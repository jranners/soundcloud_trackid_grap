import os
import subprocess

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.config import settings

logger = get_task_logger(__name__)

SNIPPET_DURATION = 12  # seconds
OFFSET_AFTER_TRANSITION = 30  # seconds


@celery_app.task(
    name="app.tasks.analysis.segment_audio",
    queue="analysis",
    bind=True,
    max_retries=2,
)
def segment_audio(self, download_result: dict) -> dict:
    tracklist_id = download_result["tracklist_id"]
    audio_path = download_result["audio_path"]
    segments = []

    try:
        import essentia.standard as es

        loader = es.MonoLoader(filename=audio_path, sampleRate=44100)
        audio = loader()

        sample_rate = 44100
        transitions = _detect_transitions_sbic(audio, sample_rate)

        if not transitions:
            logger.warning("No transitions found, using onset fallback for %s", tracklist_id)
            transitions = _detect_transitions_fallback(audio, sample_rate)

        for ts in transitions:
            snippet_start = ts + OFFSET_AFTER_TRANSITION
            snippet_path = os.path.join(
                settings.RAMDISK_PATH,
                f"{tracklist_id}_snippet_{int(snippet_start)}.wav",
            )
            success = _extract_snippet(audio_path, snippet_start, SNIPPET_DURATION, snippet_path)
            if success:
                segments.append({"path": snippet_path, "timestamp": ts})

        logger.info("Extracted %d segments for %s", len(segments), tracklist_id)
        return {"tracklist_id": tracklist_id, "segments": segments}

    except Exception as exc:
        logger.error("Analysis failed for %s: %s", tracklist_id, exc)
        for seg in segments:
            if os.path.exists(seg["path"]):
                os.remove(seg["path"])
        raise self.retry(exc=exc, countdown=15)

    finally:
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)


def _detect_transitions_sbic(audio, sample_rate: int) -> list:
    import essentia.standard as es

    frame_size = 2048
    hop_size = 1024
    sbic = es.SBic(
        cpw=1.5,
        increase=1.25,
        minSegLen=10,
        size1=1000,
        size2=500,
    )

    pool = es.Pool()
    run_extractor = es.Extractor()

    mfcc_extractor = es.MFCC()
    w = es.Windowing(type="hann")
    spec = es.Spectrum()
    frames_gen = es.FrameGenerator(audio, frameSize=frame_size, hopSize=hop_size)

    features = []
    for frame in frames_gen:
        windowed = w(frame)
        spectrum = spec(windowed)
        _, mfcc_coeffs = mfcc_extractor(spectrum)
        features.append(mfcc_coeffs)

    if not features:
        return []

    import numpy as np

    feature_array = np.array(features, dtype="float32")
    boundaries = sbic(feature_array)

    hop_duration = hop_size / sample_rate
    transitions = sorted({float(b) * hop_duration for b in boundaries if b * hop_duration > 30})
    return transitions


def _detect_transitions_fallback(audio, sample_rate: int) -> list:
    import essentia.standard as es
    import numpy as np

    try:
        beat_tracker = es.BeatTrackerMultiFeature()
        beats, _ = beat_tracker(audio)
        if len(beats) > 4:
            beats_arr = np.array(beats)
            diffs = np.diff(beats_arr)
            mean_diff = np.mean(diffs)
            std_diff = np.std(diffs)
            change_indices = np.where(np.abs(diffs - mean_diff) > 2 * std_diff)[0]
            transitions = [float(beats_arr[i]) for i in change_indices if beats_arr[i] > 30]
            if transitions:
                return transitions
    except Exception:
        pass

    onset_detection = es.OnsetDetection(method="hfc")
    w = es.Windowing(type="hann")
    fft = es.FFT()
    c2p = es.CartesianToPolar()

    onsets_values = []
    for frame in es.FrameGenerator(audio, frameSize=1024, hopSize=512):
        cart = fft(w(frame))
        mag, phase = c2p(cart)
        onsets_values.append(onset_detection(mag, phase))

    hop_duration = 512 / sample_rate
    onset_times = [i * hop_duration for i, v in enumerate(onsets_values) if v > 0.5 and i * hop_duration > 30]

    seen = []
    for t in onset_times:
        if not seen or t - seen[-1] > 60:
            seen.append(t)
    return seen


def _extract_snippet(source_path: str, start: float, duration: float, output_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", source_path,
        "-t", str(duration),
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        return result.returncode == 0 and os.path.exists(output_path)
    except Exception as exc:
        logger.error("ffmpeg failed: %s", exc)
        return False
