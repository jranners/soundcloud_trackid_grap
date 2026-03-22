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
            # Backward compatibility: older analysis payloads used a flat
            # {"path": "...", "timestamp": ...} segment format.
            if not candidates and segment.get("path"):
                candidates = [{"path": segment.get("path"), "offset": 0}]
            timestamp = segment.get("timestamp", segment.get("start_time", 0.0))
            
            identified_result = None
            attempted_candidate = False
            had_unsuccessful_attempt = False
            for candidate in candidates:
                snippet_path = candidate.get("path", "")
                if not os.path.exists(snippet_path):
                    continue
                attempted_candidate = True
                try:
                    result = asyncio.run(_async_identify(snippet_path))
                    # shazamio returns a structure where 'track' exists if identified
                    if result and "track" in result:
                        identified_result = result
                        logger.info("Identified track at %.1fs using offset %+d: %s", timestamp, candidate.get("offset", 0), result)
                        break
                    had_unsuccessful_attempt = True
                except Exception as exc:
                    logger.error("Identification failed for %s: %s", snippet_path, exc)
            
            # Keep `{}` as explicit "attempted but no Shazam match" sentinel to preserve
            # existing aggregation/test expectations while distinguishing from "not attempted" (None).
            if identified_result is None and had_unsuccessful_attempt:
                identified_result = {}

            if identified_result is None:
                logger.warning("No valid snippet candidates for transition at %.1fs", timestamp)
            elif identified_result == {}:
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
            # Backward compatibility cleanup for legacy flat segment format.
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
