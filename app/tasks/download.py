import glob
import os

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.config import settings
from app.tasks.progress import set_tracklist_metadata, set_tracklist_progress

logger = get_task_logger(__name__)


def fetch_soundcloud_metadata(url: str) -> dict:
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    set_title = (info.get("title") if isinstance(info, dict) else None) or None
    cover_url = (
        (info.get("thumbnail") if isinstance(info, dict) else None)
        or (
            info.get("thumbnails", [{}])[-1].get("url")
            if isinstance(info, dict) and info.get("thumbnails")
            else None
        )
    )
    return {"set_title": set_title, "cover_url": cover_url}


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
        set_tracklist_progress(
            tracklist_id,
            status="downloading",
            progress_percent=10,
            progress_message="Preparing download",
        )
        import yt_dlp

        info = {}

        ydl_opts = {
            # Prefer high-bitrate non-HLS streams first (usually faster than fragmented HLS).
            "format": "bestaudio[abr>=320][protocol^=http]/bestaudio[protocol^=http]/bestaudio/best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [
                lambda d: _download_progress_hook(tracklist_id, d),
            ],
            "concurrent_fragment_downloads": 10,
            "retries": 10,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}

        # Find the downloaded file
        pattern = os.path.join(settings.RAMDISK_PATH, f"{tracklist_id}.*")
        matches = glob.glob(pattern)
        if not matches:
            raise FileNotFoundError(f"No audio file found for tracklist {tracklist_id}")
        audio_path = matches[0]
        set_tracklist_progress(
            tracklist_id,
            progress_percent=25,
            progress_message="Audio downloaded",
        )
        set_title = (info.get("title") if isinstance(info, dict) else None) or None
        cover_url = (
            (info.get("thumbnail") if isinstance(info, dict) else None)
            or (
                info.get("thumbnails", [{}])[-1].get("url")
                if isinstance(info, dict) and info.get("thumbnails")
                else None
            )
        )
        set_tracklist_metadata(tracklist_id, set_title=set_title, cover_url=cover_url)
        logger.info("Downloaded audio to %s", audio_path)
        return {
            "tracklist_id": tracklist_id,
            "audio_path": audio_path,
            "url": url,
            "set_title": set_title,
            "cover_url": cover_url,
        }

    except Exception as exc:
        logger.error("Download failed for %s: %s", tracklist_id, exc)
        if self.request.retries >= self.max_retries:
            set_tracklist_progress(
                tracklist_id,
                status="failed",
                progress_percent=100,
                progress_message=f"Download failed: {exc}",
            )
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        raise self.retry(exc=exc, countdown=10)


def _download_progress_hook(tracklist_id: str, data: dict) -> None:
    status = data.get("status")
    if status == "downloading":
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        downloaded = data.get("downloaded_bytes") or 0
        if total:
            ratio = max(0.0, min(1.0, downloaded / total))
            progress = 10 + (ratio * 10)
            set_tracklist_progress(
                tracklist_id,
                progress_percent=progress,
                progress_message=f"Downloading audio ({int(ratio * 100)}%)",
            )
    elif status == "finished":
        set_tracklist_progress(
            tracklist_id,
            progress_percent=22,
            progress_message="Download finished, processing file",
        )
