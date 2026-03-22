import asyncio
import os

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.tasks.progress import set_tracklist_progress

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
        total_segments = len(segments)
        set_tracklist_progress(
            tracklist_id,
            status="fingerprinting",
            total_segments=total_segments,
            processed_segments=0,
            progress_percent=70,
            progress_message=f"Identifying tracks 0/{total_segments}",
        )

        for idx, segment in enumerate(segments, start=1):
            candidates = segment.get("candidates", [])
            if not candidates and segment.get("path"):
                candidates = [{"path": segment.get("path"), "offset": 0}]
            timestamp = segment.get("timestamp", segment.get("start_time", 0.0))
            
            identified_result = None
            attempted_candidate = False
            for candidate in candidates:
                snippet_path = candidate.get("path", "")
                if not os.path.exists(snippet_path):
                    continue
                attempted_candidate = True
                try:
                    result = asyncio.run(_async_identify(snippet_path))
                    identified_result = result
                    # shazamio returns a structure where 'track' exists if identified
                    if result and "track" in result:
                        logger.info("Identified track at %.1fs using offset %+d: %s", timestamp, candidate.get("offset", 0), result)
                        break
                except Exception as exc:
                    logger.error("Identification failed for %s: %s", snippet_path, exc)
            
            if identified_result is None and attempted_candidate:
                identified_result = {}

            if not identified_result:
                logger.warning("No candidate recognized for transition at %.1fs", timestamp)
            identifications.append({"timestamp": timestamp, "result": identified_result})

            fingerprint_ratio = (idx / total_segments) if total_segments else 1.0
            set_tracklist_progress(
                tracklist_id,
                processed_segments=idx,
                progress_percent=70 + (fingerprint_ratio * 25),
                progress_message=f"Identifying tracks {idx}/{total_segments}",
            )

        return {"tracklist_id": tracklist_id, "identifications": identifications}

    except Exception as exc:
        logger.error("Fingerprint task failed for %s: %s", tracklist_id, exc)
        if self.request.retries >= self.max_retries:
            set_tracklist_progress(
                tracklist_id,
                status="failed",
                progress_percent=100,
                progress_message=f"Fingerprint failed: {exc}",
            )
        raise self.retry(exc=exc, countdown=20)

    finally:
        for segment in segments:
            path = segment.get("path", "")
            if path and os.path.exists(path):
                os.remove(path)
            for candidate in segment.get("candidates", []):
                path = candidate.get("path", "")
                if path and os.path.exists(path):
                    os.remove(path)


async def _async_identify(snippet_path: str) -> dict:
    from shazamio import Shazam

    shazam = Shazam()
    result = await shazam.recognize(snippet_path)
    return result
