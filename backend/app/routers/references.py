import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import db, storage

router = APIRouter(prefix="/api", tags=["references"])


@router.get("/templates")
async def list_templates():
    return await db.fetch("SELECT * FROM format_templates ORDER BY created_at DESC")


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    template = await db.fetchrow("SELECT * FROM format_templates WHERE id = $1", template_id)
    if not template:
        raise HTTPException(404, "template not found")
    return template


@router.post("/references/upload", status_code=201)
async def upload_reference(file: UploadFile = File(...)):
    """Manual fallback for when yt-dlp can't download a platform: the user
    screen-records the reference and uploads the file."""
    ref_id = str(uuid.uuid4())
    path = f"references/{ref_id}/upload.mp4"
    await storage.upload(path, await file.read(), file.content_type or "video/mp4")
    return await db.fetchrow(
        "INSERT INTO reference_videos (id, source, storage_path, url) VALUES ($1, 'upload', $2, $3) RETURNING *",
        ref_id, path, file.filename,
    )
