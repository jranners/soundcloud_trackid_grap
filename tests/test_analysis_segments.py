from app.tasks.analysis import MIN_SEGMENT_DURATION, _build_segment_ranges, merge_short_segments


def test_merge_short_segments_handles_start_middle_end_and_consecutive_short_segments():
    segments = [
        (0.0, 10.0),   # short start
        (10.0, 20.0),  # short (consecutive)
        (20.0, 80.0),  # long
        (80.0, 90.0),  # short middle
        (90.0, 100.0),  # short end
    ]

    merged = merge_short_segments(segments, min_duration=MIN_SEGMENT_DURATION)

    assert merged == [(0.0, 100.0)]
    assert all((end - start) >= MIN_SEGMENT_DURATION for start, end in merged)


def test_merge_short_segments_no_short_segments_remain_unless_total_mix_too_short():
    merged = merge_short_segments(
        [(0.0, 15.0), (15.0, 30.0), (30.0, 120.0)],
        min_duration=MIN_SEGMENT_DURATION,
    )
    assert all((end - start) >= MIN_SEGMENT_DURATION for start, end in merged)

    # If the whole mix is shorter than minimum duration, one short segment is expected.
    short_mix = merge_short_segments([(0.0, 30.0)], min_duration=MIN_SEGMENT_DURATION)
    assert short_mix == [(0.0, 30.0)]
    assert (short_mix[0][1] - short_mix[0][0]) < MIN_SEGMENT_DURATION


def test_build_segment_ranges_inserts_start_end_ignores_invalid_transitions_and_is_gapless():
    transitions = [90.0, -5.0, 30.0, 200.0, 120.0, 0.0, 120.0]
    audio_duration = 180.0

    ranges = _build_segment_ranges(transitions, audio_duration, min_duration=0.0)

    assert ranges == [(0.0, 30.0), (30.0, 90.0), (90.0, 120.0), (120.0, 180.0)]
    assert ranges[0][0] == 0.0
    assert ranges[-1][1] == audio_duration
    assert all(prev_end == next_start for (_, prev_end), (next_start, _) in zip(ranges, ranges[1:]))
