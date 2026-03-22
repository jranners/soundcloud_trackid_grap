import json
import uuid
from types import ModuleType
from unittest.mock import MagicMock, patch

import numpy as np


def _make_mock_es_with_boundaries(boundary_times, sample_rate=44100, hop_size=1024):
    mock_es = MagicMock()
    fake_audio = np.ones(sample_rate * 180, dtype="float32") * 0.1

    mock_loader_instance = MagicMock()
    mock_loader_instance.return_value = fake_audio
    mock_es.MonoLoader.return_value = mock_loader_instance

    boundary_frames = np.array([int(t / (hop_size / sample_rate)) for t in boundary_times], dtype="float32")
    mock_sbic_instance = MagicMock()
    mock_sbic_instance.return_value = boundary_frames
    mock_es.SBic.return_value = mock_sbic_instance

    mock_mfcc_instance = MagicMock()
    mock_mfcc_instance.return_value = (None, np.arange(13, dtype="float32"))
    mock_es.MFCC.return_value = mock_mfcc_instance

    mock_es.Windowing.return_value = MagicMock(side_effect=lambda x: x)
    mock_es.Spectrum.return_value = MagicMock(return_value=np.ones(1025, dtype="float32"))
    mock_es.FrameGenerator.side_effect = lambda *_args, **_kwargs: [np.ones(2048, dtype="float32")] * 3
    mock_es.BeatTrackerMultiFeature.return_value = MagicMock(return_value=([], None))
    mock_es.OnsetDetection.return_value = MagicMock(return_value=0.0)
    mock_es.FFT.return_value = MagicMock(return_value=np.zeros(512, dtype="complex64"))
    mock_es.CartesianToPolar.return_value = MagicMock(
        return_value=(np.zeros(257, dtype="float32"), np.zeros(257, dtype="float32"))
    )
    return mock_es


def test_segment_features_pipeline_and_min_duration(tmp_path):
    tracklist_id = str(uuid.uuid4())
    audio_file = tmp_path / f"{tracklist_id}.mp3"
    audio_file.write_bytes(b"fake audio data")

    download_result = {"tracklist_id": tracklist_id, "audio_path": str(audio_file), "url": "https://test"}
    mock_es = _make_mock_es_with_boundaries(boundary_times=[35.0, 70.0, 100.0])
    mock_essentia_module = ModuleType("essentia")
    mock_essentia_module.standard = mock_es

    with (
        patch.dict("sys.modules", {"essentia": mock_essentia_module, "essentia.standard": mock_es}),
        patch("app.tasks.analysis.settings") as mock_settings,
        patch("app.tasks.analysis._extract_snippet", return_value=True),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)
        from app.tasks.analysis import segment_audio

        result = segment_audio.__wrapped__(download_result)

    segments = result["segments"]
    durations = [s["duration"] for s in segments]
    mfcc_matrix = np.array([s["mfcc_mean"] for s in segments], dtype="float32")
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    print(f"Number of segments: {len(segments)}")
    print(f"Average segment duration: {avg_duration:.2f}")
    print(f"MFCC-Matrix Shape: {mfcc_matrix.shape}")
    print(f"Example segment JSON: {json.dumps(segments[0], ensure_ascii=False)}")

    assert len(segments) >= 1
    assert mfcc_matrix.ndim == 2
    assert mfcc_matrix.shape[1] == 13
    assert all(d >= 45.0 for d in durations[:-1])
    # Last segment is also expected to satisfy min-duration for this test audio (>45s total).
    assert durations[-1] >= 45.0
