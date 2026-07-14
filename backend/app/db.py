"""Thin asyncpg layer. Rows come back as plain dicts; JSONB columns are
encoded/decoded automatically. Migrations are plain SQL files applied in order
and tracked in schema_migrations."""

import json
from pathlib import Path
from typing import Any

import asyncpg

from .config import require

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


async def _init_conn(conn: asyncpg.Connection):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = require("database")
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=8, init=_init_conn, statement_cache_size=0)
    return _pool


async def close():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _to_dict(record: asyncpg.Record | None) -> dict | None:
    return dict(record) if record is not None else None


async def fetch(query: str, *args) -> list[dict]:
    p = await pool()
    return [dict(r) for r in await p.fetch(query, *args)]


async def fetchrow(query: str, *args) -> dict | None:
    p = await pool()
    return _to_dict(await p.fetchrow(query, *args))


async def fetchval(query: str, *args) -> Any:
    p = await pool()
    return await p.fetchval(query, *args)


async def execute(query: str, *args) -> str:
    p = await pool()
    return await p.execute(query, *args)


async def migrate() -> list[str]:
    """Apply pending SQL migrations in filename order. Returns applied names."""
    p = await pool()
    await p.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
    )
    done = {r["name"] for r in await p.fetch("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        sql = path.read_text()
        async with p.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", path.name)
        applied.append(path.name)
    return applied
