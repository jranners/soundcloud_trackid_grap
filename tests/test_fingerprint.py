import os
import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def tracklist_id():
    return str(uuid.uuid4())


@pytest.fixture()
def analysis_result(tmp_path, tracklist_id):
    snippet1 = tmp_path / f"{tracklist_id}_snippet_30.wav"
    snippet1.write_bytes(b"fake wav")
    snippet2 = tmp_path / f"{tracklist_id}_snippet_90.wav"
    snippet2.write_bytes(b"fake wav 2")
    return {
        "tracklist_id": tracklist_id,
        "segments": [
            {"path": str(snippet1), "timestamp": 0.0},
            {"path": str(snippet2), "timestamp": 60.0},
        ],
    }


KNOWN_RESULT = {"track": {"title": "Test Track", "subtitle": "Test Artist", "key": "12345"}}


def test_known_track_identified(analysis_result):
    async def fake_recognize(path):
        return KNOWN_RESULT

    mock_shazam_cls = MagicMock()
    mock_shazam_instance = MagicMock()
    mock_shazam_instance.recognize = fake_recognize
    mock_shazam_cls.return_value = mock_shazam_instance

    mock_shazamio = MagicMock()
    mock_shazamio.Shazam = mock_shazam_cls

    with patch.dict("sys.modules", {"shazamio": mock_shazamio}):
        from app.tasks.fingerprint import identify_tracks

        result = identify_tracks.__wrapped__(analysis_result)

    assert result["tracklist_id"] == analysis_result["tracklist_id"]
    identified = [r for r in result["identifications"] if r["result"] is not None]
    assert len(identified) == 2
    for item in identified:
        assert item["result"]["track"]["title"] == "Test Track"


def test_unknown_track_handled(analysis_result):
    async def fake_recognize(path):
        return {}

    mock_shazam_cls = MagicMock()
    mock_shazam_instance = MagicMock()
    mock_shazam_instance.recognize = fake_recognize
    mock_shazam_cls.return_value = mock_shazam_instance

    mock_shazamio = MagicMock()
    mock_shazamio.Shazam = mock_shazam_cls

    with patch.dict("sys.modules", {"shazamio": mock_shazamio}):
        from app.tasks.fingerprint import identify_tracks

        result = identify_tracks.__wrapped__(analysis_result)

    assert len(result["identifications"]) == 2
    for item in result["identifications"]:
        assert item["result"] == {}


def test_missing_snippet_handled(tracklist_id):
    analysis = {
        "tracklist_id": tracklist_id,
        "segments": [{"path": "/nonexistent/path.wav", "timestamp": 30.0}],
    }

    mock_shazamio = MagicMock()

    with patch.dict("sys.modules", {"shazamio": mock_shazamio}):
        from app.tasks.fingerprint import identify_tracks

        result = identify_tracks.__wrapped__(analysis)

    assert result["identifications"][0]["result"] is None


def test_rate_limit_configured():
    from app.tasks.fingerprint import identify_tracks

    assert identify_tracks.rate_limit == "15/m"


def test_snippets_cleaned_up_after_identification(analysis_result):
    paths = [s["path"] for s in analysis_result["segments"]]
    for p in paths:
        assert os.path.exists(p)

    async def fake_recognize(path):
        return KNOWN_RESULT

    mock_shazam_cls = MagicMock()
    mock_shazam_instance = MagicMock()
    mock_shazam_instance.recognize = fake_recognize
    mock_shazam_cls.return_value = mock_shazam_instance

    mock_shazamio = MagicMock()
    mock_shazamio.Shazam = mock_shazam_cls

    with patch.dict("sys.modules", {"shazamio": mock_shazamio}):
        from app.tasks.fingerprint import identify_tracks

        identify_tracks.__wrapped__(analysis_result)

    for p in paths:
        assert not os.path.exists(p)
