"""F1 — Brand Ingest.

Given a storefront URL:
  1. Pull the product catalog. Shopify stores expose /products.json publicly
     (paginated); an Admin token is only needed for private stores. Non-Shopify
     stores fall back to a best-effort HTML scrape of OpenGraph product data.
  2. Download product images into Supabase Storage (assets rows).
  3. Chunk + embed descriptions into pgvector (needs OPENAI_API_KEY).
  4. Draft brand_voice.md with Claude (needs ANTHROPIC_API_KEY) — reviewed by
     a human in the UI before first use.

Steps 3 and 4 degrade gracefully: missing keys are recorded as warnings on the
brand instead of failing the ingest.
"""

import html
import re
from urllib.parse import urljoin, urlparse

import httpx

from .. import db, storage
from ..config import MissingKeyError, settings
from ..providers import audio, llm

UA = {"User-Agent": "Mozilla/5.0 (compatible; NitroClip/1.0; brand-ingest)"}


def normalize_store_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return f"https://{parsed.netloc}"


async def fetch_shopify_products(base_url: str) -> list[dict] | None:
    """Read the public Shopify catalog. Returns None if this isn't Shopify."""
    products: list[dict] = []
    headers = dict(UA)
    if settings.shopify_admin_token:
        headers["X-Shopify-Access-Token"] = settings.shopify_admin_token
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
        page = 1
        while len(products) < settings.max_products_ingest:
            r = await client.get(f"{base_url}/products.json", params={"limit": 250, "page": page})
            if r.status_code != 200 or "application/json" not in r.headers.get("content-type", ""):
                return products if products else None
            batch = r.json().get("products", [])
            if not batch:
                break
            products.extend(batch)
            if len(batch) < 250:
                break
            page += 1
    return products[: settings.max_products_ingest]


