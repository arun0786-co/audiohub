"""measure - how far apart are two headphones? (the phase 6 experiment)

the click track has one tone on the left and another on the right. put the LEFT
cup of headphone A and the RIGHT cup of headphone B next to one phone and record.
the tones tell us which click came from which headphone, so one mono recording
gives the offset and also who is late.

only the standard library, so finding the clicks is done by hand:
multiply by the tone, sum over the length of one click, look for peaks.
"""

from __future__ import annotations

import math
import statistics
import sys
import wave
from array import array
from itertools import accumulate
from typing import Dict, List, Optional, Sequence, Tuple

from .latency import LatencyMeasurement

LEFT_HZ = 2000
RIGHT_HZ = 5000
CLICK_S = 0.010
PERIOD_S = 2.0  # offsets up to half of this can be told apart
HOP_S = 0.0002  # how fine we look for the peak
MIN_PAIRS = 5
MIN_PEAK_OVER_NOISE = 8.0
MIN_DRIFT_S = 300.0  # shorter recordings cant say anything about drift


class MeasureError(Exception):
    """the recording cannot give an honest answer"""


def write_signal(path: str, seconds: float = 60.0, rate: int = 48000) -> int:
    """write the stereo click track, returns how many clicks are in it"""
    clicks = int(seconds // PERIOD_S)
    if clicks < MIN_PAIRS:
        raise MeasureError(f"need at least {MIN_PAIRS * PERIOD_S:g} seconds")
    n = int(CLICK_S * rate)
    # the click starts 0.5 s in, so nothing is lost when playback starts
    start = rate // 2
    period = array("h", bytes(int(PERIOD_S * rate) * 4))
    for i in range(n):
        for ch, hz in enumerate((LEFT_HZ, RIGHT_HZ)):
            value = 0.6 * math.sin(2 * math.pi * hz * i / rate)
            period[2 * (start + i) + ch] = int(32767 * value)
    if sys.byteorder == "big":
        period.byteswap()
    data = period.tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        for _ in range(clicks):
            w.writeframes(data)
    return clicks


def read_mono(path: str) -> Tuple[List[float], int]:
    try:
        with wave.open(path, "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise MeasureError(f"cannot read {path} as wav ({exc}). try: ffmpeg -i {path} -c:a pcm_s16le out.wav")
    except OSError as exc:
        raise MeasureError(f"cannot open {path}: {exc.strerror}")
    if width != 2:
        raise MeasureError(f"need 16 bit wav, this is {8 * width} bit. try: ffmpeg -i {path} -c:a pcm_s16le out.wav")
    if rate < 3 * RIGHT_HZ:
        raise MeasureError(f"sample rate {rate} is too low for the {RIGHT_HZ} Hz click, record at 44100 or 48000")
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    if channels == 1:
        return [float(s) for s in samples], rate
    return [sum(samples[i:i + channels]) / channels for i in range(0, len(samples), channels)], rate


def _envelope(x: Sequence[float], rate: int, hz: int, hop: int) -> List[float]:
    """how strongly a click of this tone starts at each hop"""
    size = rate // math.gcd(rate, hz)
    cos = [math.cos(2 * math.pi * hz * i / rate) for i in range(size)]
    sin = [math.sin(2 * math.pi * hz * i / rate) for i in range(size)]
    re = list(accumulate((v * cos[i % size] for i, v in enumerate(x)), initial=0.0))
    im = list(accumulate((v * sin[i % size] for i, v in enumerate(x)), initial=0.0))
    n = int(CLICK_S * rate)
    return [math.hypot(re[t + n] - re[t], im[t + n] - im[t]) for t in range(0, len(x) - n, hop)]


def find_clicks(x: Sequence[float], rate: int, hz: int) -> List[float]:
    """start times of the clicks of one tone, in seconds"""
    hop = max(1, int(HOP_S * rate))
    env = _envelope(x, rate, hz, hop)
    if not env:
        return []
    top, noise = max(env), statistics.median(env)
    if top <= 0 or top < MIN_PEAK_OVER_NOISE * noise:
        return []
    gap = int(PERIOD_S / 2 * rate / hop)
    times: List[float] = []
    i = 0
    while i < len(env):
        if env[i] < 0.4 * top:
            i += 1
            continue
        # the peak is within one click length of where it first got loud
        end = min(len(env), i + int(2 * CLICK_S * rate / hop))
        best = max(range(i, end), key=env.__getitem__)
        times.append(best * hop / rate)
        i = best + gap
    return times


def pair_offsets(left: Sequence[float], right: Sequence[float]) -> List[Tuple[float, float]]:
    """(time, right minus left in ms) for each left click with a right click near it"""
    pairs = []
    for t in left:
        near = min(right, key=lambda r: abs(r - t), default=None)
        if near is not None and abs(near - t) < PERIOD_S / 2:
            pairs.append((t, (near - t) * 1000.0))
    return pairs


def drift_ppm(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    """slope of the offset over time, None if the recording is too short"""
    if len(pairs) < 2 or pairs[-1][0] - pairs[0][0] < MIN_DRIFT_S:
        return None
    mt = statistics.fmean(t for t, _ in pairs)
    mo = statistics.fmean(o for _, o in pairs)
    top = sum((t - mt) * (o - mo) for t, o in pairs)
    return top / sum((t - mt) ** 2 for t, _ in pairs) * 1000.0  # ms per s -> ppm


def analyze(path: str) -> Dict[str, object]:
    """offset of the right headphone against the left one, positive = right is late"""
    x, rate = read_mono(path)
    left = find_clicks(x, rate, LEFT_HZ)
    right = find_clicks(x, rate, RIGHT_HZ)
    for name, clicks in (("left", left), ("right", right)):
        if len(clicks) < MIN_PAIRS:
            raise MeasureError(f"found {len(clicks)} {name} clicks, need {MIN_PAIRS}. record longer or move the phone closer")
    # clicks we found must really come every PERIOD_S, otherwise its some other sound
    for name, clicks in (("left", left), ("right", right)):
        gaps = [b - a for a, b in zip(clicks, clicks[1:])]
        if abs(statistics.median(gaps) - PERIOD_S) > 0.05:
            raise MeasureError(f"the {name} clicks are not {PERIOD_S:g}s apart, is this a recording of the click track?")
    pairs = pair_offsets(left, right)
    if len(pairs) < MIN_PAIRS:
        raise MeasureError(f"only {len(pairs)} clicks could be paired, need {MIN_PAIRS}")
    m = LatencyMeasurement("right-left", [o for _, o in pairs], method="two tone click recording")
    return {**m.summary(), "seconds": pairs[-1][0] - pairs[0][0], "drift_ppm": drift_ppm(pairs)}
