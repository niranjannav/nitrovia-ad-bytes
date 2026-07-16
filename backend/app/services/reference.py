"""F2 — Reference Video → Format Template.

Downloads user-supplied reference videos (yt-dlp; manual upload fallback),
transcribes them (Whisper), samples frames (ffmpeg), then has Claude extract a
reusable format template: hook type, beat structure with timings, pacing,
caption style, CTA placement.

Legal note (PRD): reference videos are analyzed for structure only, never
republished or trained on. Downloads are transient — the stored copy is
deleted once analysis completes.
"""

import asyncio
import subprocess
import tempfile
from pathlib import Path

from .. import db, storage
from ..config import MissingKeyError
from ..providers import audio, llm

FORMAT_TEMPLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "hook_type": {"type": "string", "description": "e.g. question, bold claim, POV, before/after"},
        "total_duration_s": {"type": "number"},
        "pacing": {"type": "string", "description": "e.g. rapid cuts every 1-2s, slow build"},
        "caption_style": {"type": "string"},
        "cta_placement": {"type": "string"},
        "audio_style": {"type": "string"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "t_start": {"type": "number"},
                    "t_end": {"type": "number"},
                    "purpose": {"type": "string", "description": "hook | context | product | social proof | cta ..."},
                    "visual_pattern": {"type": "string"},
                    "vo_pattern": {"type": "string"},
                },
                "required": ["t_start", "t_end", "purpose", "visual_pattern", "vo_pattern"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["hook_type", "total_duration_s", "pacing", "caption_style", "cta_placement", "audio_style", "beats"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """You analyze short-form videos (TikTok/Reels/Shorts) and extract their FORMAT — the reusable structure, not the content.
You receive sampled frames (in chronological order) and the transcript. Produce a format template another brand could adapt:
hook mechanics, beat-by-beat structure with timings, pacing, caption style, and CTA placement.
Describe patterns abstractly (e.g. "close-up product reveal with punch-in") so they transfer across brands."""


async def _run_cmd(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(*args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {stderr.decode()[-800:]}")


async def download_reference(url: str, dest_dir: Path) -> Path:
    out = dest_dir / "reference.%(ext)s"
    await _run_cmd(
        "yt-dlp", "--no-playlist", "-f", "mp4/best", "--max-filesize", "200M",
        "-o", str(out), url,
    )
    files = list(dest_dir.glob("reference.*"))
    if not files:
        raise RuntimeError("yt-dlp produced no file — the platform may be blocking downloads; upload a screen recording instead.")
    return files[0]


async def sample_frames(video: Path, dest_dir: Path, max_frames: int = 8) -> list[Path]:
    # ~1 frame per 4s capped at max_frames, scaled down for the vision model
    await _run_cmd(
        "ffmpeg", "-y", "-i", str(video), "-vf", "fps=1/4,scale=512:-2",
        "-frames:v", str(max_frames), "-q:v", "4", str(dest_dir / "frame_%02d.jpg"),
    )
    return sorted(dest_dir.glob("frame_*.jpg"))


async def extract_audio(video: Path, dest_dir: Path) -> Path:
    out = dest_dir / "audio.mp3"
    await _run_cmd("ffmpeg", "-y", "-i", str(video), "-vn", "-acodec", "libmp3lame", "-b:a", "64k", str(out))
    return out


async def process_reference(reference_id: str):
    """Download + transcribe + frame-sample one reference video."""
    ref = await db.fetchrow("SELECT * FROM reference_videos WHERE id = $1", reference_id)
    if not ref:
        raise ValueError(f"reference {reference_id} not found")
    await db.execute("UPDATE reference_videos SET status = 'processing', error = NULL WHERE id = $1", reference_id)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        if ref["source"] == "upload" and ref["storage_path"]:
            video = tmp_dir / "reference.mp4"
            video.write_bytes(await storage.download(ref["storage_path"]))
        else:
            video = await download_reference(ref["url"], tmp_dir)

        transcript = ""
        try:
            audio_file = await extract_audio(video, tmp_dir)
            transcript = await audio.transcribe(audio_file)
        except MissingKeyError as e:
            transcript = f"(transcript unavailable — {e})"

        frames = await sample_frames(video, tmp_dir)
        frame_paths = []
        for i, frame in enumerate(frames):
            path = f"references/{reference_id}/frame_{i:02d}.jpg"
            await storage.upload(path, frame.read_bytes(), "image/jpeg")
            frame_paths.append(path)

    # storage_path is cleared: the downloaded video is transient by design
    # (PRD legal note); only the sampled frames + transcript persist.
    await db.execute(
        "UPDATE reference_videos SET status = 'analyzed', transcript = $2, storage_path = NULL WHERE id = $1",
        reference_id, transcript,
    )
    return frame_paths


async def extract_template(reference_ids: list[str], name: str) -> str:
    """Combine analyzed references into one format template (Claude vision)."""
    images: list[bytes] = []
    transcripts: list[str] = []
    for rid in reference_ids:
        ref = await db.fetchrow("SELECT * FROM reference_videos WHERE id = $1", rid)
        if not ref or ref["status"] != "analyzed":
            raise RuntimeError(f"reference {rid} is not analyzed yet")
        transcripts.append(ref.get("transcript") or "")
        # up to 4 frames per reference to keep the request lean
        for i in range(4):
            try:
                images.append(await storage.download(f"references/{rid}/frame_{i:02d}.jpg"))
            except Exception:
                break

    user = "Transcripts of the reference videos (in order):\n\n" + "\n\n---\n\n".join(
        f"Reference {i + 1}: {t}" for i, t in enumerate(transcripts)
    )
    template = await llm.complete_json_with_images(EXTRACT_SYSTEM, user, images, FORMAT_TEMPLATE_SCHEMA)
    row = await db.fetchrow(
        "INSERT INTO format_templates (name, reference_ids, template) VALUES ($1, $2::uuid[], $3) RETURNING id",
        name, reference_ids, template,
    )
    return str(row["id"])
