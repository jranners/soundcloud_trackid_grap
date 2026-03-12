import glob
import os
import subprocess

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.config import settings

logger = get_task_logger(__name__)


@celery_app.task(
    name="app.tasks.download.download_audio",
    queue="download",
    bind=True,
    max_retries=3,
)
def download_audio(self, tracklist_id: str, url: str) -> dict:
    output_template = os.path.join(settings.RAMDISK_PATH, f"{tracklist_id}.%(ext)s")
    audio_path = None

    try:
        import yt_dlp

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "sleep_requests": 1.5,
            "extractor_args": {"soundcloud": {"formats": ["hls_aac"]}},
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the downloaded file
        pattern = os.path.join(settings.RAMDISK_PATH, f"{tracklist_id}.*")
        matches = glob.glob(pattern)
        if not matches:
            raise FileNotFoundError(f"No audio file found for tracklist {tracklist_id}")
        audio_path = matches[0]
        logger.info("Downloaded audio to %s", audio_path)
        return {"tracklist_id": tracklist_id, "audio_path": audio_path, "url": url}

    except Exception as exc:
        logger.error("Download failed for %s: %s", tracklist_id, exc)
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        raise self.retry(exc=exc, countdown=10)
