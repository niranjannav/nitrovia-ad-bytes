"""Audio + embeddings, each independently switchable between cloud and local:

  TTS         Kokoro 82M — hosted on fal.ai (default, reuses FAL_KEY), run
              in-process via kokoro-onnx (TTS_PROVIDER=local, $0 on a Mac), or
              any OpenAI-compatible /v1/audio/speech endpoint.
  Embeddings  Any OpenAI-compatible endpoint. Default: NVIDIA's free model on
              OpenRouter. Local: Ollama at http://localhost:11434/v1.
  STT         Any OpenAI-compatible /v1/audio/transcriptions endpoint.
              Default: OpenAI Whisper. Local: speaches / LM Studio.
"""

import asyncio
import io
import wave
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from ..config import require, settings

# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------


async def tts(text: str) -> tuple[bytes, str, str]:
    """Synthesize voiceover. Returns (audio bytes, file extension, mime type)."""
    require("tts")
    provider = settings.tts_provider
    if provider == "fal":
        return await _tts_fal(text)
    if provider == "local":
        return await _tts_local(text)
    if provider == "openai_compatible":
        return await _tts_openai_compatible(text)
    raise ValueError(f"TTS_PROVIDER must be fal | local | openai_compatible, got {provider!r}")


def tts_provider_label() -> str:
    return {
        "fal": f"fal:{settings.fal_tts_model}",
        "local": "kokoro-onnx:local",
        "openai_compatible": f"{settings.tts_base_url}#{settings.tts_model}",
    }.get(settings.tts_provider, settings.tts_provider)


async def _tts_fal(text: str) -> tuple[bytes, str, str]:
    from . import media

    result = await media.run_fal(
        settings.fal_tts_model,
        {"prompt": text, "voice": settings.tts_voice, "speed": settings.tts_speed},
    )
    url = result["audio"]["url"]
    ext = "mp3" if url.split("?")[0].endswith(".mp3") else "wav"
    return await media.download(url), ext, ("audio/mpeg" if ext == "mp3" else "audio/wav")


# kokoro-onnx model files, fetched once into KOKORO_MODEL_DIR (~330MB total)
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}

_kokoro = None


async def _kokoro_instance():
    global _kokoro
    if _kokoro is not None:
        return _kokoro
    try:
        from kokoro_onnx import Kokoro
    except ImportError as e:
        raise RuntimeError(
            "TTS_PROVIDER=local needs the kokoro-onnx package — run: "
            "backend/.venv/bin/pip install -r backend/requirements-local.txt"
        ) from e

    model_dir = Path(settings.kokoro_model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, url in KOKORO_FILES.items():
        dest = model_dir / name
        if dest.exists():
            continue
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            async with client.stream("GET", url) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(".part")
                with open(tmp, "wb") as f:
                    async for chunk in r.aiter_bytes(1 << 20):
                        f.write(chunk)
                tmp.rename(dest)

    _kokoro = await asyncio.to_thread(Kokoro, str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin"))
    return _kokoro


async def _tts_local(text: str) -> tuple[bytes, str, str]:
    kokoro = await _kokoro_instance()
    samples, sample_rate = await asyncio.to_thread(
        kokoro.create, text, voice=settings.tts_voice, speed=settings.tts_speed, lang="en-us"
    )
    return encode_wav(samples, sample_rate), "wav", "audio/wav"


def encode_wav(samples, sample_rate: int) -> bytes:
    """float32 [-1, 1] samples -> 16-bit mono WAV (stdlib only, so the base
    install can run tests without numpy)."""
    try:
        import numpy as np

        pcm = (np.clip(np.asarray(samples), -1.0, 1.0) * 32767).astype("<i2").tobytes()
    except ImportError:
        import array

        pcm = array.array("h", (int(max(-1.0, min(1.0, float(s))) * 32767) for s in samples)).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


async def _tts_openai_compatible(text: str) -> tuple[bytes, str, str]:
    key = settings.tts_api_key or settings.openai_api_key or "local"
    client = AsyncOpenAI(base_url=settings.tts_base_url, api_key=key)
    result = await client.audio.speech.create(
        model=settings.tts_model,
        voice=settings.tts_voice,
        input=text,
        response_format="mp3",
    )
    return result.content, "mp3", "audio/mpeg"


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


async def embed(texts: list[str]) -> list[list[float]]:
    key = require("embeddings") or "local"
    client = AsyncOpenAI(base_url=settings.embeddings_base_url, api_key=key)
    # Note: NVIDIA NIMs natively take an input_type (query/passage) parameter;
    # OpenRouter handles that server-side. If retrieval quality disappoints,
    # pass extra_body={"input_type": ...} here.
    result = await client.embeddings.create(model=settings.embeddings_model, input=texts)
    return [d.embedding for d in result.data]


# ---------------------------------------------------------------------------
# STT
# ---------------------------------------------------------------------------


async def transcribe(path: Path) -> str:
    key = require("stt") or "local"
    client = AsyncOpenAI(base_url=settings.stt_base_url, api_key=key)
    with open(path, "rb") as f:
        result = await client.audio.transcriptions.create(model=settings.stt_model, file=f)
    return result.text
