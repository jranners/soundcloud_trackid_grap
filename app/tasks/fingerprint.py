import asyncio
import json
import os
from dataclasses import dataclass

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.config import settings
from app.tasks.progress import set_tracklist_progress

logger = get_task_logger(__name__)
logger_shazam = get_task_logger(f"{__name__}.shazam")

PRE_REQUEST_DELAY_SECONDS = 1.0
MIN_SEGMENT_DURATION_FOR_FALLBACK = 90.0
UNCERTAIN_SCORE_THRESHOLD = 0.2
DISAGREEMENT_CONFIDENCE = 0.6


@dataclass
class ShazamResult:
    result: dict
    no_match: bool
    throttled_retries: int = 0


@dataclass
class SegmentIdentifyAttempt:
    candidate: dict
    result: ShazamResult | None = None
    error: Exception | None = None


def _extract_identity(result: dict | None) -> tuple[str | None, str | None]:
    if not isinstance(result, dict):
        return None, None
    track_data = result.get("track", {}) or {}
    title = track_data.get("title")
    artist = track_data.get("subtitle")
    if not title and not artist:
        return None, None
    return title, artist


def _extract_shazam_score(result: dict | None) -> float:
    if not isinstance(result, dict):
        return 0.0
    track_data = result.get("track", {}) or {}
    for key in ("score", "match_score", "confidence"):
        value = track_data.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _meta_quality(result: dict | None) -> int:
    title, artist = _extract_identity(result)
    quality = 0
    if title:
        quality += 1
    if artist:
        quality += 1
    return quality


def _is_throttling_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 429:
        return True
    return any(token in msg for token in ("429", "rate limit", "too many requests", "throttl"))


