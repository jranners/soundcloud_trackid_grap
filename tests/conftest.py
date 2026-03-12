import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock, patch

from app.models import Base


SQLITE_URL = "sqlite://"


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(SQLITE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture()
def mock_celery_app():
    with patch("app.celery_app.celery_app") as mock_app:
        mock_task = MagicMock()
        mock_task.id = "test-task-id"
        mock_app.AsyncResult.return_value = MagicMock(
            status="PENDING", ready=lambda: False, result=None
        )
        yield mock_app


@pytest.fixture()
def test_client(db_session):
    from app.main import app
    from app import database

    def override_get_db():
        from contextlib import contextmanager

        @contextmanager
        def _get_db():
            yield db_session

        return _get_db()

    with patch("app.main.get_db") as mock_get_db:
        mock_get_db.return_value.__enter__ = lambda s: db_session
        mock_get_db.return_value.__exit__ = MagicMock(return_value=False)

        with TestClient(app) as client:
            yield client
