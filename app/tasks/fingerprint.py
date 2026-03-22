import asyncio
import os
from collections import Counter

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.tasks.progress import set_tracklist_progress

logger = get_task_logger(__name__)


def _extract_identity(result: dict | None) -> tuple[str | None, str | None]:
    if not isinstance(result, dict):
        return None, None
    track_data = result.get("track", {}) or {}
    title = track_data.get("title")
    artist = track_data.get("subtitle")
    if not title and not artist:
        return None, None
    return title, artist


def _aggregate_segment_matches(matches: list[dict]) -> dict:
    num_snippets = len(matches)
    recognized = []
    for item in matches:
        title, artist = _extract_identity(item.get("result"))
        if title or artist:
            recognized.append((title or "", artist or ""))

    if not recognized:
        return {
            "result": {} if num_snippets else None,
            "confidence_score": 0.0,
            "num_snippets": num_snippets,
            "num_consistent_snippets": 0,
            "raw_matches_json": matches,
        }

    counts = Counter(recognized)
    selected_identity, consistent_count = counts.most_common(1)[0]
    selected_result = next(
        (
            item.get("result")
            for item in matches
            if _extract_identity(item.get("result")) == selected_identity
        ),
        {},
    )
    if consistent_count == num_snippets:
        confidence = 0.95 if num_snippets > 1 else 0.9
    else:
        confidence = min(0.89, consistent_count / max(1, num_snippets))

    return {
        "result": selected_result,
        "confidence_score": round(float(confidence), 3),
        "num_snippets": num_snippets,
        "num_consistent_snippets": int(consistent_count),
        "raw_matches_json": matches,
    }


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
                candidates = [{"path": segment.get("path"), "offset": 0, "snippet_type": "legacy"}]
            timestamp = segment.get("timestamp", segment.get("start_time", 0.0))

            snippet_matches = []
            attempted_candidate = False
            for candidate in candidates:
                snippet_path = candidate.get("path", "")
                if not os.path.exists(snippet_path):
                    continue
                attempted_candidate = True
                try:
                    result = asyncio.run(_async_identify(snippet_path))
                    snippet_matches.append(
                        {
                            "snippet_type": candidate.get("snippet_type"),
                            "segment_index": candidate.get("segment_index"),
                            "snippet_start": candidate.get("snippet_start"),
                            "offset": candidate.get("offset", 0),
                            "result": result or {},
                        }
                    )
                except Exception as exc:
                    logger.error("Identification failed for %s: %s", snippet_path, exc)

            aggregate = _aggregate_segment_matches(snippet_matches)
            identified_result = aggregate["result"]

            if not attempted_candidate:
                logger.warning("No valid snippet candidates for transition at %.1fs", timestamp)
            elif identified_result == {}:
                logger.warning("No candidate recognized for transition at %.1fs", timestamp)
            else:
                logger.info("Aggregated segment at %.1fs with confidence %.2f", timestamp, aggregate["confidence_score"])
            identifications.append(
                {
                    "segment_index": segment.get("segment_index", idx - 1),
                    "timestamp": timestamp,
                    "result": identified_result,
                    "confidence_score": aggregate["confidence_score"],
                    "num_snippets": aggregate["num_snippets"],
                    "num_consistent_snippets": aggregate["num_consistent_snippets"],
                    "raw_matches_json": aggregate["raw_matches_json"],
                }
            )

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
