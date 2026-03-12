import glob
import os
import uuid
from datetime import datetime, timezone

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.config import settings
from app.database import get_db
from app.models import Track, Tracklist

logger = get_task_logger(__name__)


@celery_app.task(
    name="app.tasks.aggregate_results",
    queue="analysis",
    bind=True,
)
def aggregate_results(self, fingerprint_result: dict) -> dict:
    tracklist_id = fingerprint_result["tracklist_id"]
    identifications = fingerprint_result.get("identifications", [])
    saved_tracks = []

    try:
        with get_db() as db:
            tracklist = db.get(Tracklist, uuid.UUID(tracklist_id))
            if tracklist is None:
                logger.error("Tracklist %s not found in DB", tracklist_id)
                return {"tracklist_id": tracklist_id, "error": "not found", "tracks": []}

            for item in identifications:
                timestamp = item["timestamp"]
                raw = item.get("result") or {}

                title = None
                artist = None
                try:
                    track_data = raw.get("track", {})
                    title = track_data.get("title")
                    artist = track_data.get("subtitle")
                except Exception:
                    pass

                track = Track(
                    id=uuid.uuid4(),
                    tracklist_id=uuid.UUID(tracklist_id),
                    title=title,
                    artist=artist,
                    timestamp_start=timestamp,
                    raw_result=raw if raw else None,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(track)
                saved_tracks.append(
                    {"title": title, "artist": artist, "timestamp_start": timestamp}
                )

            tracklist.status = "completed"
            tracklist.updated_at = datetime.now(timezone.utc)
            db.commit()
            logger.info(
                "Saved %d tracks and marked tracklist %s as completed",
                len(saved_tracks),
                tracklist_id,
            )

        return {
            "tracklist_id": tracklist_id,
            "status": "completed",
            "tracks": saved_tracks,
        }

    except Exception as exc:
        logger.error("Aggregation failed for %s: %s", tracklist_id, exc)
        with get_db() as db:
            tracklist = db.get(Tracklist, uuid.UUID(tracklist_id))
            if tracklist:
                tracklist.status = "failed"
                tracklist.updated_at = datetime.now(timezone.utc)
                db.commit()
        raise

    finally:
        pattern = os.path.join(settings.RAMDISK_PATH, f"{tracklist_id}*")
        for f in glob.glob(pattern):
            try:
                os.remove(f)
            except OSError:
                pass
