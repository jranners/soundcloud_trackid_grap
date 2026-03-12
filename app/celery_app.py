from celery import Celery

from app.config import settings

celery_app = Celery(
    "soundcloud_trackid",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.download",
        "app.tasks.analysis",
        "app.tasks.fingerprint",
        "app.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_queues={
        "download": {"exchange": "download", "routing_key": "download"},
        "analysis": {"exchange": "analysis", "routing_key": "analysis"},
        "fingerprint": {"exchange": "fingerprint", "routing_key": "fingerprint"},
    },
    task_routes={
        "app.tasks.download.*": {"queue": "download"},
        "app.tasks.analysis.*": {"queue": "analysis"},
        "app.tasks.fingerprint.*": {"queue": "fingerprint"},
        "app.tasks.aggregate_results": {"queue": "analysis"},
    },
    task_default_queue="analysis",
)
