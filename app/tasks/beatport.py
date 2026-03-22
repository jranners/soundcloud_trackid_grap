import uuid
from celery.utils.log import get_task_logger
import httpx

from app.celery_app import celery_app
from app.config import settings
from app.database import get_db
from app.models import Tracklist

logger = get_task_logger(__name__)

@celery_app.task(
    name="app.tasks.beatport.send_to_beatportdl",
    queue="analysis",
    bind=True,
)
def send_to_beatportdl(self, tracklist_id: str, mode: str = "zip") -> dict:
    try:
        uid = uuid.UUID(tracklist_id)
    except ValueError:
        return {"error": "Invalid tracklist_id"}
        
    with get_db() as db:
        tracklist = db.get(Tracklist, uid)
        if not tracklist:
            logger.error("Tracklist not found: %s", tracklist_id)
            return {"error": "Tracklist not found"}
        
        # Collect tracks that have a title and an artist
        tracks = [t for t in tracklist.tracks if t.title and t.artist]
        
    if not tracks:
        logger.warning("No valid tracks to send for %s", tracklist_id)
        return {"status": "success", "queued": 0, "total": 0}
        
    urls_to_download = []
    beatport_job_id = None
    
    with httpx.Client(timeout=15.0) as client:
        # Search for each track sequentially
        for track in tracks:
            query = f"{track.title} {track.artist}".strip()
            search_url = f"{settings.BEATPORTDL_API_URL.rstrip('/')}/api/search"
            try:
                resp = client.get(search_url, params={"q": query, "type": "tracks", "page": 1})
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    if data and len(data) > 0:
                        top_result = data[0]
                        beatport_url = top_result.get("url")
                        if beatport_url:
                            urls_to_download.append(beatport_url)
                            logger.info("Matched '%s' -> %s", query, beatport_url)
                    else:
                        logger.info("No matches on Beatport for: %s", query)
                else:
                    logger.error("BeatportDL Search API returned %d for '%s'", resp.status_code, query)
            except Exception as e:
                logger.error("Failed querying BeatportDL for '%s': %s", query, e)
                
        # Send downloads to the checkout
        if urls_to_download:
            checkout_url = f"{settings.BEATPORTDL_API_URL.rstrip('/')}/api/download/checkout"
            payload = {"urls": urls_to_download, "mode": mode}
            try:
                resp = client.post(checkout_url, json=payload)
                if resp.status_code == 200:
                    bp_data = resp.json()
                    beatport_job_id = bp_data.get("jobId")
                    logger.info("Successfully checked out %d tracks on BeatportDL (Job: %s).", len(urls_to_download), beatport_job_id)
                else:
                    logger.error("BeatportDL Checkout API failed with %d: %s", resp.status_code, resp.text)
            except Exception as e:
                logger.error("Failed issuing checkout to BeatportDL: %s", e)
                
    return {
        "status": "success",
        "queued": len(urls_to_download),
        "total": len(tracks),
        "beatport_job_id": beatport_job_id,
        "mode": mode
    }
