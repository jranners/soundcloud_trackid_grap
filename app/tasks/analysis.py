import os
import subprocess
import glob
from dataclasses import dataclass
from typing import Optional

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
MIN_SEGMENT_DURATION = 45.0  # seconds


@dataclass
class SegmentFeatures:
    segment_index: int
    start_time: float
    end_time: float
    duration: float
    mean_loudness: float
    mfcc_mean: list[float]
    chroma_mean: Optional[list[float]] = None
    candidates: Optional[list[dict]] = None

    def to_payload(self) -> dict:
        return {
            "segment_index": self.segment_index,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "mean_loudness": self.mean_loudness,
            "mfcc_mean": self.mfcc_mean,
            "chroma_mean": self.chroma_mean,
            # Keep legacy keys for downstream compatibility.
            "timestamp": self.start_time,
            "candidates": self.candidates or [],
        }


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
        audio_duration = float(len(audio) / sample_rate)
        segment_ranges = _build_segment_ranges(
            transitions=transitions,
            audio_duration=audio_duration,
            min_duration=MIN_SEGMENT_DURATION,
        )

        total_transitions = len(segment_ranges)
        set_tracklist_progress(
            tracklist_id,
            total_segments=total_transitions,
            processed_segments=0,
            progress_percent=45,
            progress_message=f"Found {total_transitions} segments",
        )

        for idx, (start_time, end_time) in enumerate(segment_ranges, start=1):
            segment_audio_slice = _slice_audio(audio, sample_rate, start_time, end_time)
            segment_features = _compute_segment_features(
                segment_index=idx - 1,
                segment_audio=segment_audio_slice,
                sample_rate=sample_rate,
                start_time=start_time,
                end_time=end_time,
            )
            candidates = []
            for offset in [OFFSET_AFTER_TRANSITION, OFFSET_AFTER_TRANSITION + 15, OFFSET_AFTER_TRANSITION - 15]:
                snippet_start = start_time + offset
                if snippet_start < 0:
                    continue
                snippet_path = os.path.join(
                    settings.RAMDISK_PATH,
                    f"{tracklist_id}_snippet_{int(start_time)}_{offset}.wav",
                )
                success = _extract_snippet(audio_path, snippet_start, SNIPPET_DURATION, snippet_path)
                if success:
                    candidates.append({"path": snippet_path, "offset": offset})
            segment_features.candidates = candidates
            segments.append(segment_features.to_payload())
                
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


def _build_segment_ranges(transitions: list[float], audio_duration: float, min_duration: float = MIN_SEGMENT_DURATION) -> list[tuple[float, float]]:
    """Build contiguous [start, end) ranges and enforce minimum duration by merging."""
    cleaned = sorted(
        {
            float(t)
            for t in transitions
            if 0.0 < float(t) < audio_duration
        }
    )
    boundaries = [0.0] + cleaned + [audio_duration]
    segments = []
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        if end > start:
            segments.append((float(start), float(end)))
    return merge_short_segments(segments, min_duration=min_duration)


def merge_short_segments(segments: list[tuple[float, float]], min_duration: float = MIN_SEGMENT_DURATION) -> list[tuple[float, float]]:
    """Merge short segments (<min_duration) with neighbors.

    Rules:
    - First short segment merges into the next segment.
    - Last short segment merges into the previous segment.
    - Middle short segment merges with the longer neighboring segment.
    """
    if len(segments) <= 1:
        return segments

    merged = [tuple(s) for s in segments]
    idx = 0
    while idx < len(merged):
        start, end = merged[idx]
        duration = end - start
        if duration >= min_duration:
            idx += 1
            continue

        if idx == 0 and len(merged) > 1:
            next_start, next_end = merged[idx + 1]
            merged[idx + 1] = (start, next_end)
            del merged[idx]
            continue

        if idx == len(merged) - 1 and idx > 0:
            prev_start, _prev_end = merged[idx - 1]
            merged[idx - 1] = (prev_start, end)
            del merged[idx]
            # Re-check the merged previous segment because cascading merges can still
            # violate min_duration when multiple adjacent short segments exist.
            idx = max(0, idx - 1)
            continue

        left_duration = merged[idx - 1][1] - merged[idx - 1][0]
        right_duration = merged[idx + 1][1] - merged[idx + 1][0]
        # Tie-breaker prefers the left neighbor to keep boundary movement monotonic
        # and deterministic across repeated runs.
        if left_duration >= right_duration:
            prev_start, _prev_end = merged[idx - 1]
            merged[idx - 1] = (prev_start, end)
            del merged[idx]
            # Re-check the merged segment to handle chains of short neighbors.
            idx = max(0, idx - 1)
        else:
            _next_start, next_end = merged[idx + 1]
            merged[idx + 1] = (start, next_end)
            del merged[idx]
    return merged


def _slice_audio(audio, sample_rate: int, start_time: float, end_time: float):
    start_idx = max(0, int(start_time * sample_rate))
    end_idx = min(len(audio), int(end_time * sample_rate))
    return audio[start_idx:end_idx]


def _compute_segment_features(
    segment_index: int,
    segment_audio,
    sample_rate: int,
    start_time: float,
    end_time: float,
) -> SegmentFeatures:
    import numpy as np

    duration = max(0.0, float(end_time - start_time))
    if segment_audio is None or len(segment_audio) == 0:
        return SegmentFeatures(
            segment_index=segment_index,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            mean_loudness=0.0,
            mfcc_mean=[0.0] * 13,
            chroma_mean=None,
        )

    audio_np = np.asarray(segment_audio, dtype="float32")
    mean_loudness = float(np.sqrt(np.mean(np.square(audio_np))))
    mfcc_mean = _compute_mfcc_mean(audio_np)
    chroma_mean = _compute_chroma_mean(audio_np, sample_rate)
    return SegmentFeatures(
        segment_index=segment_index,
        start_time=start_time,
        end_time=end_time,
        duration=duration,
        mean_loudness=mean_loudness,
        mfcc_mean=mfcc_mean,
        chroma_mean=chroma_mean,
    )


def _compute_mfcc_mean(audio):
    import numpy as np
    import essentia.standard as es

    w = es.Windowing(type="hann")
    spec = es.Spectrum()
    mfcc = es.MFCC()
    coeffs = []
    for frame in es.FrameGenerator(audio, frameSize=2048, hopSize=1024):
        spectrum = spec(w(frame))
        _, mfcc_coeffs = mfcc(spectrum)
        coeffs.append(np.asarray(mfcc_coeffs, dtype="float32"))

    if not coeffs:
        return [0.0] * 13
    return np.mean(np.stack(coeffs), axis=0).astype("float32").tolist()


def _compute_chroma_mean(audio, sample_rate: int):
    try:
        import librosa
        import numpy as np
    except Exception:
        return None

    try:
        chroma = librosa.feature.chroma_stft(y=audio, sr=sample_rate)
        if chroma.size == 0:
            return None
        return np.mean(chroma, axis=1).astype("float32").tolist()
    except Exception:
        return None
