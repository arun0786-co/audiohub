from __future__ import annotations

import pytest

from audiohub.latency import (
    LatencyMeasurement,
    NoMeasurements,
    compute_offsets,
    drift_ms_per_hour,
    estimate_drift_ppm,
    max_relative_offset,
    meets_movie_target,
    relative_offsets,
)


def test_compute_offsets_matches_the_worked_example():
    """The example from the project brief, section 14."""
    offsets = compute_offsets({"hesh": 180, "crossbeats": 220, "headset_c": 150})
    assert offsets == {"hesh": 40.0, "crossbeats": 0.0, "headset_c": 70.0}


def test_offsets_align_every_sink_to_the_same_arrival_time():
    latencies = {"a": 100, "b": 175, "c": 210}
    offsets = compute_offsets(latencies)
    aligned = {k: latencies[k] + offsets[k] for k in latencies}
    assert len(set(aligned.values())) == 1


def test_offsets_are_never_negative():
    """We can delay audio. We cannot make it arrive earlier."""
    for v in compute_offsets({"a": 10, "b": 400, "c": 55}).values():
        assert v >= 0


def test_target_below_slowest_sink_is_rejected():
    with pytest.raises(ValueError):
        compute_offsets({"a": 100, "b": 250}, target_ms=200)


def test_explicit_target_above_slowest_is_allowed():
    offsets = compute_offsets({"a": 100, "b": 250}, target_ms=300)
    assert offsets == {"a": 200.0, "b": 50.0}


def test_empty_measurements_raise_rather_than_guess():
    """Measure first. Never substitute an assumption for a measurement."""
    for fn in (compute_offsets, relative_offsets, max_relative_offset):
        with pytest.raises(NoMeasurements):
            fn({})


def test_max_relative_offset_and_movie_target():
    assert max_relative_offset({"a": 180, "b": 220}) == 40.0
    assert meets_movie_target({"a": 180, "b": 200}) is True
    assert meets_movie_target({"a": 100, "b": 300}) is False


def test_measurement_statistics():
    m = LatencyMeasurement(sink_id="hesh", method="loopback")
    for s in (180.0, 184.0, 176.0, 182.0):
        m.add(s)
    assert m.n == 4
    assert m.mean_ms == pytest.approx(180.5)
    assert m.jitter_ms == pytest.approx(3.4157, rel=1e-3)
    assert m.spread_ms == 8.0


def test_statistics_are_none_without_enough_samples():
    """An unmeasured sink reports None, never a plausible-looking zero."""
    empty = LatencyMeasurement(sink_id="hesh")
    assert empty.mean_ms is None and empty.jitter_ms is None

    one = LatencyMeasurement(sink_id="hesh", samples_ms=[180.0])
    assert one.mean_ms == 180.0
    assert one.jitter_ms is None, "one sample cannot express jitter"


def test_drift_estimation():
    # 36 ms of extra skew accumulated over one hour == 10 ppm.
    ppm = estimate_drift_ppm(offset_start_ms=0.0, offset_end_ms=36.0, elapsed_s=3600)
    assert ppm == pytest.approx(10.0)
    assert drift_ms_per_hour(ppm) == pytest.approx(36.0)


def test_drift_requires_positive_elapsed_time():
    with pytest.raises(ValueError):
        estimate_drift_ppm(0.0, 10.0, 0)