async def fetch_generic_products(base_url: str) -> list[dict]:
    """Fallback for non-Shopify sites: scrape the homepage for product links and
    OpenGraph metadata. Best-effort — enough to seed a catalog for review."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=UA) as client:
        r = await client.get(base_url)
        r.raise_for_status()
        page = r.text
        hrefs = re.findall(r'href=["\']([^"\']*(?:/products?/|/shop/|/item/)[^"\']*)["\']', page)
        seen, products = set(), []
        for href in hrefs:
            url = urljoin(base_url, html.unescape(href)).split("?")[0]
            if url in seen or len(products) >= 40:
                continue
            seen.add(url)
            try:
                pr = await client.get(url)
                if pr.status_code != 200:
                    continue
                og = dict(re.findall(r'<meta[^>]+property=["\']og:(\w+)["\'][^>]+content=["\']([^"\']*)["\']', pr.text))
                title = html.unescape(og.get("title", "")) or url.rstrip("/").split("/")[-1].replace("-", " ").title()
                products.append(
                    {
                        "id": url,
                        "title": title,
                        "body_html": html.unescape(og.get("description", "")),
                        "handle": url,
                        "images": [{"src": og["image"]}] if og.get("image") else [],
                        "variants": [],
                        "tags": "",
                    }
                )
            except httpx.HTTPError:
                continue
        return products


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


async def ingest_brand(brand_id: str):
    brand = await db.fetchrow("SELECT * FROM brands WHERE id = $1", brand_id)
    if not brand:
        raise ValueError(f"brand {brand_id} not found")
    await db.execute("UPDATE brands SET status = 'ingesting' WHERE id = $1", brand_id)

    base_url = normalize_store_url(brand["store_url"])
    warnings: list[str] = []

    raw = await fetch_shopify_products(base_url)
    platform = "shopify"
    if raw is None:
        platform = "generic"
        raw = await fetch_generic_products(base_url)
    if not raw:
        raise RuntimeError(f"No products found at {base_url} — check the URL (Shopify stores expose /products.json).")

    product_ids: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=UA) as client:
        for p in raw:
            external_id = str(p.get("id"))
            description = _strip_html(p.get("body_html", ""))
            price = None
            if p.get("variants"):
                price = str(p["variants"][0].get("price") or "") or None
            handle = p.get("handle", "")
            product_url = handle if handle.startswith("http") else f"{base_url}/products/{handle}"
            tags = p.get("tags", "")
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if isinstance(tags, str) else list(tags or [])
            row = await db.fetchrow(
                """INSERT INTO products (brand_id, external_id, title, description, product_url, price, tags)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT (brand_id, external_id) DO UPDATE
                     SET title = EXCLUDED.title, description = EXCLUDED.description,
                         product_url = EXCLUDED.product_url, price = EXCLUDED.price, tags = EXCLUDED.tags
                   RETURNING id""",
                brand_id, external_id, p.get("title", "Untitled"), description, product_url, price, tag_list,
            )
            product_ids[external_id] = str(row["id"])

            for i, img in enumerate((p.get("images") or [])[:4]):
                src = img.get("src") if isinstance(img, dict) else img
                if not src:
                    continue
                exists = await db.fetchval(
                    "SELECT 1 FROM assets WHERE product_id = $1 AND source_url = $2", row["id"], src
                )
                if exists:
                    continue
                try:
                    r = await client.get(src)
                    r.raise_for_status()
                    ext = "png" if "png" in r.headers.get("content-type", "") else "jpg"
                    path = f"brands/{brand_id}/products/{row['id']}/shot_{i}.{ext}"
                    await storage.upload(path, r.content, r.headers.get("content-type", "image/jpeg"))
                    kind = "design_file" if i == 0 and platform == "shopify" and _looks_like_design(p) else "product_shot"
                    await db.execute(
                        "INSERT INTO assets (brand_id, product_id, kind, storage_path, source_url) VALUES ($1,$2,$3,$4,$5)",
                        brand_id, row["id"], kind, path, src,
                    )
                except Exception as e:  # storage/network failures shouldn't kill the ingest
                    warnings.append(f"image download failed for {p.get('title')}: {e}")

    # Embeddings (optional — needs OpenAI)
    try:
        await _embed_products(brand_id)
    except MissingKeyError as e:
        warnings.append(str(e))

    # Brand voice draft (optional — needs Anthropic)
    try:
        await draft_brand_voice(brand_id, base_url)
    except MissingKeyError as e:
        warnings.append(str(e))

    await db.execute(
        "UPDATE brands SET status = 'ready', platform = $2, meta = meta || $3::jsonb WHERE id = $1",
        brand_id, platform, {"warnings": warnings, "product_count": len(product_ids)},
    )


def _looks_like_design(product: dict) -> bool:
    """Heuristic: POD products whose first image is the flat design/print file."""
    title = (product.get("title") or "").lower()
    return any(w in title for w in ("design", "print", "graphic"))


def _chunk(text: str, size: int = 700) -> list[str]:
    words, chunks, current = text.split(), [], []
    count = 0
    for w in words:
        current.append(w)
        count += len(w) + 1
        if count >= size:
            chunks.append(" ".join(current))
            current, count = [], 0
    if current:
        chunks.append(" ".join(current))
    return chunks


async def _embed_products(brand_id: str):
    products = await db.fetch("SELECT id, title, description, tags, price FROM products WHERE brand_id = $1", brand_id)
    await db.execute("DELETE FROM product_chunks WHERE brand_id = $1", brand_id)
    texts, refs = [], []
    for p in products:
        base = f"{p['title']}. {p['description']}"
        if p["tags"]:
            base += " Tags: " + ", ".join(p["tags"])
        for chunk in _chunk(base) or [p["title"]]:
            texts.append(chunk)
            refs.append(p["id"])
    if not texts:
        return
    vectors = await audio.embed(texts)
    for text, product_id, vec in zip(texts, refs, vectors):
        await db.execute(
            "INSERT INTO product_chunks (brand_id, product_id, chunk_text, embedding) VALUES ($1,$2,$3,$4::vector)",
            brand_id, product_id, text, "[" + ",".join(f"{v:.6f}" for v in vec) + "]",
        )


VOICE_SYSTEM = """You are a brand strategist. Draft a brand_voice.md for a D2C brand based on its product catalog.
This document guides every ad script generated for the brand, and it will be human-reviewed before use.
Structure it with these markdown sections: ## Tone, ## Vocabulary (words/phrases to use), ## Taboos (topics, words and framings to avoid — be thorough and specific; this is the most important brand-safety artifact), ## Audience, ## Positioning.
Infer sensitivities from the catalog (e.g. faith-branded merchandise demands reverence and strict taboo lists). Be concrete, not generic."""


async def draft_brand_voice(brand_id: str, store_url: str) -> str:
    products = await db.fetch(
        "SELECT title, description, tags, price FROM products WHERE brand_id = $1 LIMIT 60", brand_id
    )
    catalog = "\n".join(
        f"- {p['title']} ({p['price'] or 'n/a'}): {p['description'][:300]} [tags: {', '.join(p['tags'])}]"
        for p in products
    )
    content = await llm.complete_text(VOICE_SYSTEM, f"Store: {store_url}\n\nProduct catalog:\n{catalog}")
    version = (await db.fetchval("SELECT COALESCE(MAX(version), 0) FROM brand_voice WHERE brand_id = $1", brand_id)) + 1
    await db.execute(
        "INSERT INTO brand_voice (brand_id, version, content_md, status) VALUES ($1,$2,$3,'draft')",
        brand_id, version, content,
    )
    return content
