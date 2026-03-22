import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Track, Tracklist

SQLITE_URL = "sqlite://"


@pytest.fixture()
def engine():
    e = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(e)
    yield e
    Base.metadata.drop_all(e)


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.rollback()
    s.close()


def make_fake_get_db(s):
    @contextmanager
    def _fake():
        yield s
    return _fake


@pytest.fixture()
def mock_chain():
    mock_result = MagicMock()
    mock_result.id = "fake-task-id"
    m = MagicMock()
    m.return_value.apply_async.return_value = mock_result
    return m


def test_analyze_returns_task_and_tracklist(session, mock_chain):
    from app.main import app

    with (
        patch("app.main.get_db", side_effect=make_fake_get_db(session)),
        patch("app.main.chain", mock_chain),
    ):
        with TestClient(app) as client:
            resp = client.post("/analyze", json={"url": "https://soundcloud.com/test/track"})

    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert "tracklist_id" in data
    assert data["task_id"] == "fake-task-id"
    uuid.UUID(data["tracklist_id"])
    tl = session.get(Tracklist, uuid.UUID(data["tracklist_id"]))
    assert tl is not None
    assert tl.task_id == "fake-task-id"


def test_get_status():
    from app.main import app

    mock_result = MagicMock()
    mock_result.status = "PENDING"
    mock_result.ready.return_value = False
    mock_result.result = None

    with patch("app.main.celery_app") as mock_ca:
        mock_ca.AsyncResult.return_value = mock_result
        with TestClient(app) as client:
            resp = client.get("/status/some-task-id")

    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "some-task-id"
    assert data["status"] == "PENDING"


def test_get_status_includes_progress(session):
    from app.main import app

    tl_id = uuid.uuid4()
    tl = Tracklist(
        id=tl_id,
        url="https://soundcloud.com/test/mix",
        status="segmenting",
        progress_percent=53,
        progress_message="Extracting snippets 4/10",
    )
    session.add(tl)
    session.commit()

    mock_result = MagicMock()
    mock_result.status = "STARTED"
    mock_result.ready.return_value = False
    mock_result.result = None

    with (
        patch("app.main.celery_app") as mock_ca,
        patch("app.main.get_db", side_effect=make_fake_get_db(session)),
    ):
        mock_ca.AsyncResult.return_value = mock_result
        with TestClient(app) as client:
            resp = client.get(f"/status/some-task-id?tracklist_id={tl_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "STARTED"
    assert data["progress"]["stage"] == "segmenting"
    assert data["progress"]["progress"] == 53
    assert data["progress"]["message"] == "Extracting snippets 4/10"
    assert data["tracklist"]["id"] == str(tl_id)


def test_jobs_endpoint_returns_recent_jobs(session):
    from app.main import app

    one = Tracklist(
        id=uuid.uuid4(),
        task_id="task-1",
        url="https://soundcloud.com/test/a",
        set_title="Set A",
        cover_url="https://img.test/a.jpg",
        status="downloading",
        progress_percent=14,
        progress_message="Downloading audio (40%)",
    )
    two = Tracklist(
        id=uuid.uuid4(),
        task_id="task-2",
        url="https://soundcloud.com/test/b",
        status="completed",
        progress_percent=100,
    )
    session.add(one)
    session.add(two)
    session.commit()

    with patch("app.main.get_db", side_effect=make_fake_get_db(session)):
        with TestClient(app) as client:
            resp = client.get("/jobs?limit=10&status=active")

    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert len(data["jobs"]) >= 1
    found = [item for item in data["jobs"] if item["task_id"] == "task-1"][0]
    assert found["set_title"] == "Set A"
    assert found["cover_url"] == "https://img.test/a.jpg"
    assert found["progress"]["progress"] == 14


def test_jobs_endpoint_completed_tab(session):
    from app.main import app

    session.add(
        Tracklist(
            id=uuid.uuid4(),
            task_id="task-completed",
            url="https://soundcloud.com/test/completed",
            status="completed",
            progress_percent=100,
        )
    )
    session.commit()

    with patch("app.main.get_db", side_effect=make_fake_get_db(session)):
        with TestClient(app) as client:
            resp = client.get("/jobs?limit=10&status=completed")

    assert resp.status_code == 200
    data = resp.json()
    assert any(item["task_id"] == "task-completed" for item in data["jobs"])


def test_get_tracklist_not_found(session):
    from app.main import app
    fake_id = str(uuid.uuid4())

    with patch("app.main.get_db", side_effect=make_fake_get_db(session)):
        with TestClient(app) as client:
            resp = client.get(f"/tracklist/{fake_id}")

    assert resp.status_code == 404


def test_get_tracklist_invalid_uuid():
    from app.main import app

    with TestClient(app) as client:
        resp = client.get("/tracklist/not-a-uuid")

    assert resp.status_code == 400


def test_get_tracklist_success(session):
    from app.main import app
    tl_id = uuid.uuid4()
    tl = Tracklist(id=tl_id, url="https://soundcloud.com/test/mix", status="completed")
    session.add(tl)
    session.commit()

    with patch("app.main.get_db", side_effect=make_fake_get_db(session)):
        with TestClient(app) as client:
            resp = client.get(f"/tracklist/{tl_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(tl_id)
    assert data["status"] == "completed"
    assert data["tracks"] == []


def test_get_tracklist_includes_confidence_fields(session):
    from app.main import app

    tl_id = uuid.uuid4()
    tl = Tracklist(id=tl_id, url="https://soundcloud.com/test/mix", status="completed")
    session.add(tl)
    session.flush()
    session.add(
        Track(
            tracklist_id=tl_id,
            title="Track Title",
            artist="Track Artist",
            timestamp_start=12.0,
            timestamp_end=30.0,
            confidence_score=0.91,
            num_snippets=3,
            num_consistent_snippets=2,
            raw_matches_json=[
                {
                    "snippet_type": "a",
                    "result": {"track": {"title": "Track Title", "subtitle": "Track Artist"}},
                }
            ],
        )
    )
    session.commit()

    with patch("app.main.get_db", side_effect=make_fake_get_db(session)):
        with TestClient(app) as client:
            resp = client.get(f"/tracklist/{tl_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tracks"]) == 1
    track = data["tracks"][0]
    assert track["confidence_score"] == 0.91
    assert track["num_snippets"] == 3
    assert track["num_consistent_snippets"] == 2
    assert track["raw_matches_json"] == [
        {
            "snippet_type": "a",
            "result": {"track": {"title": "Track Title", "subtitle": "Track Artist"}},
        }
    ]
