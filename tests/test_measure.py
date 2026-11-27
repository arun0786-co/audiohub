"""phase 6 tool: made up recordings with a known offset must give it back."""

from __future__ import annotations

import math
import random
import wave
from array import array

import pytest

from audiohub import cli, measure


def record(path, offset_ms, rate=48000, clicks=8, noise=0.02, right_gain=0.3, drift=0.0, channels=1, echo=0.0):
    """like a phone recording: both cups in one channel plus hiss"""
    rnd = random.Random(1)
    total = int(rate * (clicks * measure.PERIOD_S + 1))
    x = [rnd.gauss(0, noise) for _ in range(total)]
    n = int(measure.CLICK_S * rate)

    def add(at, hz, gain):
        s = round(at * rate)
        for i in range(n):
            if s + i < total:
                x[s + i] += gain * math.sin(2 * math.pi * hz * i / rate)

    for k in range(clicks):
        t = 0.7 + k * measure.PERIOD_S
        add(t, measure.LEFT_HZ, 0.4)
        add(t + echo, measure.LEFT_HZ, 0.2 if echo else 0)
        add(t + offset_ms / 1000 + drift * k, measure.RIGHT_HZ, right_gain)
    pcm = array("h")
    for v in x:
        pcm.extend([int(max(-1, min(1, v)) * 32767)] * channels)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return str(path)


@pytest.mark.parametrize("offset", [0, 3, 40, -40, 180, -350])
def test_known_offset_comes_back(tmp_path, offset):
    r = measure.analyze(record(tmp_path / "r.wav", offset))
    assert r["n"] == 8
    assert r["median_ms"] == pytest.approx(offset, abs=0.5)
    assert r["jitter_ms"] < 0.5


@pytest.mark.parametrize("rate, channels", [(44100, 1), (48000, 2), (16000, 1)])
def test_other_formats(tmp_path, rate, channels):
    r = measure.analyze(record(tmp_path / "r.wav", 60, rate=rate, channels=channels))
    assert r["median_ms"] == pytest.approx(60, abs=0.5)


def test_one_side_quieter_and_an_echo(tmp_path):
    r = measure.analyze(record(tmp_path / "r.wav", 25, right_gain=0.1, echo=0.03))
    assert r["median_ms"] == pytest.approx(25, abs=0.5)


def test_signal_itself_has_no_offset(tmp_path):
    p = str(tmp_path / "s.wav")
    assert measure.write_signal(p, 20) == 10
    r = measure.analyze(p)
    assert r["n"] == 10 and abs(r["median_ms"]) < 0.5


def test_short_recording_gives_no_drift(tmp_path):
    assert measure.analyze(record(tmp_path / "r.wav", 10, drift=0.001))["drift_ppm"] is None


def test_drift_slope():
    pairs = [(t, 5 + 0.02 * t) for t in range(0, 600, 2)]  # 20 us per second
    assert measure.drift_ppm(pairs) == pytest.approx(20)


def test_noise_is_not_a_measurement(tmp_path):
    with pytest.raises(measure.MeasureError, match="left clicks"):
        measure.analyze(record(tmp_path / "r.wav", 0, clicks=0))


def test_one_headphone_silent(tmp_path):
    with pytest.raises(measure.MeasureError, match="right clicks"):
        measure.analyze(record(tmp_path / "r.wav", 0, right_gain=0))


def test_wrong_spacing_is_refused(tmp_path, monkeypatch):
    p = record(tmp_path / "r.wav", 10)
    monkeypatch.setattr(measure, "PERIOD_S", 1.5)
    with pytest.raises(measure.MeasureError, match="apart"):
        measure.analyze(p)


def test_not_a_wav(tmp_path):
    p = tmp_path / "x.m4a"
    p.write_bytes(b"hello")
    with pytest.raises(measure.MeasureError, match="ffmpeg"):
        measure.analyze(str(p))


def test_cli(tmp_path, capsys):
    assert cli.main(["measure", "signal", str(tmp_path / "s.wav"), "--seconds", "12"]) == 0
    p = record(tmp_path / "r.wav", 55)
    assert cli.main(["measure", "analyze", p, "--left", "hesh", "--right", "cb-evolve"]) == 0
    out = capsys.readouterr().out
    assert "cb-evolve is 55." in out or "cb-evolve is 54." in out
    assert "OVER" in out and "drift: not measured" in out
    assert cli.main(["measure", "analyze", str(tmp_path / "nope.wav")]) == 2
