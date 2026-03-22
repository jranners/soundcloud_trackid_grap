import os
import subprocess
import glob

from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.config import settings
from app.tasks.progress import set_tracklist_progress

logger = get_task_logger(__name__)

SNIPPET_DURATION = 12  # seconds
OFFSET_AFTER_TRANSITION = 30  # seconds
DJ_MIN_TRACK_GAP = 75  # seconds
DJ_IDEAL_TRACK_GAP = 105  # seconds
DJ_MAX_TRACK_GAP = 150  # seconds


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
        set_tracklist_progress(
            tracklist_id,
            status="segmenting",
            progress_percent=30,
            progress_message="Loading audio for segmentation",
        )
        if not os.path.exists(audio_path):
            # Defensive recovery for stale path values: locate current downloaded file by tracklist id.
            pattern = os.path.join(settings.RAMDISK_PATH, f"{tracklist_id}.*")
            matches = glob.glob(pattern)
            if matches:
                audio_path = matches[0]
                logger.warning("Recovered missing audio path for %s: %s", tracklist_id, audio_path)
            else:
                raise FileNotFoundError(f"Audio file missing for tracklist {tracklist_id}: {audio_path}")

        import essentia.standard as es

        loader = es.MonoLoader(filename=audio_path, sampleRate=44100)
        audio = loader()

        sample_rate = 44100
        transitions = _detect_transitions_sbic(audio, sample_rate)

        if not transitions:
            logger.warning("No transitions found, using onset fallback for %s", tracklist_id)
            set_tracklist_progress(
                tracklist_id,
                progress_percent=40,
                progress_message="No clear transitions, running fallback detector",
            )
            transitions = _detect_transitions_fallback(audio, sample_rate)

        transitions = _enforce_dj_track_spacing(transitions)

        total_transitions = len(transitions)
        set_tracklist_progress(
            tracklist_id,
            total_segments=total_transitions,
            processed_segments=0,
            progress_percent=45,
            progress_message=f"Found {total_transitions} transitions",
        )

        for idx, ts in enumerate(transitions, start=1):
            candidates = []
            for offset in [OFFSET_AFTER_TRANSITION, OFFSET_AFTER_TRANSITION + 15, OFFSET_AFTER_TRANSITION - 15]:
                snippet_start = ts + offset
                if snippet_start < 0:
                    continue
                snippet_path = os.path.join(
                    settings.RAMDISK_PATH,
                    f"{tracklist_id}_snippet_{int(ts)}_{offset}.wav",
                )
                success = _extract_snippet(audio_path, snippet_start, SNIPPET_DURATION, snippet_path)
                if success:
                    candidates.append({"path": snippet_path, "offset": offset})
            
            if candidates:
                segments.append({"candidates": candidates, "timestamp": ts})
                
            extraction_ratio = (idx / total_transitions) if total_transitions else 1.0
            set_tracklist_progress(
                tracklist_id,
                processed_segments=idx,
                progress_percent=45 + (extraction_ratio * 20),
                progress_message=f"Extracting snippets {idx}/{total_transitions}",
            )

        logger.info("Extracted %d segments for %s", len(segments), tracklist_id)
        set_tracklist_progress(
            tracklist_id,
            progress_percent=65,
            progress_message=f"Segmentation completed ({len(segments)} snippets)",
        )
        if audio_path and os.path.exists(audio_path):
            os.remove(audio_path)
        return {"tracklist_id": tracklist_id, "segments": segments}

    except Exception as exc:
        logger.error("Analysis failed for %s: %s", tracklist_id, exc)
        if self.request.retries >= self.max_retries:
            set_tracklist_progress(
                tracklist_id,
                status="failed",
                progress_percent=100,
                progress_message=f"Analysis failed: {exc}",
            )
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
        for seg in segments:
            for candidate in seg.get("candidates", []):
                cp = candidate.get("path")
                if cp and os.path.exists(cp):
                    os.remove(cp)
        raise self.retry(exc=exc, countdown=15)


def _detect_transitions_sbic(audio, sample_rate: int) -> list:
    import essentia.standard as es

    frame_size = 2048
    hop_size = 1024
    sbic = es.SBic(
        cpw=1.5,
        inc1=60,
        inc2=20,
        minLength=10,
        size1=300,
        size2=200,
    )

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


def _enforce_dj_track_spacing(transitions: list[float]) -> list[float]:
    if not transitions:
        return []

    sorted_transitions = sorted(set(float(t) for t in transitions))
    selected = [sorted_transitions[0]]
    remaining = sorted_transitions[1:]

    while remaining:
        last = selected[-1]
        in_window = [
            t for t in remaining if DJ_MIN_TRACK_GAP <= (t - last) <= DJ_MAX_TRACK_GAP
        ]
        if in_window:
            best = min(in_window, key=lambda t: abs((t - last) - DJ_IDEAL_TRACK_GAP))
        else:
            far_candidates = [t for t in remaining if (t - last) > DJ_MAX_TRACK_GAP]
            if not far_candidates:
                break
            best = far_candidates[0]
        selected.append(best)
        remaining = [t for t in remaining if t > best]

    return selected
