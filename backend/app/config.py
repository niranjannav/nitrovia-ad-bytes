"""Central configuration. Every provider key is optional at boot: the app starts
with an empty .env and reports what is missing via /health. Services raise
MissingKeyError at call time so the UI can tell the user exactly which env var
to fill.

Audio + embedding capabilities (tts / embeddings / stt) are independently
configurable and can each point at a cloud provider or a model running locally
(e.g. on an Apple Silicon Mac) — see .env.example for recipes."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Load .env from the repo root (one level above backend/) as well as CWD.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
if _REPO_ROOT_ENV.exists():
    load_dotenv(_REPO_ROOT_ENV)
load_dotenv()


class Settings(BaseSettings):
    # ---- API keys (fill in .env) ----
    anthropic_api_key: str = ""
    fal_key: str = ""
    openrouter_api_key: str = ""  # free NVIDIA embeddings via OpenRouter
    openai_api_key: str = ""      # optional — only STT (Whisper) uses it by default
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""
    shopify_admin_token: str = ""  # optional; public /products.json used otherwise

    # ---- Script/vision model (Claude) ----
    claude_model: str = "claude-opus-4-8"

    # ---- TTS (voiceover) — cheapest first: Kokoro 82M ----
    # "fal"               -> Kokoro hosted on fal.ai (reuses FAL_KEY, ~$0.02/1k chars)
    # "local"             -> in-process kokoro-onnx ($0; pip install -r requirements-local.txt)
    # "openai_compatible" -> any /v1/audio/speech endpoint (OpenAI, DeepInfra,
    #                        a local Kokoro-FastAPI server, ...)
    tts_provider: str = "fal"
    tts_voice: str = "af_heart"
    tts_speed: float = 1.0
    fal_tts_model: str = "fal-ai/kokoro/american-english"
    tts_base_url: str = "https://api.openai.com/v1"
    tts_api_key: str = ""  # falls back to OPENAI_API_KEY
    tts_model: str = "tts-1"
    kokoro_model_dir: str = str(Path.home() / ".cache" / "nitroclip" / "kokoro")

    # ---- Embeddings — any OpenAI-compatible endpoint ----
    # Default: NVIDIA's free model on OpenRouter. Local: point base_url at
    # Ollama (http://localhost:11434/v1) with e.g. model nomic-embed-text.
    embeddings_base_url: str = "https://openrouter.ai/api/v1"
    embeddings_api_key: str = ""  # falls back to OPENROUTER_API_KEY
    embeddings_model: str = "nvidia/llama-nemotron-embed-vl-1b-v2:free"

    # ---- STT (reference-video transcription) — any OpenAI-compatible endpoint ----
    # Default: OpenAI Whisper. Local: point base_url at speaches / LM Studio.
    stt_base_url: str = "https://api.openai.com/v1"
    stt_api_key: str = ""  # falls back to OPENAI_API_KEY
    stt_model: str = "whisper-1"

    # ---- Image/video generation (fal.ai) ----
    fal_image_model: str = "fal-ai/flux/dev"
    fal_video_model: str = "fal-ai/veo3.1/fast/image-to-video"

    # ---- App behavior ----
    storage_bucket: str = "nitroclip"
    run_worker: bool = True
    segment_video_seconds: int = 6  # Veo 3.1 supports up to 8s per generation
    max_products_ingest: int = 250
    cors_origins: str = "*"

    # ---- Cost accounting estimates (USD; providers don't return spend) ----
    est_image_cost: float = 0.05
    est_video_cost_per_sec: float = 0.15
    est_tts_cost: float = 0.01

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


class MissingKeyError(Exception):
    """Raised when an action needs a provider key that isn't configured."""

    def __init__(self, provider: str, env_var: str, purpose: str):
        self.provider = provider
        self.env_var = env_var
        self.purpose = purpose
        super().__init__(f"Set {env_var} in .env to enable {purpose}.")


# ---- Static providers: name -> (settings attr, env var, what it unlocks) ----
STATIC_PROVIDERS = {
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY", "script generation, brand voice, format extraction and captions (Claude)"),
    "fal": ("fal_key", "FAL_KEY", "image generation (Flux) and video generation (Veo 3.1) via fal.ai"),
    "supabase": ("supabase_url", "SUPABASE_URL", "media storage (Supabase Storage)"),
    "supabase_key": ("supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY", "media storage auth (Supabase service role key)"),
    "database": ("database_url", "DATABASE_URL", "the Postgres database (Supabase connection string)"),
}


def _is_local_url(url: str) -> bool:
    """Local endpoints (Ollama, Kokoro-FastAPI, speaches, ...) need no API key."""
    return any(h in url for h in ("localhost", "127.0.0.1", "host.docker.internal"))


def _tts_status() -> tuple[bool, str, str, str]:
    """-> (configured, env_var hint, purpose, resolved key)"""
    provider = settings.tts_provider
    if provider == "local":
        return True, "TTS_PROVIDER", "voiceover (Kokoro 82M, in-process)", ""
    if provider == "fal":
        return bool(settings.fal_key), "FAL_KEY", "voiceover (Kokoro 82M on fal.ai)", settings.fal_key
    key = settings.tts_api_key or settings.openai_api_key
    ok = bool(key) or _is_local_url(settings.tts_base_url)
    return ok, "TTS_API_KEY", f"voiceover via {settings.tts_base_url}", key


def _embeddings_status() -> tuple[bool, str, str, str]:
    key = settings.embeddings_api_key or settings.openrouter_api_key
    ok = bool(key) or _is_local_url(settings.embeddings_base_url)
    return ok, "OPENROUTER_API_KEY", "product embeddings for semantic retrieval (free NVIDIA model on OpenRouter, or a local endpoint)", key


def _stt_status() -> tuple[bool, str, str, str]:
    key = settings.stt_api_key or settings.openai_api_key
    ok = bool(key) or _is_local_url(settings.stt_base_url)
    return ok, "OPENAI_API_KEY", "reference-video transcription (Whisper, or a local endpoint)", key


CAPABILITIES = {
    "tts": _tts_status,
    "embeddings": _embeddings_status,
    "stt": _stt_status,
}


def provider_status() -> dict[str, bool]:
    status = {name: bool(getattr(settings, attr)) for name, (attr, _, _) in STATIC_PROVIDERS.items()}
    for name, resolver in CAPABILITIES.items():
        status[name] = resolver()[0]
    return status


def require(provider: str) -> str:
    """Return the resolved key for a provider/capability, or raise MissingKeyError.
    Capabilities backed by a local endpoint resolve to an empty key — that's fine,
    OpenAI-compatible local servers ignore the Authorization header."""
    if provider in STATIC_PROVIDERS:
        attr, env_var, purpose = STATIC_PROVIDERS[provider]
        value = getattr(settings, attr)
        if not value:
            raise MissingKeyError(provider, env_var, purpose)
        return value
    ok, env_var, purpose, value = CAPABILITIES[provider]()
    if not ok:
        raise MissingKeyError(provider, env_var, purpose)
    return value


def ffmpeg_available() -> bool:
    from shutil import which

    return which("ffmpeg") is not None and which("ffprobe") is not None


def music_dir() -> Path:
    return Path(os.environ.get("MUSIC_DIR", Path(__file__).resolve().parents[1] / "assets" / "music"))
