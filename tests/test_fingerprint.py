import os
import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def tracklist_id():
    return str(uuid.uuid4())


@pytest.fixture()
def analysis_result(tmp_path, tracklist_id):
    snippet1 = tmp_path / f"{tracklist_id}_snippet_0_A.wav"
    snippet1.write_bytes(b"fake wav")
    snippet2 = tmp_path / f"{tracklist_id}_snippet_0_B.wav"
    snippet2.write_bytes(b"fake wav 2")
    snippet3 = tmp_path / f"{tracklist_id}_snippet_1_A.wav"
    snippet3.write_bytes(b"fake wav 3")
    snippet4 = tmp_path / f"{tracklist_id}_snippet_1_B.wav"
    snippet4.write_bytes(b"fake wav 4")
    return {
        "tracklist_id": tracklist_id,
        "segments": [
            {
                "segment_index": 0,
                "timestamp": 0.0,
                "candidates": [
                    {"path": str(snippet1), "snippet_type": "A", "segment_index": 0, "snippet_start": 2.0},
                    {"path": str(snippet2), "snippet_type": "B", "segment_index": 0, "snippet_start": 30.0},
                ],
            },
            {
                "segment_index": 1,
                "timestamp": 60.0,
                "candidates": [
                    {"path": str(snippet3), "snippet_type": "A", "segment_index": 1, "snippet_start": 62.0},
                    {"path": str(snippet4), "snippet_type": "B", "segment_index": 1, "snippet_start": 90.0},
                ],
            },
        ],
    }


KNOWN_RESULT = {"track": {"title": "Test Track", "subtitle": "Test Artist", "key": "12345"}}
LOW_SCORE = 0.1
HIGH_SCORE = 0.8


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
    identified = [r for r in result["identifications"] if r["result"] not in (None, {})]
    assert len(identified) == 2
    for item in identified:
        assert item["result"]["track"]["title"] == "Test Track"
        assert item["confidence_score"] >= 0.9
        assert item["num_snippets"] == 1
        assert item["num_consistent_snippets"] == 1


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
        assert item["confidence_score"] == 0.0
        assert item["num_consistent_snippets"] == 0


def test_missing_snippet_handled(tracklist_id):
    analysis = {
        "tracklist_id": tracklist_id,
        "segments": [
            {
                "segment_index": 0,
                "timestamp": 30.0,
                "candidates": [{"path": "/nonexistent/path.wav", "snippet_type": "A", "segment_index": 0}],
            }
        ],
    }

    mock_shazamio = MagicMock()

    with patch.dict("sys.modules", {"shazamio": mock_shazamio}):
        from app.tasks.fingerprint import identify_tracks

        result = identify_tracks.__wrapped__(analysis)

    assert result["identifications"][0]["result"] is None
    assert result["identifications"][0]["confidence_score"] == 0.0


def test_rate_limit_configured():
    from app.tasks.fingerprint import identify_tracks

    assert identify_tracks.rate_limit == "15/m"


def test_snippets_cleaned_up_after_identification(analysis_result):
    paths = [c["path"] for s in analysis_result["segments"] for c in s["candidates"]]
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


def test_inconsistent_segment_reduces_confidence(tracklist_id, tmp_path):
    snippet1 = tmp_path / f"{tracklist_id}_snippet_0_A.wav"
    snippet1.write_bytes(b"one")
    snippet2 = tmp_path / f"{tracklist_id}_snippet_0_B.wav"
    snippet2.write_bytes(b"two")
    analysis = {
        "tracklist_id": tracklist_id,
        "segments": [
            {
                "segment_index": 0,
                "timestamp": 0.0,
                "duration": 120.0,
                "candidates": [
                    {"path": str(snippet1), "snippet_type": "A", "segment_index": 0},
                    {"path": str(snippet2), "snippet_type": "B", "segment_index": 0},
                ],
            }
        ],
    }

    async def fake_recognize(path):
        if path.endswith("_A.wav"):
            return {"track": {"title": "Track A", "subtitle": "Artist A", "score": LOW_SCORE}}
        return {"track": {"title": "Track B", "subtitle": "Artist B", "score": HIGH_SCORE}}

    mock_shazam_cls = MagicMock()
    mock_shazam_instance = MagicMock()
    mock_shazam_instance.recognize = fake_recognize
    mock_shazam_cls.return_value = mock_shazam_instance
    mock_shazamio = MagicMock()
    mock_shazamio.Shazam = mock_shazam_cls

    with patch.dict("sys.modules", {"shazamio": mock_shazamio}):
        from app.tasks.fingerprint import identify_tracks

        result = identify_tracks.__wrapped__(analysis)

    item = result["identifications"][0]
    assert item["result"]["track"]["title"] == "Track B"
    assert item["num_snippets"] == 2
    assert item["num_consistent_snippets"] == 1
    assert item["confidence_score"] == 0.6


