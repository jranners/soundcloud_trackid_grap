import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Tracklist

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
