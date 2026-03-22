import os
import uuid
from types import ModuleType
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


@pytest.fixture()
def tracklist_id():
    return str(uuid.uuid4())


@pytest.fixture()
def download_result(tmp_path, tracklist_id):
    audio_file = tmp_path / f"{tracklist_id}.mp3"
    audio_file.write_bytes(b"fake audio data")
    return {"tracklist_id": tracklist_id, "audio_path": str(audio_file), "url": "https://test"}


def _make_mock_es():
    mock_es = MagicMock()
    fake_audio = np.zeros(44100 * 120, dtype="float32")

    mock_loader_instance = MagicMock()
    mock_loader_instance.return_value = fake_audio
    mock_es.MonoLoader.return_value = mock_loader_instance

    mock_sbic_instance = MagicMock()
    mock_sbic_instance.return_value = np.array([1000, 2000], dtype="float32")
    mock_es.SBic.return_value = mock_sbic_instance

    mock_mfcc_instance = MagicMock()
    mock_mfcc_instance.return_value = (MagicMock(), np.zeros(13, dtype="float32"))
    mock_es.MFCC.return_value = mock_mfcc_instance

    mock_es.Windowing.return_value = MagicMock(return_value=np.zeros(2048, dtype="float32"))
    mock_es.Spectrum.return_value = MagicMock(return_value=np.zeros(1025, dtype="float32"))
    mock_es.FrameGenerator.return_value = [np.zeros(2048, dtype="float32")] * 3

    return mock_es


def test_sbic_detects_transitions(tmp_path, tracklist_id, download_result):
    mock_es = _make_mock_es()

    with (
        patch.dict("sys.modules", {"essentia": MagicMock(), "essentia.standard": mock_es}),
        patch("app.tasks.analysis.settings") as mock_settings,
        patch("app.tasks.analysis._extract_snippet", return_value=True),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)
        mock_settings.SNIPPET_DURATION_SECONDS = 8
        mock_settings.MIN_SEGMENT_DURATION = 45.0
        mock_settings.DJ_MIN_TRACK_GAP = 75
        mock_settings.DJ_IDEAL_TRACK_GAP = 105
        mock_settings.DJ_MAX_TRACK_GAP = 150
        from app.tasks.analysis import segment_audio

        result = segment_audio.__wrapped__(download_result)

    assert result["tracklist_id"] == tracklist_id
    assert isinstance(result["segments"], list)


def test_snippets_use_settings_duration(tmp_path, tracklist_id, download_result):
    mock_es = _make_mock_es()
    extracted_calls = []

    def fake_extract(src, start, duration, out_path):
        extracted_calls.append((start, duration, out_path))
        return True

    with (
        patch.dict("sys.modules", {"essentia": MagicMock(), "essentia.standard": mock_es}),
        patch("app.tasks.analysis.settings") as mock_settings,
        patch("app.tasks.analysis._extract_snippet", side_effect=fake_extract),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)
        mock_settings.SNIPPET_DURATION_SECONDS = 8
        mock_settings.MIN_SEGMENT_DURATION = 45.0
        mock_settings.DJ_MIN_TRACK_GAP = 75
        mock_settings.DJ_IDEAL_TRACK_GAP = 105
        mock_settings.DJ_MAX_TRACK_GAP = 150
        from app.tasks.analysis import segment_audio

        segment_audio.__wrapped__(download_result)

    for start, duration, _ in extracted_calls:
        assert duration == 8


def test_fallback_when_no_transitions(tmp_path, tracklist_id, download_result):
    mock_es = _make_mock_es()
    mock_sbic_instance = MagicMock()
    mock_sbic_instance.return_value = np.array([], dtype="float32")
    mock_es.SBic.return_value = mock_sbic_instance

    mock_beat_instance = MagicMock()
    mock_beat_instance.return_value = (np.linspace(30, 300, 50, dtype="float32"), None)
    mock_es.BeatTrackerMultiFeature.return_value = mock_beat_instance

    mock_onset = MagicMock()
    mock_onset.return_value = 0.0
    mock_es.OnsetDetection.return_value = mock_onset
    mock_es.FFT.return_value = MagicMock(return_value=np.zeros(512, dtype="complex64"))
    mock_es.CartesianToPolar.return_value = MagicMock(
        return_value=(np.zeros(257, dtype="float32"), np.zeros(257, dtype="float32"))
    )

    with (
        patch.dict("sys.modules", {"essentia": MagicMock(), "essentia.standard": mock_es}),
        patch("app.tasks.analysis.settings") as mock_settings,
        patch("app.tasks.analysis._extract_snippet", return_value=True),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)
        mock_settings.SNIPPET_DURATION_SECONDS = 8
        mock_settings.MIN_SEGMENT_DURATION = 45.0
        mock_settings.DJ_MIN_TRACK_GAP = 75
        mock_settings.DJ_IDEAL_TRACK_GAP = 105
        mock_settings.DJ_MAX_TRACK_GAP = 150
        from app.tasks.analysis import segment_audio

        result = segment_audio.__wrapped__(download_result)

    assert isinstance(result["segments"], list)


