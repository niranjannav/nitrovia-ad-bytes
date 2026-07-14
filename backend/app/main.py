"""NitroClip API. Boots with an empty .env: /health reports which keys are
missing, and every endpoint that needs an unconfigured provider returns a
structured 503 the frontend renders as a "fill this key" banner."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, worker
from .config import MissingKeyError, ffmpeg_available, provider_status, settings
from .routers import brands, projects, references

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("nitroclip")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    worker_task = None
    if provider_status()["database"]:
        try:
            applied = await db.migrate()
            if applied:
                log.info("applied migrations: %s", applied)
        except Exception as e:
            log.error("migration failed: %s", e)
    else:
        log.warning("DATABASE_URL not set — API is up but data endpoints will return 503 until it is configured")
    if settings.run_worker:
        worker_task = asyncio.create_task(worker.loop(stop_event))
    yield
    stop_event.set()
    if worker_task:
        worker_task.cancel()
    await db.close()


app = FastAPI(title="NitroClip", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(MissingKeyError)
async def missing_key_handler(_: Request, exc: MissingKeyError):
    return JSONResponse(
        status_code=503,
        content={"error": "missing_key", "provider": exc.provider, "env_var": exc.env_var, "message": str(exc)},
    )


@app.get("/health")
async def health():
    status = provider_status()
    ready_to_plan = all(status[p] for p in ("anthropic", "database", "supabase", "supabase_key"))
    ready_to_generate = ready_to_plan and status["fal"] and status["openai"]
    return {
        "ok": True,
        "providers": status,
        "ffmpeg": ffmpeg_available(),
        "ready_to_plan": ready_to_plan,
        "ready_to_generate": ready_to_generate,
        "env_vars": {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "fal": "FAL_KEY",
            "supabase": "SUPABASE_URL",
            "supabase_key": "SUPABASE_SERVICE_ROLE_KEY",
            "database": "DATABASE_URL",
        },
    }


app.include_router(brands.router)
app.include_router(references.router)
app.include_router(projects.router)
