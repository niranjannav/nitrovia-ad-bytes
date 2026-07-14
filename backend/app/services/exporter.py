"""F7 — Export: MP4 + LLM-generated caption + hashtags. Post-ready package;
the user posts manually (v1 deliberately avoids platform APIs)."""

from .. import db
from . import storyboard


async def export_project(project_id: str) -> dict:
    project = await db.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project or not project["final_video_path"]:
        raise RuntimeError("project has no finished video yet — stitch it first")
    result = await storyboard.generate_caption(project_id)
    row = await db.fetchrow(
        "INSERT INTO exports (project_id, storage_path, caption, hashtags) VALUES ($1,$2,$3,$4) RETURNING *",
        project_id, project["final_video_path"], result["caption"], result["hashtags"],
    )
    return row
