import uuid

from celery.utils.log import get_task_logger

from app.database import get_db
from app.models import Tracklist

logger = get_task_logger(__name__)


def set_tracklist_progress(
    tracklist_id: str,
    *,
    status: str | None = None,
    progress_percent: float | None = None,
    progress_message: str | None = None,
    total_segments: float | None = None,
    processed_segments: float | None = None,
) -> None:
    try:
        with get_db() as db:
            tracklist = db.get(Tracklist, uuid.UUID(tracklist_id))
            if tracklist is None:
                logger.warning("Tracklist %s not found while updating progress", tracklist_id)
                return
            if status is not None:
                tracklist.status = status
            if progress_percent is not None:
                tracklist.progress_percent = float(progress_percent)
            if progress_message is not None:
                tracklist.progress_message = progress_message
            if total_segments is not None:
                tracklist.total_segments = float(total_segments)
            if processed_segments is not None:
                tracklist.processed_segments = float(processed_segments)
            db.commit()
    except Exception as exc:
        logger.error("Failed to update progress for %s: %s", tracklist_id, exc)


def set_tracklist_metadata(tracklist_id: str, *, set_title: str | None = None, cover_url: str | None = None) -> None:
    try:
        with get_db() as db:
            tracklist = db.get(Tracklist, uuid.UUID(tracklist_id))
            if tracklist is None:
                logger.warning("Tracklist %s not found while updating metadata", tracklist_id)
                return
            if set_title:
                tracklist.set_title = set_title
            if cover_url:
                tracklist.cover_url = cover_url
            db.commit()
    except Exception as exc:
        logger.error("Failed to update metadata for %s: %s", tracklist_id, exc)


def set_tracklist_status(tracklist_id: str, status: str) -> None:
    set_tracklist_progress(tracklist_id, status=status)
