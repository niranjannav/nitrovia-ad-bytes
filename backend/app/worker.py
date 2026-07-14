"""Async job worker. Runs in-process with the API by default (RUN_WORKER=1),
or standalone via `python -m app.worker`. Every stage writes its outputs to
the database/storage as it goes, so a re-run skips or redoes cheaply."""

import asyncio
import logging
import traceback

from . import db, jobs
from .config import MissingKeyError, settings
from .services import exporter, ingest, media_pipeline, reference, stitch, storyboard

log = logging.getLogger("nitroclip.worker")


async def handle_ingest_brand(payload: dict):
    try:
        await ingest.ingest_brand(payload["brand_id"])
    except Exception:
        await db.execute("UPDATE brands SET status = 'failed' WHERE id = $1", payload["brand_id"])
        raise


async def handle_prepare_project(payload: dict):
    """Chain: process references -> extract format template -> generate script."""
    project_id = payload["project_id"]
    try:
        await db.execute("UPDATE projects SET status = 'extracting', error = NULL WHERE id = $1", project_id)
        for rid in payload["reference_ids"]:
            ref = await db.fetchrow("SELECT status FROM reference_videos WHERE id = $1", rid)
            if ref and ref["status"] != "analyzed":
                try:
                    await reference.process_reference(rid)
                except Exception as e:
                    await db.execute(
                        "UPDATE reference_videos SET status = 'failed', error = $2 WHERE id = $1", rid, str(e)[:1000]
                    )
                    raise
        analyzed = [
            rid for rid in payload["reference_ids"]
            if (await db.fetchval("SELECT status FROM reference_videos WHERE id = $1", rid)) == "analyzed"
        ]
        if not analyzed:
            raise RuntimeError("no reference videos could be analyzed")
        project = await db.fetchrow("SELECT title FROM projects WHERE id = $1", project_id)
        template_id = await reference.extract_template(analyzed, payload.get("template_name") or f"Template — {project['title']}")
        await db.execute("UPDATE projects SET format_template_id = $2 WHERE id = $1", project_id, template_id)
        await storyboard.generate_script(project_id)
    except Exception as e:
        await db.execute(
            "UPDATE projects SET status = 'failed', error = $2 WHERE id = $1", project_id, str(e)[:1000]
        )
        raise


async def handle_generate_script(payload: dict):
    try:
        await storyboard.generate_script(payload["project_id"])
    except Exception as e:
        await db.execute(
            "UPDATE projects SET status = 'failed', error = $2 WHERE id = $1", payload["project_id"], str(e)[:1000]
        )
        raise


async def handle_render_segment(payload: dict):
    segment_id = payload["segment_id"]
    try:
        project_id = await media_pipeline.render_segment(
            segment_id,
            do_image=payload.get("image", True),
            do_video=payload.get("video", True),
            do_tts=payload.get("tts", True),
        )
    except Exception as e:
        await db.execute("UPDATE segments SET status = 'failed', error = $2 WHERE id = $1", segment_id, str(e)[:1000])
        seg = await db.fetchrow("SELECT project_id FROM segments WHERE id = $1", segment_id)
        if seg:
            await db.execute("UPDATE projects SET status = 'failed', error = $2 WHERE id = $1", seg["project_id"], str(e)[:1000])
        raise
    if await media_pipeline.all_segments_ready(str(project_id)):
        await jobs.enqueue_once("stitch_project", {"project_id": str(project_id)}, str(project_id))


async def handle_stitch_project(payload: dict):
    try:
        await stitch.stitch_project(payload["project_id"])
    except Exception as e:
        await db.execute(
            "UPDATE projects SET status = 'failed', error = $2 WHERE id = $1", payload["project_id"], str(e)[:1000]
        )
        raise


async def handle_export_project(payload: dict):
    await exporter.export_project(payload["project_id"])


HANDLERS = {
    "ingest_brand": handle_ingest_brand,
    "prepare_project": handle_prepare_project,
    "generate_script": handle_generate_script,
    "render_segment": handle_render_segment,
    "stitch_project": handle_stitch_project,
    "export_project": handle_export_project,
}


async def run_one(job: dict) -> None:
    handler = HANDLERS.get(job["type"])
    if handler is None:
        await jobs.finish(job["id"], f"unknown job type {job['type']}")
        return
    try:
        await handler(job["payload"])
        await jobs.finish(job["id"])
        log.info("job %s (%s) done", job["id"], job["type"])
    except MissingKeyError as e:
        await jobs.finish(job["id"], str(e))
        log.warning("job %s (%s) blocked: %s", job["id"], job["type"], e)
    except Exception as e:
        await jobs.finish(job["id"], str(e))
        log.error("job %s (%s) failed: %s\n%s", job["id"], job["type"], e, traceback.format_exc())


async def loop(stop_event: asyncio.Event | None = None):
    log.info("worker loop started")
    while stop_event is None or not stop_event.is_set():
        try:
            job = await jobs.claim_next()
        except MissingKeyError:
            await asyncio.sleep(5)  # DATABASE_URL not set yet
            continue
        except Exception as e:
            log.error("worker poll error: %s", e)
            await asyncio.sleep(5)
            continue
        if job is None:
            await asyncio.sleep(2)
            continue
        await run_one(job)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(loop())


if __name__ == "__main__":
    main()
