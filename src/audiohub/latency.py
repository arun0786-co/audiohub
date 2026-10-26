"""Latency measurement bookkeeping and compensation maths (Phases 6 and 7).

This module holds no measurement *apparatus* -- it deliberately cannot guess a
latency. It only turns real samples into statistics and statistics into per-sink
delay offsets. If no experiment has been run, every function here will tell you
so rather than inventing a plausible number.

Why the targets below:
  ITU-R BT.1359-1 puts the detectability threshold for audio/video sync at about
  +45 ms when audio leads video and about -125 ms when audio lags. Bluetooth
  audio always lags, so the lag figure is the one that matters for a single
  listener, and players/OSes usually compensate for a *single* known sink.
  What AudioHub adds is the *relative* spread between simultaneous listeners,
  which nothing else compensates for. Two people watching the same screen with
  different headphone delays each get their own A/V error.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

#: Per-listener A/V lag beyond which sync is considered objectionable (ITU-R).
AV_LAG_DETECTABLE_MS = 125.0

#: Target for the spread between sinks in movie mode. Chosen so that aligning
#: sinks costs less added buffer than it saves in A/V error. Revisit this once
#: docs/experiments.md contains real numbers -- it is currently a design target,
#: NOT a measured result.
MOVIE_RELATIVE_OFFSET_TARGET_MS = 40.0


@dataclass
class LatencyMeasurement:
    """Raw samples for one sink, in milliseconds, from a real experiment."""

    sink_id: str
    samples_ms: List[float] = field(default_factory=list)
    method: str = "unspecified"
    notes: str = ""

    def add(self, sample_ms: float) -> None:
        self.samples_ms.append(float(sample_ms))

    @property
    def n(self) -> int:
        return len(self.samples_ms)

    @property
    def mean_ms(self) -> Optional[float]:
        return statistics.fmean(self.samples_ms) if self.samples_ms else None

    @property
    def median_ms(self) -> Optional[float]:
        return statistics.median(self.samples_ms) if self.samples_ms else None

    @property
    def jitter_ms(self) -> Optional[float]:
        """Sample standard deviation. Needs >= 2 samples to mean anything."""
        if len(self.samples_ms) < 2:
            return None
        return statistics.stdev(self.samples_ms)

    @property
    def min_ms(self) -> Optional[float]:
        return min(self.samples_ms) if self.samples_ms else None

    @property
    def max_ms(self) -> Optional[float]:
        return max(self.samples_ms) if self.samples_ms else None

    @property
    def spread_ms(self) -> Optional[float]:
        if not self.samples_ms:
            return None
        return max(self.samples_ms) - min(self.samples_ms)

    def summary(self) -> Dict[str, Optional[float]]:
        return {
            "n": self.n,
            "mean_ms": self.mean_ms,
            "median_ms": self.median_ms,
            "jitter_ms": self.jitter_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
        }


class NoMeasurements(Exception):
    """Raised instead of guessing. See development philosophy: measure first."""


def compute_offsets(
    latencies_ms: Dict[str, float], target_ms: Optional[float] = None
) -> Dict[str, float]:
    """Return the extra delay each sink needs so that all sinks line up.

    We can only ever *add* delay -- no sink can be made to play earlier than its
    hardware allows -- so the alignment target is the slowest sink, and every
    faster sink is padded up to it.

        {"hesh": 180, "crossbeats": 220, "headset_c": 150}
        -> {"hesh": 40.0, "crossbeats": 0.0, "headset_c": 70.0}

    Passing an explicit `target_ms` below the slowest sink is an error, because
    the result would be unachievable and silently wrong.
    """
    if not latencies_ms:
        raise NoMeasurements("no latency measurements supplied")
    slowest = max(latencies_ms.values())
    if target_ms is None:
        target_ms = slowest
    elif target_ms < slowest:
        raise ValueError(
            "target_ms (%.1f) is below the slowest sink (%.1f); "
            "audio cannot be made to arrive earlier" % (target_ms, slowest)
        )
    return {sink_id: float(target_ms - v) for sink_id, v in latencies_ms.items()}


def relative_offsets(latencies_ms: Dict[str, float]) -> Dict[str, float]:
    """Latency of each sink relative to the fastest one."""
    if not latencies_ms:
        raise NoMeasurements("no latency measurements supplied")
    fastest = min(latencies_ms.values())
    return {k: float(v - fastest) for k, v in latencies_ms.items()}


def max_relative_offset(latencies_ms: Dict[str, float]) -> float:
    """The headline number for Phase 6: worst-case spread between listeners."""
    if not latencies_ms:
        raise NoMeasurements("no latency measurements supplied")
    return float(max(latencies_ms.values()) - min(latencies_ms.values()))


def meets_movie_target(
    latencies_ms: Dict[str, float], target_ms: float = MOVIE_RELATIVE_OFFSET_TARGET_MS
) -> bool:
    return max_relative_offset(latencies_ms) <= target_ms


def estimate_drift_ppm(
    offset_start_ms: float, offset_end_ms: float, elapsed_s: float
) -> float:
    """Clock drift in parts per million between two sinks.

    Two Bluetooth sinks run on independent crystals. Even if they start aligned,
    a few ppm of difference accumulates: 10 ppm is 36 ms per hour, which is
    enough to break a film. Measuring drift means measuring the *same* offset
    twice, far apart in time.
    """
    if elapsed_s <= 0:
        raise ValueError("elapsed_s must be positive")
    return ((offset_end_ms - offset_start_ms) / 1000.0) / elapsed_s * 1e6


def drift_ms_per_hour(ppm: float) -> float:
    return ppm * 3600.0 / 1000.0