def test_backoff_retries_on_429_and_succeeds():
    import asyncio

    sleep_calls = []
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise Exception("429 Too Many Requests")
        return {"ok": True}

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    with patch("app.tasks.fingerprint.asyncio.sleep", side_effect=fake_sleep):
        from app.tasks.fingerprint import call_with_backoff

        result, retries = asyncio.run(call_with_backoff(flaky, max_retries=5, base_delay=2.0))

    assert result == {"ok": True}
    assert retries == 2
    assert sleep_calls == [2.0, 4.0]


def test_max_shazam_calls_per_analysis_respected(tracklist_id, tmp_path):
    snippets = []
    segments = []
    for seg_idx in range(3):
        a = tmp_path / f"{tracklist_id}_snippet_{seg_idx}_A.wav"
        b = tmp_path / f"{tracklist_id}_snippet_{seg_idx}_B.wav"
        a.write_bytes(b"a")
        b.write_bytes(b"b")
        snippets.extend([str(a), str(b)])
        segments.append(
            {
                "segment_index": seg_idx,
                "timestamp": float(seg_idx * 60),
                "duration": 120.0,
                "candidates": [
                    {"path": str(a), "snippet_type": "A", "segment_index": seg_idx, "snippet_start": 2.0},
                    {"path": str(b), "snippet_type": "B", "segment_index": seg_idx, "snippet_start": 62.0},
                ],
            }
        )
    analysis = {"tracklist_id": tracklist_id, "segments": segments}

    calls = {"count": 0}

    async def fake_identify(_path):
        from app.tasks.fingerprint import ShazamResult

        calls["count"] += 1
        return ShazamResult(result={}, no_match=True)

    with (
        patch("app.tasks.fingerprint.identify_snippet", side_effect=fake_identify),
        patch("app.tasks.fingerprint.settings") as mock_settings,
    ):
        mock_settings.MAX_SHAZAM_CALLS_PER_ANALYSIS = 2
        from app.tasks.fingerprint import identify_tracks

        result = identify_tracks.__wrapped__(analysis)

    assert calls["count"] == 2
    assert len(result["identifications"]) == 3
    assert result["identifications"][0]["num_snippets"] == 2
    assert result["identifications"][1]["num_snippets"] == 0
    assert result["identifications"][2]["num_snippets"] == 0


def test_json_error_becomes_no_match():
    import asyncio

    async def fake_sleep(_delay):
        return None

    async def failing_recognize(_path):
        raise ValueError("JSON decode error")

    mock_shazam_cls = MagicMock()
    mock_shazam_instance = MagicMock()
    mock_shazam_instance.recognize = failing_recognize
    mock_shazam_cls.return_value = mock_shazam_instance
    mock_shazamio = MagicMock()
    mock_shazamio.Shazam = mock_shazam_cls

    with (
        patch.dict("sys.modules", {"shazamio": mock_shazamio}),
        patch("app.tasks.fingerprint.asyncio.sleep", side_effect=fake_sleep),
    ):
        from app.tasks.fingerprint import identify_snippet

        result = asyncio.run(identify_snippet("/tmp/fake.wav"))

    assert result.no_match is True
    assert result.result == {}


def test_budget_exhausted_mid_segment_skips_fallback(tracklist_id, tmp_path):
    snippet_a = tmp_path / f"{tracklist_id}_snippet_0_A.wav"
    snippet_b = tmp_path / f"{tracklist_id}_snippet_0_B.wav"
    snippet_a.write_bytes(b"a")
    snippet_b.write_bytes(b"b")
    analysis = {
        "tracklist_id": tracklist_id,
        "segments": [
            {
                "segment_index": 0,
                "timestamp": 0.0,
                "duration": 120.0,
                "candidates": [
                    {"path": str(snippet_a), "snippet_type": "A", "segment_index": 0, "snippet_start": 2.0},
                    {"path": str(snippet_b), "snippet_type": "B", "segment_index": 0, "snippet_start": 62.0},
                ],
            }
        ],
    }

    call_paths = []

    async def fake_identify(path):
        from app.tasks.fingerprint import ShazamResult

        call_paths.append(path)
        return ShazamResult(result={}, no_match=True)

    with (
        patch("app.tasks.fingerprint.identify_snippet", side_effect=fake_identify),
        patch("app.tasks.fingerprint.settings") as mock_settings,
    ):
        mock_settings.MAX_SHAZAM_CALLS_PER_ANALYSIS = 1
        from app.tasks.fingerprint import identify_tracks

        result = identify_tracks.__wrapped__(analysis)

    assert call_paths == [str(snippet_a)]
    assert result["identifications"][0]["num_snippets"] == 1
    assert result["identifications"][0]["result"] == {}
