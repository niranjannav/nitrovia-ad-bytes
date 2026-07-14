"""Postgres-backed job queue (PRD: sufficient at v1 volume — no Redis/Celery)."""

from . import db


async def enqueue(job_type: str, payload: dict, brand_id: str | None = None, project_id: str | None = None) -> dict:
    return await db.fetchrow(
        "INSERT INTO jobs (type, payload, brand_id, project_id) VALUES ($1,$2,$3,$4) RETURNING *",
        job_type, payload, brand_id, project_id,
    )


async def enqueue_once(job_type: str, payload: dict, project_id: str) -> dict | None:
    """Enqueue unless an identical active job already exists (dedupe for chained jobs)."""
    existing = await db.fetchrow(
        "SELECT id FROM jobs WHERE type = $1 AND project_id = $2 AND status IN ('queued','running')",
        job_type, project_id,
    )
    if existing:
        return None
    return await enqueue(job_type, payload, project_id=project_id)


async def claim_next() -> dict | None:
    """Claim the oldest queued job with SKIP LOCKED so multiple workers are safe."""
    p = await db.pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """SELECT id FROM jobs WHERE status = 'queued'
                   ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"""
            )
            if not row:
                return None
            return dict(
                await conn.fetchrow(
                    """UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = now()
                       WHERE id = $1 RETURNING *""",
                    row["id"],
                )
            )


async def finish(job_id, error: str | None = None):
    if error:
        await db.execute(
            "UPDATE jobs SET status = 'failed', error = $2, updated_at = now() WHERE id = $1", job_id, error[:2000]
        )
    else:
        await db.execute("UPDATE jobs SET status = 'done', updated_at = now() WHERE id = $1", job_id)
