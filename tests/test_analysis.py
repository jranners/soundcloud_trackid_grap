import os
import uuid
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
        from app.tasks.analysis import segment_audio

        result = segment_audio.__wrapped__(download_result)

    assert result["tracklist_id"] == tracklist_id
    assert isinstance(result["segments"], list)


def test_12s_snippets_extracted(tmp_path, tracklist_id, download_result):
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
        from app.tasks.analysis import segment_audio

        segment_audio.__wrapped__(download_result)

    for start, duration, _ in extracted_calls:
        assert duration == 12


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
