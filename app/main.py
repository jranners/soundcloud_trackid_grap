import uuid
from pathlib import Path

from celery import chain
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.database import get_db
from app.models import Tracklist
from app.tasks.download import fetch_soundcloud_metadata
from app.config import settings

_BASE = Path(__file__).parent

app = FastAPI(title="SoundCloud TrackID Grabber")
app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")
_templates = Jinja2Templates(directory=_BASE / "templates")


class AnalyzeRequest(BaseModel):
    url: str


STATUS_PROGRESS = {
    "pending": {"stage": "queued", "progress": 5, "title": "Queued"},
    "downloading": {"stage": "downloading", "progress": 20, "title": "Downloading audio"},
    "segmenting": {"stage": "segmenting", "progress": 50, "title": "Detecting transitions"},
    "fingerprinting": {"stage": "fingerprinting", "progress": 80, "title": "Identifying tracks"},
    "completed": {"stage": "completed", "progress": 100, "title": "Completed"},
    "failed": {"stage": "failed", "progress": 100, "title": "Failed"},
}


def _serialize_tracklist_summary(tracklist: Tracklist) -> dict:
    status_key = (tracklist.status or "").lower()
    fallback = STATUS_PROGRESS.get(
        status_key,
        {"stage": status_key or "unknown", "progress": 0, "title": status_key or "Unknown"},
    )
    progress_value = (
        int(tracklist.progress_percent)
        if tracklist.progress_percent is not None
        else int(fallback["progress"])
    )
    return {
        "id": str(tracklist.id),
        "task_id": tracklist.task_id,
        "url": tracklist.url,
        "set_title": tracklist.set_title,
        "cover_url": tracklist.cover_url,
        "status": tracklist.status,
        "progress": {
            "stage": fallback["stage"],
            "title": fallback["title"],
            "progress": progress_value,
            "message": tracklist.progress_message,
            "total_segments": tracklist.total_segments,
            "processed_segments": tracklist.processed_segments,
        },
        "created_at": tracklist.created_at.isoformat() if tracklist.created_at else None,
        "updated_at": tracklist.updated_at.isoformat() if tracklist.updated_at else None,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze")
def analyze(request: AnalyzeRequest):
    from app.tasks.download import download_audio
    from app.tasks.analysis import segment_audio
    from app.tasks.fingerprint import identify_tracks
    from app.tasks import aggregate_results

    tracklist_id = uuid.uuid4()
    set_title = None
    cover_url = None
    try:
        metadata = fetch_soundcloud_metadata(request.url)
        set_title = metadata.get("set_title")
        cover_url = metadata.get("cover_url")
    except Exception:
        pass

    try:
        with get_db() as db:
            tracklist = Tracklist(
                id=tracklist_id,
                url=request.url,
                status="pending",
                set_title=set_title,
                cover_url=cover_url,
            )
            db.add(tracklist)
            db.commit()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    task = chain(
        download_audio.s(str(tracklist_id), request.url)
        | segment_audio.s()
        | identify_tracks.s()
        | aggregate_results.s()
    ).apply_async()

    try:
        with get_db() as db:
            persisted = db.get(Tracklist, tracklist_id)
            if persisted is not None:
                persisted.task_id = task.id
                persisted.progress_percent = 5
                persisted.progress_message = "Queued"
                db.commit()
    except SQLAlchemyError:
        pass

    return {"task_id": task.id, "tracklist_id": str(tracklist_id)}


@app.get("/status/{task_id}")
def get_status(task_id: str, tracklist_id: str | None = Query(default=None)):
    result = celery_app.AsyncResult(task_id)
    payload = {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }

    status_tracklist_id = tracklist_id
    if isinstance(result.result, dict):
        status_tracklist_id = result.result.get("tracklist_id") or status_tracklist_id

    if status_tracklist_id:
        try:
            uid = uuid.UUID(status_tracklist_id)
            with get_db() as db:
                tracklist = db.get(Tracklist, uid)
                if tracklist is not None:
                    serialized = _serialize_tracklist_summary(tracklist)
                    payload["tracklist"] = {
                        "id": serialized["id"],
                        "status": serialized["status"],
                        "url": serialized["url"],
                        "set_title": serialized["set_title"],
                        "cover_url": serialized["cover_url"],
                    }
                    payload["progress"] = serialized["progress"]
        except (ValueError, SQLAlchemyError):
            pass

    return payload


@app.get("/jobs")
def list_jobs(
    limit: int = Query(default=20, ge=1, le=200),
    status: str = Query(default="active"),
):
    with get_db() as db:
        # Failed jobs are intentionally auto-pruned from UI-facing list.
        db.query(Tracklist).filter(Tracklist.status == "failed").delete(synchronize_session=False)
        db.commit()

        query = db.query(Tracklist)
        if status == "active":
            query = query.filter(Tracklist.status.in_(["pending", "downloading", "segmenting", "fingerprinting"]))
        elif status == "completed":
            query = query.filter(Tracklist.status == "completed")
        elif status == "all":
            pass
        else:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        query = query.order_by(Tracklist.created_at.desc()).limit(limit)
        items = [_serialize_tracklist_summary(item) for item in query.all()]
    return {"jobs": items}


@app.get("/tracklist/{tracklist_id}")
def get_tracklist(tracklist_id: str):
    try:
        uid = uuid.UUID(tracklist_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tracklist_id")

    with get_db() as db:
        tracklist = db.get(Tracklist, uid)
        if tracklist is None:
            raise HTTPException(status_code=404, detail="Tracklist not found")

        tracks = [
            {
                "id": str(t.id),
                "title": t.title,
                "artist": t.artist,
                "timestamp_start": t.timestamp_start,
                "timestamp_end": t.timestamp_end,
                "snippet_path": t.snippet_path,
                "raw_result": t.raw_result,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tracklist.tracks
        ]
        
        tracks.sort(key=lambda x: x["timestamp_start"] or 0.0)

        return {
            "id": str(tracklist.id),
            "task_id": tracklist.task_id,
            "url": tracklist.url,
            "set_title": tracklist.set_title,
            "cover_url": tracklist.cover_url,
            "status": tracklist.status,
            "progress_percent": tracklist.progress_percent,
            "progress_message": tracklist.progress_message,
            "total_segments": tracklist.total_segments,
            "processed_segments": tracklist.processed_segments,
            "created_at": tracklist.created_at.isoformat() if tracklist.created_at else None,
            "updated_at": tracklist.updated_at.isoformat() if tracklist.updated_at else None,
            "tracks": tracks,
        }


@app.post("/beatport/send-all/{tracklist_id}")
def beatport_send_all(tracklist_id: str, mode: str = "zip"):
    from app.tasks.beatport import send_to_beatportdl
    try:
        uuid.UUID(tracklist_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tracklist_id")
        
    task = send_to_beatportdl.delay(tracklist_id, mode)
    return {"status": "dispatched", "task_id": task.id, "mode": mode}

@app.get("/config")
def get_config():
    return {"beatportdl_api_url": settings.BEATPORTDL_API_URL.rstrip('/')}
