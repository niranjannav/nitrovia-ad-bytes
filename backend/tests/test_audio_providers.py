import math
import wave
import io

import pytest

from app import config
from app.config import MissingKeyError, settings
from app.providers import audio
from app.services import storyboard


# ---- TTS provider dispatch ------------------------------------------------


async def test_tts_dispatches_to_fal(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "fal")
    monkeypatch.setattr(settings, "fal_key", "fake-key")
    called = {}

    async def fake_fal(text):
        called["backend"] = "fal"
        return b"audio", "wav", "audio/wav"

    monkeypatch.setattr(audio, "_tts_fal", fake_fal)
    result = await audio.tts("hello")
    assert called["backend"] == "fal"
    assert result == (b"audio", "wav", "audio/wav")


async def test_tts_dispatches_to_local(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "local")
    called = {}

    async def fake_local(text):
        called["backend"] = "local"
        return b"audio", "wav", "audio/wav"

    monkeypatch.setattr(audio, "_tts_local", fake_local)
    await audio.tts("hello")
    assert called["backend"] == "local"


async def test_tts_fal_requires_fal_key(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "fal")
    monkeypatch.setattr(settings, "fal_key", "")
    with pytest.raises(MissingKeyError) as exc:
        await audio.tts("hello")
    assert "FAL_KEY" in str(exc.value)


def test_local_tts_is_always_configured(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "local")
    ok, env_var, _, _ = config._tts_status()
    assert ok is True


def test_localhost_base_url_counts_as_configured(monkeypatch):
    monkeypatch.setattr(settings, "embeddings_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "embeddings_base_url", "http://localhost:11434/v1")
    assert config._embeddings_status()[0] is True
    monkeypatch.setattr(settings, "embeddings_base_url", "https://openrouter.ai/api/v1")
    assert config._embeddings_status()[0] is False


def test_tts_provider_label(monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "local")
    assert audio.tts_provider_label() == "kokoro-onnx:local"
    monkeypatch.setattr(settings, "tts_provider", "fal")
    assert settings.fal_tts_model in audio.tts_provider_label()


# ---- WAV encoding (stdlib path — no numpy in base install) -----------------


def test_encode_wav_valid_riff():
    sr = 24000
    samples = [math.sin(2 * math.pi * 440 * i / sr) * 0.5 for i in range(sr // 10)]
    data = audio.encode_wav(samples, sr)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == sr
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == len(samples)


# ---- Embeddings client configuration ---------------------------------------


class FakeEmbeddingsAPI:
    def __init__(self, record):
        self.record = record

    async def create(self, model, input):
        self.record["model"] = model
        self.record["input"] = input

        class D:
            embedding = [0.1, 0.2]

        class R:
            data = [D() for _ in input]

        return R()


class FakeOpenAI:
    last = {}

    def __init__(self, base_url=None, api_key=None):
        FakeOpenAI.last = {"base_url": base_url, "api_key": api_key}
        self.embeddings = FakeEmbeddingsAPI(FakeOpenAI.last)


async def test_embed_uses_configured_endpoint_and_model(monkeypatch):
    monkeypatch.setattr(settings, "embeddings_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "embeddings_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "or-key")
    monkeypatch.setattr(settings, "embeddings_model", "nvidia/llama-nemotron-embed-vl-1b-v2:free")
    monkeypatch.setattr(audio, "AsyncOpenAI", FakeOpenAI)

    vectors = await audio.embed(["a", "b"])
    assert len(vectors) == 2
    assert FakeOpenAI.last["base_url"] == "https://openrouter.ai/api/v1"
    assert FakeOpenAI.last["api_key"] == "or-key"
    assert FakeOpenAI.last["model"] == "nvidia/llama-nemotron-embed-vl-1b-v2:free"


# ---- Retrieval filters by embedding model -----------------------------------


async def test_retrieval_filters_by_embedding_model(monkeypatch):
    captured = {}

    async def fake_embed(texts):
        return [[0.1, 0.2, 0.3]]

    async def fake_fetch(query, *args):
        captured["query"] = query
        captured["args"] = args
        return [{"id": "p1", "title": "T", "description": "", "price": None}]

    monkeypatch.setattr(storyboard.audio, "embed", fake_embed)
    monkeypatch.setattr(storyboard.db, "fetch", fake_fetch)

    rows = await storyboard.retrieve_products("brand-1", "query")
    assert rows[0]["id"] == "p1"
    assert "embedding_model" in captured["query"]
    assert settings.embeddings_model in captured["args"]
