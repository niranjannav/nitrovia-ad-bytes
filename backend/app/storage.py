"""Supabase Storage via its REST API (no SDK dependency). The bucket is created
as public on first use so the frontend can render media via plain URLs —
acceptable for v1 single-tenant deployments."""

import httpx

from .config import require, settings

_bucket_ready = False


def _base() -> tuple[str, dict]:
    url = require("supabase").rstrip("/")
    key = require("supabase_key")
    return url, {"Authorization": f"Bearer {key}", "apikey": key}


async def ensure_bucket():
    global _bucket_ready
    if _bucket_ready:
        return
    url, headers = _base()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{url}/storage/v1/bucket",
            headers=headers,
            json={"id": settings.storage_bucket, "name": settings.storage_bucket, "public": True},
        )
        if r.status_code not in (200, 201) and "already exists" not in r.text.lower() and r.status_code != 409:
            r.raise_for_status()
    _bucket_ready = True


async def upload(path: str, content: bytes, content_type: str) -> str:
    """Upload bytes; returns the storage path (bucket-relative)."""
    await ensure_bucket()
    url, headers = _base()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{url}/storage/v1/object/{settings.storage_bucket}/{path}",
            headers={**headers, "Content-Type": content_type, "x-upsert": "true"},
            content=content,
        )
        r.raise_for_status()
    return path


async def download(path: str) -> bytes:
    url, headers = _base()
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(f"{url}/storage/v1/object/{settings.storage_bucket}/{path}", headers=headers)
        r.raise_for_status()
        return r.content


def public_url(path: str | None) -> str | None:
    if not path:
        return None
    url = settings.supabase_url.rstrip("/")
    return f"{url}/storage/v1/object/public/{settings.storage_bucket}/{path}"
