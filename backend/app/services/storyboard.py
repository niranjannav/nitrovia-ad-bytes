"""F3 — Storyboard: timestamped script generation.

Combines the format template + brand voice + retrieved product context into an
ordered list of segments. This is the approval gate: nothing costing real
money runs before a human approves these segments."""

from .. import db
from ..config import MissingKeyError
from ..providers import audio, llm

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "t_start": {"type": "number"},
                    "t_end": {"type": "number"},
                    "vo_text": {"type": "string", "description": "voiceover, spoken naturally in the brand voice"},
                    "caption": {"type": "string", "description": "short on-screen caption"},
                    "visual_direction": {"type": "string", "description": "what the viewer sees — concrete enough to prompt an image model"},
                    "product_title": {"type": "string", "description": "exact catalog title of the featured product, or empty for pure B-roll"},
                },
                "required": ["t_start", "t_end", "vo_text", "caption", "visual_direction", "product_title"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}

SCRIPT_SYSTEM = """You write timestamped short-form video ad scripts (9:16, 15-40s) for D2C brands.
You are given a FORMAT TEMPLATE extracted from trending reference videos, the BRAND VOICE document, and RELEVANT PRODUCTS from the catalog.
Adapt the template's beat structure to this brand: keep the hook mechanics, pacing and CTA placement, swap in the brand's products and voice.
Rules:
- 4-7 segments, each 3-8 seconds, contiguous timestamps starting at 0.
- vo_text must respect the brand voice, especially its Taboos section. Never violate a taboo.
- visual_direction must be concrete and filmable by an image+video model (subject, setting, camera, mood). When a segment shows a product, describe the person/garment/environment — the actual printed design gets composited on afterwards, so describe the garment as plain.
- product_title must exactly match one of the provided catalog titles (or be empty for B-roll segments).
- The final segment carries the CTA."""


async def retrieve_products(brand_id: str, query: str, limit: int = 8) -> list[dict]:
    """pgvector retrieval over product chunks; falls back to recency when
    embeddings aren't available."""
    try:
        vectors = await audio.embed([query])
        vec = "[" + ",".join(f"{v:.6f}" for v in vectors[0]) + "]"
        rows = await db.fetch(
            """SELECT DISTINCT ON (p.id) p.id, p.title, p.description, p.price
               FROM product_chunks c JOIN products p ON p.id = c.product_id
               WHERE c.brand_id = $1 AND c.embedding IS NOT NULL
               ORDER BY p.id, c.embedding <=> $2::vector
               LIMIT $3""",
            brand_id, vec, limit,
        )
        if rows:
            return rows
    except MissingKeyError:
        pass
    return await db.fetch(
        "SELECT id, title, description, price FROM products WHERE brand_id = $1 ORDER BY created_at DESC LIMIT $2",
        brand_id, limit,
    )


async def generate_script(project_id: str):
    project = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise ValueError(f"project {project_id} not found")
    if not project["format_template_id"]:
        raise RuntimeError("project has no format template yet")
    await db.execute("UPDATE projects SET status = 'scripting', error = NULL WHERE id = $1", project_id)

    template = await db.fetchrow("SELECT * FROM format_templates WHERE id = $1", project["format_template_id"])
    voice = await db.fetchrow(
        "SELECT content_md FROM brand_voice WHERE brand_id = $1 ORDER BY version DESC LIMIT 1", project["brand_id"]
    )
    products = await retrieve_products(project["brand_id"], f"{project['title']}. {project['brief']}")
    catalog = "\n".join(f"- {p['title']} ({p['price'] or 'n/a'}): {(p['description'] or '')[:250]}" for p in products)
    by_title = {p["title"]: p["id"] for p in products}

    import json

    user = (
        f"CLIP BRIEF: {project['title']}. {project['brief']}\n\n"
        f"FORMAT TEMPLATE:\n{json.dumps(template['template'], indent=2)}\n\n"
        f"BRAND VOICE:\n{voice['content_md'] if voice else '(no brand voice document yet — keep it neutral and safe)'}\n\n"
        f"RELEVANT PRODUCTS:\n{catalog}"
    )
    result = await llm.complete_json(SCRIPT_SYSTEM, user, SCRIPT_SCHEMA)

    version = project["script_version"] + 1
    for i, seg in enumerate(result["segments"]):
        await db.execute(
            """INSERT INTO segments (project_id, brand_id, version, idx, t_start, t_end, vo_text, caption,
                                     visual_direction, product_id, status)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'draft')""",
            project_id, project["brand_id"], version, i, seg["t_start"], seg["t_end"],
            seg["vo_text"], seg["caption"], seg["visual_direction"], by_title.get(seg["product_title"]),
        )
    await db.execute(
        "UPDATE projects SET status = 'script_ready', script_version = $2 WHERE id = $1", project_id, version
    )


CAPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string", "description": "post caption, 1-3 short lines, brand voice"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["caption", "hashtags"],
    "additionalProperties": False,
}


async def generate_caption(project_id: str) -> dict:
    project = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    voice = await db.fetchrow(
        "SELECT content_md FROM brand_voice WHERE brand_id = $1 ORDER BY version DESC LIMIT 1", project["brand_id"]
    )
    segments = await db.fetch(
        "SELECT vo_text FROM segments WHERE project_id = $1 AND version = $2 ORDER BY idx",
        project_id, project["script_version"],
    )
    script = " ".join(s["vo_text"] for s in segments)
    return await llm.complete_json(
        "You write social captions + hashtags for short-form D2C video posts. Respect the brand voice and its taboos. 8-14 hashtags, no banned/spammy tags.",
        f"BRAND VOICE:\n{voice['content_md'] if voice else '(none)'}\n\nVIDEO SCRIPT:\n{script}\n\nBRIEF: {project['title']}. {project['brief']}",
        CAPTION_SCHEMA,
    )
