import uuid

from celery import chain
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.database import get_db
from app.models import Tracklist

app = FastAPI(title="SoundCloud TrackID Grabber")


class AnalyzeRequest(BaseModel):
    url: str


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

    try:
        with get_db() as db:
            tracklist = Tracklist(id=tracklist_id, url=request.url, status="pending")
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

    return {"task_id": task.id, "tracklist_id": str(tracklist_id)}


@app.get("/status/{task_id}")
def get_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }


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

        return {
            "id": str(tracklist.id),
            "url": tracklist.url,
            "status": tracklist.status,
            "created_at": tracklist.created_at.isoformat() if tracklist.created_at else None,
            "updated_at": tracklist.updated_at.isoformat() if tracklist.updated_at else None,
            "tracks": tracks,
        }
