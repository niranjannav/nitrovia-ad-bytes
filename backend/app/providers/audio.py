"""OpenAI-backed audio + embeddings: Whisper transcription for reference
videos, TTS voiceover for segments, embeddings for pgvector retrieval."""

from pathlib import Path

from openai import AsyncOpenAI

from ..config import require, settings


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=require("openai"))


async def transcribe(path: Path) -> str:
    client = _client()
    with open(path, "rb") as f:
        result = await client.audio.transcriptions.create(model=settings.openai_whisper_model, file=f)
    return result.text


async def tts(text: str) -> bytes:
    client = _client()
    result = await client.audio.speech.create(
        model=settings.openai_tts_model,
        voice=settings.openai_tts_voice,
        input=text,
        response_format="mp3",
    )
    return result.content


async def embed(texts: list[str]) -> list[list[float]]:
    client = _client()
    result = await client.embeddings.create(model=settings.openai_embedding_model, input=texts)
    return [d.embedding for d in result.data]
