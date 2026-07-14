from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs, storage
from ..services.ingest import normalize_store_url

router = APIRouter(prefix="/api/brands", tags=["brands"])


class BrandCreate(BaseModel):
    name: str
    store_url: str


class VoiceUpdate(BaseModel):
    content_md: str
    approve: bool = False


@router.get("")
async def list_brands():
    return await db.fetch(
        """SELECT b.*, (SELECT COUNT(*) FROM products p WHERE p.brand_id = b.id) AS product_count
           FROM brands b ORDER BY b.created_at DESC"""
    )


@router.post("", status_code=201)
async def create_brand(body: BrandCreate):
    url = normalize_store_url(body.store_url)
    brand = await db.fetchrow(
        "INSERT INTO brands (name, store_url) VALUES ($1, $2) RETURNING *", body.name.strip(), url
    )
    await jobs.enqueue("ingest_brand", {"brand_id": str(brand["id"])}, brand_id=str(brand["id"]))
    return brand


@router.get("/{brand_id}")
async def get_brand(brand_id: str):
    brand = await db.fetchrow("SELECT * FROM brands WHERE id = $1", brand_id)
    if not brand:
        raise HTTPException(404, "brand not found")
    brand["product_count"] = await db.fetchval("SELECT COUNT(*) FROM products WHERE brand_id = $1", brand_id)
    return brand


@router.post("/{brand_id}/reingest")
async def reingest_brand(brand_id: str):
    brand = await db.fetchrow("SELECT id FROM brands WHERE id = $1", brand_id)
    if not brand:
        raise HTTPException(404, "brand not found")
    return await jobs.enqueue("ingest_brand", {"brand_id": brand_id}, brand_id=brand_id)


@router.get("/{brand_id}/products")
async def list_products(brand_id: str):
    products = await db.fetch(
        "SELECT * FROM products WHERE brand_id = $1 ORDER BY created_at DESC LIMIT 500", brand_id
    )
    for p in products:
        shots = await db.fetch(
            "SELECT id, kind, storage_path FROM assets WHERE product_id = $1 ORDER BY created_at", p["id"]
        )
        p["assets"] = [{**a, "url": storage.public_url(a["storage_path"])} for a in shots]
    return products


@router.get("/{brand_id}/voice")
async def get_voice(brand_id: str):
    voice = await db.fetchrow(
        "SELECT * FROM brand_voice WHERE brand_id = $1 ORDER BY version DESC LIMIT 1", brand_id
    )
    return voice or {}


@router.put("/{brand_id}/voice")
async def update_voice(brand_id: str, body: VoiceUpdate):
    version = (await db.fetchval("SELECT COALESCE(MAX(version), 0) FROM brand_voice WHERE brand_id = $1", brand_id)) + 1
    return await db.fetchrow(
        "INSERT INTO brand_voice (brand_id, version, content_md, status) VALUES ($1,$2,$3,$4) RETURNING *",
        brand_id, version, body.content_md, "approved" if body.approve else "draft",
    )
