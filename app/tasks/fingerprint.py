import asyncio
import os

from celery.utils.log import get_task_logger

from app.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    name="app.tasks.fingerprint.identify_tracks",
    queue="fingerprint",
    bind=True,
    rate_limit="15/m",
    max_retries=3,
)
def identify_tracks(self, analysis_result: dict) -> dict:
    tracklist_id = analysis_result["tracklist_id"]
    segments = analysis_result.get("segments", [])
    identifications = []

    try:
        for segment in segments:
            snippet_path = segment["path"]
            timestamp = segment["timestamp"]

            if not os.path.exists(snippet_path):
                logger.warning("Snippet not found: %s", snippet_path)
                identifications.append({"timestamp": timestamp, "result": None})
                continue

            try:
                result = asyncio.run(_async_identify(snippet_path))
                identifications.append({"timestamp": timestamp, "result": result})
                logger.info("Identified track at %.1fs: %s", timestamp, result)
            except Exception as exc:
                logger.error("Identification failed for %s: %s", snippet_path, exc)
                identifications.append({"timestamp": timestamp, "result": None})

        return {"tracklist_id": tracklist_id, "identifications": identifications}

    except Exception as exc:
        logger.error("Fingerprint task failed for %s: %s", tracklist_id, exc)
        raise self.retry(exc=exc, countdown=20)

    finally:
        for segment in segments:
            path = segment.get("path", "")
            if path and os.path.exists(path):
                os.remove(path)


async def _async_identify(snippet_path: str) -> dict:
    from shazamio import Shazam

    shazam = Shazam()
    result = await shazam.recognize(snippet_path)
    return result
