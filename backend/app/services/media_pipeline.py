"""F4/F5/F6 — per-segment media generation.

The segment is the unit of work: image → (composite) → video → voiceover all
attach to it, each as a versioned render. Regeneration re-runs any subset of
stages. Server-side rule: nothing here runs on a segment that was never
approved (a rejected script costs cents; a rejected render costs dollars)."""

from .. import db, storage
from ..config import settings
from ..providers import audio, media
from . import compositing

STYLE_SUFFIX = (
    "Vertical 9:16 composition, photorealistic, natural lighting, shot on a modern mirrorless camera, "
    "crisp social-media-ready aesthetic. No text, no watermarks, no logos rendered by the model."
)


async def _next_render_version(segment_id: str, rtype: str) -> int:
    v = await db.fetchval(
        "SELECT COALESCE(MAX(version), 0) FROM renders WHERE segment_id = $1 AND type = $2", segment_id, rtype
    )
    return v + 1


async def _add_render(segment_id: str, rtype: str, provider: str, path: str, prompt: str | None, cost: float, meta: dict | None = None) -> dict:
    version = await _next_render_version(segment_id, rtype)
    row = await db.fetchrow(
        """INSERT INTO renders (segment_id, type, provider, version, storage_path, prompt, cost, meta)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
        segment_id, rtype, provider, version, path, prompt, cost, meta or {},
    )
    await db.execute("UPDATE segments SET cost_accum = cost_accum + $2 WHERE id = $1", segment_id, cost)
    return row


def _segment_duration(segment: dict) -> int:
    dur = float(segment["t_end"]) - float(segment["t_start"])
    return int(min(max(round(dur), 4), 8))


async def render_segment(segment_id: str, do_image: bool = True, do_video: bool = True, do_tts: bool = True):
    segment = await db.fetchrow("SELECT * FROM segments WHERE id = $1", segment_id)
    if not segment:
        raise ValueError(f"segment {segment_id} not found")
    if segment["status"] == "draft":
        raise RuntimeError("segment is not approved — approve the script before generating media")
    await db.execute("UPDATE segments SET status = 'generating', error = NULL WHERE id = $1", segment_id)

    project_id = segment["project_id"]

    if do_image:
        await generate_segment_image(segment)
        segment = await db.fetchrow("SELECT * FROM segments WHERE id = $1", segment_id)
    await db.execute("UPDATE segments SET status = 'image_ready' WHERE id = $1", segment_id)

    if do_video:
        await generate_segment_video(segment)
    await db.execute("UPDATE segments SET status = 'video_ready' WHERE id = $1", segment_id)

    if do_tts and (segment["vo_text"] or "").strip():
        await generate_segment_tts(segment)

    await db.execute("UPDATE segments SET status = 'ready' WHERE id = $1", segment_id)
    return project_id


async def generate_segment_image(segment: dict):
    prompt = f"{segment['visual_direction']}. {STYLE_SUFFIX}"
    image_bytes = await media.generate_image(prompt)
    meta = {"composited": False}

    # POD fidelity: composite the real design file onto the generated scene.
    if segment["product_id"]:
        design = await db.fetchrow(
            "SELECT storage_path FROM assets WHERE product_id = $1 AND kind = 'design_file' ORDER BY created_at LIMIT 1",
            segment["product_id"],
        )
        if design:
            try:
                design_bytes = await storage.download(design["storage_path"])
                image_bytes = compositing.composite_design(image_bytes, design_bytes)
                meta["composited"] = True
            except Exception as e:
                meta["composite_error"] = str(e)[:300]  # fall back to the raw scene

    path = f"projects/{segment['project_id']}/segments/{segment['id']}/image_v{await _next_render_version(str(segment['id']), 'image')}.jpg"
    await storage.upload(path, image_bytes, "image/jpeg")
    render = await _add_render(str(segment["id"]), "image", "fal:" + settings.fal_image_model, path, prompt, settings.est_image_cost, meta)
    await db.execute("UPDATE segments SET selected_image_render_id = $2 WHERE id = $1", segment["id"], render["id"])


async def generate_segment_video(segment: dict):
    image_render = await db.fetchrow(
        "SELECT * FROM renders WHERE id = $1", segment["selected_image_render_id"]
    )
    if not image_render:
        raise RuntimeError("segment has no image to animate — generate an image first")
    image_url = storage.public_url(image_render["storage_path"])
    duration = _segment_duration(segment)
    prompt = (
        f"{segment['visual_direction']}. Subtle, natural motion; keep the subject and any printed design "
        f"stable and legible. Smooth cinematic camera movement."
    )
    video_bytes = await media.generate_video(image_url, prompt, duration)
    path = f"projects/{segment['project_id']}/segments/{segment['id']}/video_v{await _next_render_version(str(segment['id']), 'video')}.mp4"
    await storage.upload(path, video_bytes, "video/mp4")
    cost = settings.est_video_cost_per_sec * duration
    render = await _add_render(str(segment["id"]), "video", "fal:" + settings.fal_video_model, path, prompt, cost, {"duration_s": duration})
    await db.execute("UPDATE segments SET selected_video_render_id = $2 WHERE id = $1", segment["id"], render["id"])


async def generate_segment_tts(segment: dict):
    audio_bytes, ext, mime = await audio.tts(segment["vo_text"])
    path = f"projects/{segment['project_id']}/segments/{segment['id']}/vo_v{await _next_render_version(str(segment['id']), 'audio')}.{ext}"
    await storage.upload(path, audio_bytes, mime)
    cost = 0.0 if settings.tts_provider == "local" else settings.est_tts_cost
    render = await _add_render(str(segment["id"]), "audio", audio.tts_provider_label(), path, segment["vo_text"], cost)
    await db.execute("UPDATE segments SET selected_audio_render_id = $2 WHERE id = $1", segment["id"], render["id"])


async def all_segments_ready(project_id: str) -> bool:
    project = await db.fetchrow("SELECT script_version FROM projects WHERE id = $1", project_id)
    pending = await db.fetchval(
        "SELECT COUNT(*) FROM segments WHERE project_id = $1 AND version = $2 AND status != 'ready'",
        project_id, project["script_version"],
    )
    return pending == 0
