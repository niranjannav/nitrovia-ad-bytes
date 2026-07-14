"""fal.ai image (Flux) and video (Veo 3.1 image-to-video) generation.

Model endpoints are env-configurable (FAL_IMAGE_MODEL / FAL_VIDEO_MODEL) since
fal's catalog shifts; defaults are current as of mid-2026."""

import os

import httpx

from ..config import require, settings


def _ensure_key():
    os.environ["FAL_KEY"] = require("fal")


async def _run(model: str, arguments: dict) -> dict:
    _ensure_key()
    import fal_client

    return await fal_client.run_async(model, arguments=arguments)


async def generate_image(prompt: str, width: int = 1080, height: int = 1920) -> bytes:
    """Text-to-image via Flux; returns raw image bytes (9:16 portrait default)."""
    result = await _run(
        settings.fal_image_model,
        {
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
            "num_images": 1,
            "enable_safety_checker": True,
        },
    )
    url = result["images"][0]["url"]
    return await _download(url)


async def generate_video(image_url: str, prompt: str, duration_s: int) -> bytes:
    """Image-to-video via Veo 3.1 Fast; returns MP4 bytes."""
    result = await _run(
        settings.fal_video_model,
        {
            "image_url": image_url,
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "duration": f"{min(max(duration_s, 4), 8)}s",
            "generate_audio": False,
            "resolution": "720p",
        },
    )
    url = result["video"]["url"]
    return await _download(url)


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content
