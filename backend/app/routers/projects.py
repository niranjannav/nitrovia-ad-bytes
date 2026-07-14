from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, jobs, storage

router = APIRouter(prefix="/api", tags=["projects"])


class ProjectCreate(BaseModel):
    brand_id: str
    title: str
    brief: str = ""
    format_template_id: str | None = None
    reference_urls: list[str] = []
    uploaded_reference_ids: list[str] = []


class SegmentUpdate(BaseModel):
    vo_text: str | None = None
    caption: str | None = None
    visual_direction: str | None = None
    t_start: float | None = None
    t_end: float | None = None
    product_id: str | None = None


class RegenerateBody(BaseModel):
    # cheapest -> most expensive, per PRD F6
    level: str  # "video" (new video, same image) | "image_video" | "full" (new direction -> image -> video -> vo)
    visual_direction: str | None = None
    vo_text: str | None = None
    caption: str | None = None


class SelectRenderBody(BaseModel):
    render_id: str


async def _project_or_404(project_id: str) -> dict:
    project = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise HTTPException(404, "project not found")
    return project


async def _segment_or_404(segment_id: str) -> dict:
    segment = await db.fetchrow("SELECT * FROM segments WHERE id = $1", segment_id)
    if not segment:
        raise HTTPException(404, "segment not found")
    return segment


@router.get("/projects")
async def list_projects():
    return await db.fetch(
        """SELECT pr.*, b.name AS brand_name FROM projects pr
           JOIN brands b ON b.id = pr.brand_id ORDER BY pr.created_at DESC"""
    )


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate):
    urls = [u.strip() for u in body.reference_urls if u.strip()]
    if not body.format_template_id and not urls and not body.uploaded_reference_ids:
        raise HTTPException(422, "provide reference video URLs (or uploads), or pick an existing format template")

    project = await db.fetchrow(
        "INSERT INTO projects (brand_id, title, brief, format_template_id) VALUES ($1,$2,$3,$4) RETURNING *",
        body.brand_id, body.title.strip(), body.brief.strip(), body.format_template_id,
    )
    pid = str(project["id"])

    if body.format_template_id and not urls and not body.uploaded_reference_ids:
        await jobs.enqueue("generate_script", {"project_id": pid}, project_id=pid)
    else:
        reference_ids = list(body.uploaded_reference_ids)
        for url in urls:
            ref = await db.fetchrow(
                "INSERT INTO reference_videos (brand_id, url, source) VALUES ($1,$2,'url') RETURNING id",
                body.brand_id, url,
            )
            reference_ids.append(str(ref["id"]))
        await jobs.enqueue(
            "prepare_project",
            {"project_id": pid, "reference_ids": reference_ids, "template_name": f"Template — {body.title.strip()}"},
            project_id=pid,
        )
    return project


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = await _project_or_404(project_id)
    project["final_video_url"] = storage.public_url(project["final_video_path"])
    segments = await db.fetch(
        "SELECT * FROM segments WHERE project_id = $1 AND version = $2 ORDER BY idx",
        project_id, project["script_version"],
    )
    for segment in segments:
        renders = await db.fetch(
            "SELECT * FROM renders WHERE segment_id = $1 ORDER BY type, version DESC", segment["id"]
        )
        segment["renders"] = [{**r, "url": storage.public_url(r["storage_path"])} for r in renders]
        if segment["product_id"]:
            segment["product"] = await db.fetchrow(
                "SELECT id, title FROM products WHERE id = $1", segment["product_id"]
            )
    project["segments"] = segments
    project["total_cost"] = sum(float(s["cost_accum"]) for s in segments)
    export = await db.fetchrow(
        "SELECT * FROM exports WHERE project_id = $1 ORDER BY created_at DESC LIMIT 1", project_id
    )
    if export:
        export["video_url"] = storage.public_url(export["storage_path"])
    project["export"] = export
    return project


@router.post("/projects/{project_id}/regenerate_script")
async def regenerate_script(project_id: str):
    await _project_or_404(project_id)
    return await jobs.enqueue("generate_script", {"project_id": project_id}, project_id=project_id)


@router.put("/segments/{segment_id}")
async def update_segment(segment_id: str, body: SegmentUpdate):
    segment = await _segment_or_404(segment_id)
    if segment["status"] not in ("draft", "failed"):
        # Approved scripts are immutable (audit trail): edits create a new draft state for that segment.
        await db.execute("UPDATE segments SET status = 'draft' WHERE id = $1", segment_id)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    for field, value in updates.items():
        await db.execute(f"UPDATE segments SET {field} = $2 WHERE id = $1", segment_id, value)  # noqa: S608 — fields come from the pydantic model
    return await db.fetchrow("SELECT * FROM segments WHERE id = $1", segment_id)


