"""F5 — assembly. Local ffmpeg, effectively free — which is what makes
per-segment regeneration + restitch cheap.

Per segment: normalize to 1080x1920/30fps h264, trim to the scripted duration,
burn the caption, mux the TTS voiceover. Then concat, and mix a royalty-free
music bed under everything if one exists in backend/assets/music/."""

import asyncio
import random
import subprocess
import tempfile
from pathlib import Path

from .. import db, storage
from ..config import music_dir

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font() -> str | None:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


async def _ffmpeg(*args: str):
    proc = await asyncio.create_subprocess_exec("ffmpeg", "-y", *args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr.decode()[-1200:]}")


def build_segment_filter(caption: str, duration: float, caption_file: Path | None) -> str:
    """Video filter chain for one segment: normalize + burn caption."""
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=yuv420p"
    font = _font()
    if caption.strip() and caption_file is not None and font:
        vf += (
            f",drawtext=fontfile={font}:textfile={caption_file}:fontcolor=white:fontsize=64:"
            "borderw=4:bordercolor=black@0.85:x=(w-text_w)/2:y=h*0.78:line_spacing=12"
        )
    return vf


async def _render_one_segment(segment: dict, work: Path, index: int) -> Path:
    duration = float(segment["t_end"]) - float(segment["t_start"])
    video_render = await db.fetchrow("SELECT * FROM renders WHERE id = $1", segment["selected_video_render_id"])
    if not video_render:
        raise RuntimeError(f"segment {segment['idx'] + 1} has no video render")
    src = work / f"seg_{index}_src.mp4"
    src.write_bytes(await storage.download(video_render["storage_path"]))

    caption_file = None
    if (segment["caption"] or "").strip():
        caption_file = work / f"seg_{index}_caption.txt"
        caption_file.write_text(segment["caption"].strip())

    out = work / f"seg_{index}.mp4"
    args = ["-i", str(src)]

    audio_render = None
    if segment["selected_audio_render_id"]:
        audio_render = await db.fetchrow("SELECT * FROM renders WHERE id = $1", segment["selected_audio_render_id"])
    if audio_render:
        vo = work / f"seg_{index}_vo.mp3"
        vo.write_bytes(await storage.download(audio_render["storage_path"]))
        args += ["-i", str(vo)]
        audio_map = ["-map", "0:v", "-map", "1:a", "-af", "apad"]
    else:
        # silent track keeps concat streams consistent
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        audio_map = ["-map", "0:v", "-map", "1:a"]

    await _ffmpeg(
        *args,
        "-vf", build_segment_filter(segment["caption"] or "", duration, caption_file),
        *audio_map,
        "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        str(out),
    )
    return out


async def stitch_project(project_id: str) -> str:
    project = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise ValueError(f"project {project_id} not found")
    await db.execute("UPDATE projects SET status = 'stitching', error = NULL WHERE id = $1", project_id)
    segments = await db.fetch(
        "SELECT * FROM segments WHERE project_id = $1 AND version = $2 ORDER BY idx",
        project_id, project["script_version"],
    )
    if not segments:
        raise RuntimeError("no segments to stitch")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        parts = []
        for i, segment in enumerate(segments):
            parts.append(await _render_one_segment(segment, work, i))

        concat_list = work / "concat.txt"
        concat_list.write_text("\n".join(f"file '{p}'" for p in parts))
        joined = work / "joined.mp4"
        await _ffmpeg("-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(joined))

        final = joined
        beds = sorted(music_dir().glob("*.mp3")) if music_dir().exists() else []
        if beds:
            bed = random.choice(beds)
            mixed = work / "final.mp4"
            await _ffmpeg(
                "-i", str(joined), "-stream_loop", "-1", "-i", str(bed),
                "-filter_complex", "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
                str(mixed),
            )
            final = mixed

        path = f"projects/{project_id}/final.mp4"
        await storage.upload(path, final.read_bytes(), "video/mp4")

    await db.execute("UPDATE projects SET status = 'ready', final_video_path = $2 WHERE id = $1", project_id, path)
    return path
