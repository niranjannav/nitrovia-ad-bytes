"""Central configuration. Every provider key is optional at boot: the app starts
with an empty .env and reports what is missing via /health. Services raise
MissingKeyError at call time so the UI can tell the user exactly which env var
to fill."""

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
    openai_api_key: str = ""
    fal_key: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""
    shopify_admin_token: str = ""  # optional; public /products.json used otherwise

    # ---- Model / provider tuning (sensible defaults, override in .env) ----
    claude_model: str = "claude-opus-4-8"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "alloy"
    openai_whisper_model: str = "whisper-1"
    openai_embedding_model: str = "text-embedding-3-small"
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
    est_tts_cost: float = 0.02

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


class MissingKeyError(Exception):
    """Raised when an action needs a provider key that isn't configured."""

    def __init__(self, provider: str, env_var: str, purpose: str):
        self.provider = provider
        self.env_var = env_var
        self.purpose = purpose
        super().__init__(f"Set {env_var} in .env to enable {purpose}.")


# provider -> (settings attr, env var, what it unlocks)
PROVIDERS = {
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY", "script generation, brand voice, format extraction and captions (Claude)"),
    "openai": ("openai_api_key", "OPENAI_API_KEY", "reference-video transcription, voiceover and product embeddings (OpenAI)"),
    "fal": ("fal_key", "FAL_KEY", "image generation (Flux) and video generation (Veo 3.1) via fal.ai"),
    "supabase": ("supabase_url", "SUPABASE_URL", "media storage (Supabase Storage)"),
    "supabase_key": ("supabase_service_role_key", "SUPABASE_SERVICE_ROLE_KEY", "media storage auth (Supabase service role key)"),
    "database": ("database_url", "DATABASE_URL", "the Postgres database (Supabase connection string)"),
}


def provider_status() -> dict[str, bool]:
    return {name: bool(getattr(settings, attr)) for name, (attr, _, _) in PROVIDERS.items()}


def require(provider: str) -> str:
    attr, env_var, purpose = PROVIDERS[provider]
    value = getattr(settings, attr)
    if not value:
        raise MissingKeyError(provider, env_var, purpose)
    return value


def ffmpeg_available() -> bool:
    from shutil import which

    return which("ffmpeg") is not None and which("ffprobe") is not None


def music_dir() -> Path:
    return Path(os.environ.get("MUSIC_DIR", Path(__file__).resolve().parents[1] / "assets" / "music"))