@router.post("/segments/{segment_id}/approve")
async def approve_segment(segment_id: str):
    segment = await _segment_or_404(segment_id)
    if segment["status"] != "draft":
        return segment
    await db.execute("UPDATE segments SET status = 'approved' WHERE id = $1", segment_id)
    return await db.fetchrow("SELECT * FROM segments WHERE id = $1", segment_id)


@router.post("/projects/{project_id}/approve")
async def approve_project(project_id: str):
    project = await _project_or_404(project_id)
    await db.execute(
        "UPDATE segments SET status = 'approved' WHERE project_id = $1 AND version = $2 AND status = 'draft'",
        project_id, project["script_version"],
    )
    await db.execute("UPDATE projects SET status = 'approved' WHERE id = $1", project_id)
    return {"ok": True}


@router.post("/projects/{project_id}/generate")
async def generate_media(project_id: str):
    """Kick off image+video+VO generation for every approved segment.
    Server-side enforcement of the approval gate: draft segments are refused."""
    project = await _project_or_404(project_id)
    segments = await db.fetch(
        "SELECT * FROM segments WHERE project_id = $1 AND version = $2 ORDER BY idx",
        project_id, project["script_version"],
    )
    if not segments:
        raise HTTPException(422, "no script yet")
    drafts = [s for s in segments if s["status"] == "draft"]
    if drafts:
        raise HTTPException(422, f"{len(drafts)} segment(s) not approved yet — approve the script first")
    queued = 0
    for segment in segments:
        if segment["status"] in ("approved", "failed"):
            await jobs.enqueue("render_segment", {"segment_id": str(segment["id"])}, project_id=project_id)
            queued += 1
    await db.execute("UPDATE projects SET status = 'generating', error = NULL WHERE id = $1", project_id)
    return {"queued_segments": queued}


@router.post("/segments/{segment_id}/regenerate")
async def regenerate_segment(segment_id: str, body: RegenerateBody):
    segment = await _segment_or_404(segment_id)
    if segment["status"] == "draft":
        raise HTTPException(422, "segment is not approved yet")
    if body.level not in ("video", "image_video", "full"):
        raise HTTPException(422, "level must be video | image_video | full")

    payload = {"segment_id": segment_id, "image": False, "video": True, "tts": False}
    if body.level in ("image_video", "full"):
        payload["image"] = True
    if body.level == "full":
        for field in ("visual_direction", "vo_text", "caption"):
            value = getattr(body, field)
            if value is not None:
                await db.execute(f"UPDATE segments SET {field} = $2 WHERE id = $1", segment_id, value)  # noqa: S608
        payload["tts"] = True

    await db.execute("UPDATE segments SET status = 'approved', error = NULL WHERE id = $1", segment_id)
    await db.execute("UPDATE projects SET status = 'generating' WHERE id = $1", segment["project_id"])
    return await jobs.enqueue("render_segment", payload, project_id=str(segment["project_id"]))


@router.post("/segments/{segment_id}/select_render")
async def select_render(segment_id: str, body: SelectRenderBody):
    """Pick a take among versioned renders; restitch to apply."""
    await _segment_or_404(segment_id)
    render = await db.fetchrow("SELECT * FROM renders WHERE id = $1 AND segment_id = $2", body.render_id, segment_id)
    if not render:
        raise HTTPException(404, "render not found for this segment")
    column = {"image": "selected_image_render_id", "video": "selected_video_render_id", "audio": "selected_audio_render_id"}[render["type"]]
    await db.execute(f"UPDATE segments SET {column} = $2 WHERE id = $1", segment_id, render["id"])  # noqa: S608
    return {"ok": True}


@router.post("/projects/{project_id}/stitch")
async def stitch(project_id: str):
    await _project_or_404(project_id)
    job = await jobs.enqueue_once("stitch_project", {"project_id": project_id}, project_id)
    return job or {"ok": True, "note": "stitch already in progress"}


@router.post("/projects/{project_id}/export")
async def export(project_id: str):
    project = await _project_or_404(project_id)
    if not project["final_video_path"]:
        raise HTTPException(422, "no finished video yet — generate and stitch first")
    return await jobs.enqueue("export_project", {"project_id": project_id}, project_id=project_id)


@router.get("/projects/{project_id}/jobs")
async def project_jobs(project_id: str):
    return await db.fetch(
        "SELECT id, type, status, error, created_at, updated_at FROM jobs WHERE project_id = $1 ORDER BY created_at DESC LIMIT 30",
        project_id,
    )


@router.get("/jobs")
async def recent_jobs():
    return await db.fetch(
        "SELECT id, type, status, error, brand_id, project_id, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT 50"
    )