def _is_json_error(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True
    return "json" in str(exc).lower() and "decode" in str(exc).lower()


async def call_with_backoff(fn, max_retries: int = 5, base_delay: float = 2.0):
    attempt = 0
    while True:
        try:
            return await fn(), attempt
        except Exception as exc:
            if not _is_throttling_error(exc):
                raise
            if attempt >= max_retries:
                logger_shazam.warning(
                    "Shazam throttling persisted after %d retries; giving up", attempt
                )
                raise
            delay = base_delay * (2 ** attempt)
            logger_shazam.warning(
                "Shazam 429/throttle detected (attempt %d/%d). Backing off %.1fs",
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1


async def identify_snippet(snippet_path: str) -> ShazamResult:
    from shazamio import Shazam

    shazam = Shazam()
    await asyncio.sleep(PRE_REQUEST_DELAY_SECONDS)

    async def _recognize():
        return await shazam.recognize(snippet_path)

    try:
        result, retries = await call_with_backoff(_recognize, max_retries=5, base_delay=2.0)
    except Exception as exc:
        if _is_json_error(exc):
            logger_shazam.warning(
                "JSON decode issue for snippet %s; treating as no match: %s",
                snippet_path,
                exc,
            )
            return ShazamResult(result={}, no_match=True)
        raise

    title, artist = _extract_identity(result)
    matched = bool(title or artist)
    return ShazamResult(result=result or {}, no_match=not matched, throttled_retries=retries)


def run_identify_snippets_for_segment(
    segment: dict,
    candidate_a: dict | None,
    candidate_b: dict | None,
    calls_used: int,
    max_calls: int,
    segment_index_fallback: int | None = None,
) -> tuple[list[SegmentIdentifyAttempt], int]:
    async def _run(initial_calls_used: int) -> tuple[list[SegmentIdentifyAttempt], int]:
        attempts: list[SegmentIdentifyAttempt] = []
        selected_result = {}
        current_calls_used = initial_calls_used

        if candidate_a and current_calls_used < max_calls:
            current_calls_used += 1
            try:
                res_a = await identify_snippet(candidate_a["path"])
                attempts.append(SegmentIdentifyAttempt(candidate=candidate_a, result=res_a))
                selected_result = res_a.result
            except Exception as exc:
                attempts.append(SegmentIdentifyAttempt(candidate=candidate_a, error=exc))
        elif candidate_a:
            logger.warning(
                "Shazam call budget exhausted before segment %s snippet A",
                segment.get("segment_index", segment_index_fallback),
            )

        needs_fallback = (
            candidate_b is not None
            and _is_uncertain_result(selected_result)
            and _should_try_fallback(segment, current_calls_used, max_calls)
        )
        if needs_fallback:
            current_calls_used += 1
            try:
                res_b = await identify_snippet(candidate_b["path"])
                attempts.append(SegmentIdentifyAttempt(candidate=candidate_b, result=res_b))
            except Exception as exc:
                attempts.append(SegmentIdentifyAttempt(candidate=candidate_b, error=exc))

        return attempts, current_calls_used

    if candidate_a is None and candidate_b is None:
        return [], calls_used
    return asyncio.run(_run(calls_used))


def _should_try_fallback(segment: dict, calls_used: int, max_calls: int) -> bool:
    if calls_used >= max_calls:
        return False
    duration = float(segment.get("duration", 0.0) or 0.0)
    return duration >= MIN_SEGMENT_DURATION_FOR_FALLBACK


def _select_best_candidate(candidate_a: dict, candidate_b: dict) -> tuple[dict, float]:
    score_a = _extract_shazam_score(candidate_a)
    score_b = _extract_shazam_score(candidate_b)
    if score_a > score_b:
        return candidate_a, DISAGREEMENT_CONFIDENCE
    if score_b > score_a:
        return candidate_b, DISAGREEMENT_CONFIDENCE

    meta_a = _meta_quality(candidate_a)
    meta_b = _meta_quality(candidate_b)
    if meta_a >= meta_b:
        return candidate_a, DISAGREEMENT_CONFIDENCE
    return candidate_b, DISAGREEMENT_CONFIDENCE


def _is_uncertain_result(result: dict | None) -> bool:
    if result in (None, {}):
        return True
    score = _extract_shazam_score(result)
    if score <= 0.0:
        return True
    if score < UNCERTAIN_SCORE_THRESHOLD:
        return True
    return _meta_quality(result) < 2


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
    max_calls = int(settings.MAX_SHAZAM_CALLS_PER_ANALYSIS)
    calls_used = 0

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

            valid_candidates = [c for c in candidates if os.path.exists(c.get("path", ""))]
            candidate_a = next((c for c in valid_candidates if c.get("snippet_type") == "A"), None)
            candidate_b = next((c for c in valid_candidates if c.get("snippet_type") == "B"), None)
            if candidate_a is None and valid_candidates:
                candidate_a = valid_candidates[0]
            if candidate_b is None and len(valid_candidates) > 1:
                candidate_b = valid_candidates[1]

            snippet_matches = []
            selected_result = {}
            confidence = 0.0
            consistent = 0
            attempts, calls_used = run_identify_snippets_for_segment(
                segment=segment,
                candidate_a=candidate_a,
                candidate_b=candidate_b,
                calls_used=calls_used,
                max_calls=max_calls,
                segment_index_fallback=idx - 1,
            )
            snippets_attempted = len(attempts)

            if attempts:
                first_attempt = attempts[0]
                first_candidate = first_attempt.candidate
                if first_attempt.error is not None:
                    logger.error(
                        "Identification failed for %s: %s",
                        first_candidate["path"],
                        first_attempt.error,
                    )
                elif first_attempt.result is not None:
                    first_result_obj = first_attempt.result
                    snippet_matches.append(
                        {
                            "snippet_type": first_candidate.get("snippet_type"),
                            "segment_index": first_candidate.get("segment_index"),
                            "snippet_start": first_candidate.get("snippet_start"),
                            "offset": first_candidate.get("offset", 0),
                            "result": first_result_obj.result,
                        }
                    )
                    selected_result = first_result_obj.result
                    confidence = 0.9 if not first_result_obj.no_match else 0.0
                    consistent = 1 if not first_result_obj.no_match else 0

            for attempt in attempts[1:]:
                candidate = attempt.candidate
                if attempt.error is not None:
                    logger.error("Identification failed for %s: %s", candidate["path"], attempt.error)
                    continue

                result_obj = attempt.result
                if result_obj is None:
                    continue

                snippet_matches.append(
                    {
                        "snippet_type": candidate.get("snippet_type"),
                        "segment_index": candidate.get("segment_index"),
                        "snippet_start": candidate.get("snippet_start"),
                        "offset": candidate.get("offset", 0),
                        "result": result_obj.result,
                    }
                )

                if selected_result in ({}, None) and not result_obj.no_match:
                    selected_result = result_obj.result
                    confidence = 0.9
                    consistent = 1
                elif selected_result not in ({}, None) and not result_obj.no_match:
                    title_a, artist_a = _extract_identity(selected_result)
                    title_b, artist_b = _extract_identity(result_obj.result)
                    if (title_a, artist_a) == (title_b, artist_b):
                        confidence = 0.95
                        consistent = 2
                    else:
                        selected_result, confidence = _select_best_candidate(
                            selected_result, result_obj.result
                        )
                        consistent = 1
                elif selected_result not in ({}, None):
                    confidence = min(confidence, 0.6)
                    consistent = 1

            if snippets_attempted == 0:
                result_out = None
                logger.warning("No valid snippet candidates for transition at %.1fs", timestamp)
            else:
                result_out = selected_result or {}
                if result_out == {}:
                    logger.warning("No candidate recognized for transition at %.1fs", timestamp)
                else:
                    logger.info("Aggregated segment at %.1fs with confidence %.2f", timestamp, confidence)

            identifications.append(
                {
                    "segment_index": segment.get("segment_index", idx - 1),
                    "timestamp": timestamp,
                    "result": result_out,
                    "confidence_score": round(float(confidence), 3),
                    "num_snippets": snippets_attempted,
                    "num_consistent_snippets": int(consistent),
                    "raw_matches_json": snippet_matches,
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
