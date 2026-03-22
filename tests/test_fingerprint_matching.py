from unittest.mock import patch

import pytest

from app.tasks.fingerprint import (
    DISAGREEMENT_CONFIDENCE,
    ShazamResult,
    _is_uncertain_result,
    _select_best_candidate,
    identify_tracks,
)


@pytest.fixture()
def tracklist_id():
    return "tracklist-test-id"


def test_is_uncertain_result_for_zero_low_or_missing_metadata():
    assert _is_uncertain_result({"track": {"title": "Song", "subtitle": "Artist", "score": 0}}) is True
    assert _is_uncertain_result({"track": {"title": "Song", "subtitle": "Artist", "score": 0.05}}) is True
    assert _is_uncertain_result({"track": {"score": 0.8}}) is True


def test_is_uncertain_result_false_for_good_result():
    assert _is_uncertain_result({"track": {"title": "Song", "subtitle": "Artist", "score": 0.9}}) is False


def test_select_best_candidate_prefers_higher_score():
    candidate_a = {"track": {"title": "A", "subtitle": "Artist A", "score": 0.2}}
    candidate_b = {"track": {"title": "B", "subtitle": "Artist B", "score": 0.7}}

    selected, confidence = _select_best_candidate(candidate_a, candidate_b)

    assert selected is candidate_b
    assert confidence == DISAGREEMENT_CONFIDENCE


def test_select_best_candidate_prefers_better_metadata_when_scores_tie():
    candidate_a = {"track": {"title": "A", "subtitle": "Artist A", "score": 0.5}}
    candidate_b = {"track": {"title": "B", "score": 0.5}}

    selected, confidence = _select_best_candidate(candidate_a, candidate_b)

    assert selected is candidate_a
    assert confidence == DISAGREEMENT_CONFIDENCE


def test_identify_tracks_consistent_a_b_gives_high_confidence(tracklist_id, tmp_path):
    snippet_a = tmp_path / "snippet_A.wav"
    snippet_b = tmp_path / "snippet_B.wav"
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
                    {"path": str(snippet_a), "snippet_type": "A", "segment_index": 0, "snippet_start": 0.0},
                    {"path": str(snippet_b), "snippet_type": "B", "segment_index": 0, "snippet_start": 60.0},
                ],
            }
        ],
    }

    async def fake_identify(_path):
        return ShazamResult(
            result={"track": {"title": "Same Song", "subtitle": "Same Artist", "score": 0.1}},
            no_match=False,
        )

    with patch("app.tasks.fingerprint.identify_snippet", side_effect=fake_identify):
        result = identify_tracks.__wrapped__(analysis)

    item = result["identifications"][0]
    assert item["confidence_score"] == 0.95
    assert item["num_consistent_snippets"] == 2
    assert item["num_snippets"] == 2


def test_identify_tracks_inconsistent_a_b_uses_best_candidate(tracklist_id, tmp_path):
    snippet_a = tmp_path / "snippet_A.wav"
    snippet_b = tmp_path / "snippet_B.wav"
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
                    {"path": str(snippet_a), "snippet_type": "A", "segment_index": 0, "snippet_start": 0.0},
                    {"path": str(snippet_b), "snippet_type": "B", "segment_index": 0, "snippet_start": 60.0},
                ],
            }
        ],
    }

    async def fake_identify(path):
        if path.endswith("snippet_A.wav"):
            return ShazamResult(
                result={"track": {"title": "Song A", "subtitle": "Artist A", "score": 0.1}},
                no_match=False,
            )
        return ShazamResult(
            result={"track": {"title": "Song B", "subtitle": "Artist B", "score": 0.8}},
            no_match=False,
        )

    with patch("app.tasks.fingerprint.identify_snippet", side_effect=fake_identify):
        result = identify_tracks.__wrapped__(analysis)

    item = result["identifications"][0]
    assert item["result"]["track"]["title"] == "Song B"
    assert item["confidence_score"] == DISAGREEMENT_CONFIDENCE
    assert item["num_consistent_snippets"] == 1
    assert item["num_snippets"] == 2


def test_identify_tracks_only_a_used_and_confidence_09(tracklist_id, tmp_path):
    snippet_a = tmp_path / "snippet_A.wav"
    snippet_b = tmp_path / "snippet_B.wav"
    snippet_a.write_bytes(b"a")
    snippet_b.write_bytes(b"b")

    analysis = {
        "tracklist_id": tracklist_id,
        "segments": [
            {
                "segment_index": 0,
                "timestamp": 0.0,
                "duration": 60.0,  # below fallback threshold, so B must not be used
                "candidates": [
                    {"path": str(snippet_a), "snippet_type": "A", "segment_index": 0, "snippet_start": 0.0},
                    {"path": str(snippet_b), "snippet_type": "B", "segment_index": 0, "snippet_start": 40.0},
                ],
            }
        ],
    }

    async def fake_identify(_path):
        return ShazamResult(
            result={"track": {"title": "Only A", "subtitle": "Artist A", "score": 0.9}},
            no_match=False,
        )

    with patch("app.tasks.fingerprint.identify_snippet", side_effect=fake_identify) as mocked_identify:
        result = identify_tracks.__wrapped__(analysis)

    item = result["identifications"][0]
    assert item["confidence_score"] == 0.9
    assert item["num_snippets"] == 1
    assert item["num_consistent_snippets"] == 1
    assert mocked_identify.call_count == 1


def test_identify_tracks_no_valid_snippet_candidates_logs_warning_and_empty_result(tracklist_id, caplog):
    analysis = {
        "tracklist_id": tracklist_id,
        "segments": [
            {
                "segment_index": 0,
                "timestamp": 42.0,
                "duration": 120.0,
                "candidates": [
                    {"path": "/does/not/exist/a.wav", "snippet_type": "A", "segment_index": 0},
                    {"path": "/does/not/exist/b.wav", "snippet_type": "B", "segment_index": 0},
                ],
            }
        ],
    }

    with caplog.at_level("WARNING"):
        result = identify_tracks.__wrapped__(analysis)

    item = result["identifications"][0]
    assert item["result"] is None
    assert item["num_snippets"] == 0
    assert "No valid snippet candidates for transition" in caplog.text