def test_ffmpeg_conversion_called(tmp_path):
    import subprocess

    src = str(tmp_path / "input.mp3")
    out = str(tmp_path / "output.wav")

    mock_result = MagicMock()
    mock_result.returncode = 0

    with (
        patch("app.tasks.analysis.subprocess.run", return_value=mock_result) as mock_run,
        patch("os.path.exists", return_value=True),
    ):
        from app.tasks.analysis import _extract_snippet

        success = _extract_snippet(src, 30.0, 12, out)

    assert success is True
    args = mock_run.call_args[0][0]
    assert "ffmpeg" in args
    assert "-ar" in args
    assert "16000" in args
    assert "-ac" in args
    assert "1" in args


def test_sbic_uses_current_parameter_names(tmp_path, tracklist_id, download_result):
    mock_es = _make_mock_es()
    mock_essentia_module = ModuleType("essentia")
    mock_essentia_module.standard = mock_es

    with (
        patch.dict("sys.modules", {"essentia": mock_essentia_module, "essentia.standard": mock_es}),
        patch("app.tasks.analysis.settings") as mock_settings,
        patch("app.tasks.analysis._extract_snippet", return_value=True),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)
        mock_settings.SNIPPET_DURATION_SECONDS = 8
        mock_settings.MIN_SEGMENT_DURATION = 45.0
        mock_settings.DJ_MIN_TRACK_GAP = 75
        mock_settings.DJ_IDEAL_TRACK_GAP = 105
        mock_settings.DJ_MAX_TRACK_GAP = 150
        from app.tasks.analysis import segment_audio

        segment_audio.__wrapped__(download_result)

    kwargs = mock_es.SBic.call_args.kwargs
    assert "inc1" in kwargs
    assert "inc2" in kwargs
    assert "minLength" in kwargs
    assert "increase" not in kwargs
    assert "minSegLen" not in kwargs


def test_enforce_dj_track_spacing_prefers_around_105_seconds():
    from app.tasks.analysis import _enforce_dj_track_spacing

    transitions = [31.0, 90.0, 132.0, 210.0, 235.0, 315.0, 420.0]
    selected = _enforce_dj_track_spacing(transitions)

    assert selected[0] == 31.0
    assert 132.0 in selected
    assert 235.0 in selected
    assert 315.0 in selected


def test_enforce_dj_track_spacing_returns_empty_for_empty():
    from app.tasks.analysis import _enforce_dj_track_spacing

    assert _enforce_dj_track_spacing([]) == []


def test_enforce_dj_track_spacing_uses_settings_values():
    from app.tasks.analysis import _enforce_dj_track_spacing

    transitions = [10.0, 60.0, 120.0, 170.0, 230.0]

    with patch("app.tasks.analysis.settings") as mock_settings:
        mock_settings.DJ_MIN_TRACK_GAP = 45
        mock_settings.DJ_IDEAL_TRACK_GAP = 60
        mock_settings.DJ_MAX_TRACK_GAP = 80
        selected = _enforce_dj_track_spacing(transitions)

    assert selected == [10.0, 60.0, 120.0, 170.0, 230.0]
    gaps = [b - a for a, b in zip(selected, selected[1:])]
    assert all(45 <= gap <= 80 for gap in gaps)


def test_enforce_dj_track_spacing_filters_out_of_window_candidates():
    from app.tasks.analysis import _enforce_dj_track_spacing

    transitions = [10.0, 40.0, 80.0, 125.0, 170.0, 260.0]

    with patch("app.tasks.analysis.settings") as mock_settings:
        mock_settings.DJ_MIN_TRACK_GAP = 45
        mock_settings.DJ_IDEAL_TRACK_GAP = 60
        mock_settings.DJ_MAX_TRACK_GAP = 80
        selected = _enforce_dj_track_spacing(transitions)

    assert selected == [10.0, 80.0, 125.0, 170.0, 260.0]
    assert 40.0 not in selected


def test_merge_short_segments_enforces_min_duration():
    from app.tasks.analysis import merge_short_segments

    merged = merge_short_segments(
        [(0.0, 30.0), (30.0, 90.0), (90.0, 120.0), (120.0, 190.0)],
        min_duration=45.0,
    )
    durations = [end - start for start, end in merged]

    assert all(d >= 45.0 for d in durations)


def test_merge_short_segments_handles_cascading_short_segments():
    from app.tasks.analysis import merge_short_segments

    merged = merge_short_segments(
        [(0.0, 20.0), (20.0, 40.0), (40.0, 60.0), (60.0, 160.0)],
        min_duration=45.0,
    )
    durations = [end - start for start, end in merged]

    assert all(d >= 45.0 for d in durations[:-1])


def test_merge_short_segments_uses_settings_default():
    from app.tasks.analysis import merge_short_segments

    with patch("app.tasks.analysis.settings") as mock_settings:
        mock_settings.MIN_SEGMENT_DURATION = 55.0
        merged = merge_short_segments([(0.0, 50.0), (50.0, 120.0)])

    assert merged == [(0.0, 120.0)]
