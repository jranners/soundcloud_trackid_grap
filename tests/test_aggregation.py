import uuid
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Track, Tracklist

SQLITE_URL = "sqlite://"


@pytest.fixture()
def db_engine():
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    s = Session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture()
def tracklist_id(db_session):
    tl_id = uuid.uuid4()
    tl = Tracklist(id=tl_id, url="https://soundcloud.com/test/mix", status="processing")
    db_session.add(tl)
    db_session.commit()
    return str(tl_id)


@pytest.fixture()
def fingerprint_result(tracklist_id):
    return {
        "tracklist_id": tracklist_id,
        "identifications": [
            {"timestamp": 0.0, "result": {"track": {"title": "Track A", "subtitle": "Artist A"}}},
            {"timestamp": 60.0, "result": {"track": {"title": "Track B", "subtitle": "Artist B"}}},
            {"timestamp": 120.0, "result": None},
        ],
    }


def _make_get_db(db_session):
    @contextmanager
    def fake_get_db():
        yield db_session

    return fake_get_db


def test_tracks_saved_to_db(db_session, tracklist_id, fingerprint_result):
    with (
        patch("app.tasks.get_db", side_effect=_make_get_db(db_session)),
        patch("app.tasks.glob.glob", return_value=[]),
    ):
        from app.tasks import aggregate_results

        result = aggregate_results.__wrapped__(fingerprint_result)

    tracks = db_session.query(Track).filter_by(tracklist_id=uuid.UUID(tracklist_id)).all()
    assert len(tracks) == 3
    titled = [t for t in tracks if t.title is not None]
    assert len(titled) == 2
    titles = {t.title for t in titled}
    assert "Track A" in titles
    assert "Track B" in titles


def test_tracklist_status_updated(db_session, tracklist_id, fingerprint_result):
    with (
        patch("app.tasks.get_db", side_effect=_make_get_db(db_session)),
        patch("app.tasks.glob.glob", return_value=[]),
    ):
        from app.tasks import aggregate_results

        aggregate_results.__wrapped__(fingerprint_result)

    tl = db_session.get(Tracklist, uuid.UUID(tracklist_id))
    assert tl.status == "completed"


def test_cleanup_runs_on_failure(db_session, tracklist_id, tmp_path):
    stale_file = tmp_path / f"{tracklist_id}_snippet_30.wav"
    stale_file.write_bytes(b"stale")
    removed_files = []

    def fake_remove(path):
        removed_files.append(path)

    bad_result = {
        "tracklist_id": tracklist_id,
        "identifications": [
            {"timestamp": 0.0, "result": {"track": {"title": "X", "subtitle": "Y"}}}
        ],
    }

    with (
        patch("app.tasks.get_db", side_effect=_make_get_db(db_session)),
        patch("app.tasks.glob.glob", return_value=[str(stale_file)]),
        patch("app.tasks.os.remove", side_effect=fake_remove),
    ):
        from app.tasks import aggregate_results

        aggregate_results.__wrapped__(bad_result)

    assert str(stale_file) in removed_files


def test_cleanup_runs_even_on_db_error(db_session, tmp_path):
    bad_id = str(uuid.uuid4())
    stale_file = tmp_path / f"{bad_id}_snippet.wav"
    stale_file.write_bytes(b"stale")
    removed_files = []

    def fake_remove(path):
        removed_files.append(path)

    bad_result = {"tracklist_id": bad_id, "identifications": []}

    with (
        patch("app.tasks.get_db", side_effect=_make_get_db(db_session)),
        patch("app.tasks.glob.glob", return_value=[str(stale_file)]),
        patch("app.tasks.os.remove", side_effect=fake_remove),
    ):
        from app.tasks import aggregate_results

        result = aggregate_results.__wrapped__(bad_result)

    assert str(stale_file) in removed_files
    assert result.get("error") == "not found"
