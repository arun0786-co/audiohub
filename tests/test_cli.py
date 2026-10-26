"""End-to-end CLI tests. Still no hardware: detect() is swapped for null backends."""

from __future__ import annotations

import json

import pytest

from audiohub import cli
from audiohub import config as cfg


@pytest.fixture(autouse=True)
def null_backends(monkeypatch, audio_backend, bt_backend):
    monkeypatch.setattr(cli, "detect", lambda: (audio_backend, bt_backend))
    return audio_backend, bt_backend


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_doctor_runs_and_reports_capabilities(capsys):
    code, out, _ = run(capsys, "doctor")
    assert code == 0
    assert "AudioHub System Diagnostics" in out
    assert "Capabilities:" in out
    assert "Hesh ANC" in out


def test_doctor_does_not_modify_the_system(capsys, null_backends):
    """Section 8: doctor is purely diagnostic."""
    audio_backend, bt_backend = null_backends
    before = [s.ref for s in audio_backend.list_sinks()]
    connected_before = [d.connected for d in bt_backend.list_devices()]

    run(capsys, "doctor")

    assert [s.ref for s in audio_backend.list_sinks()] == before
    assert [d.connected for d in bt_backend.list_devices()] == connected_before
    assert not cfg.config_path().exists(), "doctor must not write config"


def test_doctor_json_is_machine_readable(capsys):
    code, out, _ = run(capsys, "doctor", "--json")
    assert code == 0
    data = json.loads(out)
    assert "capabilities" in data and "state" in data


def test_devices_lists_bluetooth_and_sinks(capsys):
    code, out, _ = run(capsys, "devices")
    assert code == 0
    assert "Bluetooth devices" in out and "Audio sinks" in out
    assert "A Mouse" not in out, "non-audio devices are not sinks"


def test_route_single_sink(capsys):
    code, out, _ = run(capsys, "route", "default", "hesh")
    assert code == 0
    assert "Hesh" in out
    assert cfg.load().routes == [["default", "hesh"]]


def test_route_multiple_sinks_is_the_phase_4_milestone(capsys, null_backends):
    audio_backend, _ = null_backends
    code, out, _ = run(capsys, "route", "default", "hesh", "cb-evolve")
    assert code == 0
    assert sorted(audio_backend.combine_members("combine.audiohub_combine")) == ["bt1", "bt2"]
    assert sorted(cfg.load().routes) == [["default", "cb-evolve"], ["default", "hesh"]]


def test_route_rejects_unknown_sink_without_changing_anything(capsys):
    code, _, err = run(capsys, "route", "default", "nonexistent")
    assert code == 2
    assert "unknown sink" in err
    assert cfg.load().routes == []


def test_route_rejects_unknown_source(capsys):
    code, _, err = run(capsys, "route", "nosuchsource", "hesh")
    assert code == 2
    assert "unknown source" in err


def test_routes_persist_across_invocations(capsys):
    run(capsys, "route", "default", "hesh", "cb-evolve")
    code, out, _ = run(capsys, "status")
    assert code == 0
    assert "Hesh ANC" in out and "CB-EVOLVE" in out


def test_unroute_removes_routes(capsys):
    run(capsys, "route", "default", "hesh", "cb-evolve")
    code, out, _ = run(capsys, "unroute", "default", "hesh")
    assert code == 0
    assert cfg.load().routes == [["default", "cb-evolve"]]


def test_status_reports_no_measurement_until_one_exists(capsys):
    run(capsys, "route", "default", "hesh", "cb-evolve")
    _, out, _ = run(capsys, "status")
    assert "not measured" in out, "status must never imply unverified sync"


def test_mute_survives_a_restart(capsys):
    run(capsys, "route", "default", "hesh", "cb-evolve")
    run(capsys, "mute", "hesh")
    assert cfg.load().sink("hesh").muted is True
    _, out, _ = run(capsys, "status")
    assert "(muted)" in out
    run(capsys, "unmute", "hesh")
    assert cfg.load().sink("hesh").muted is False


def test_connect_and_disconnect_a_bluetooth_device(capsys):
    code, out, _ = run(capsys, "connect", "hesh")
    assert code == 0 and "connected" in out
    code, out, _ = run(capsys, "disconnect", "hesh")
    assert code == 0 and "disconnected" in out


def test_connect_unknown_device_fails_cleanly(capsys):
    code, _, err = run(capsys, "connect", "not-a-device")
    assert code == 2
    assert "no paired Bluetooth audio device" in err


def test_mode_personal_is_honest_about_what_it_cannot_do(capsys):
    """Section 15: do not fake multi-host support."""
    code, out, _ = run(capsys, "mode", "personal")
    assert code == 0
    assert "Not faking it" in out
    assert cfg.load().mode == "personal"


def test_mode_movie_persists(capsys):
    run(capsys, "mode", "movie")
    assert cfg.load().mode == "movie"
    _, out, _ = run(capsys, "status")
    assert "MODE: MOVIE" in out


def test_a_sink_disappearing_does_not_break_status(capsys, null_backends):
    """The headphone is switched off between runs; status must still work."""
    audio_backend, _ = null_backends
    run(capsys, "route", "default", "hesh", "cb-evolve")
    audio_backend.remove_sink("bt2")

    code, out, _ = run(capsys, "status")
    assert code == 0
    assert "Hesh ANC" in out
    assert "not currently present" in out
    assert cfg.load().sink("cb-evolve") is not None, "config must remember it"


def test_switched_off_sink_keeps_its_route_across_saves(capsys, null_backends):
    """Regression: persisting while a headphone is off must not forget it.

    Switching Crossbeats off and then running any other command used to delete
    its route permanently, so it never came back when it powered on again.
    """
    audio_backend, _ = null_backends
    run(capsys, "route", "default", "hesh", "cb-evolve")
    audio_backend.remove_sink("bt2")          # the headphone is switched off

    run(capsys, "mute", "hesh")               # any command that saves state

    assert sorted(cfg.load().routes) == [["default", "cb-evolve"], ["default", "hesh"]]


def test_route_returns_when_the_sink_powers_back_on(capsys, null_backends):
    from audiohub.backends.base import BackendSink

    audio_backend, _ = null_backends
    run(capsys, "route", "default", "hesh", "cb-evolve")
    audio_backend.remove_sink("bt2")
    run(capsys, "mute", "hesh")
    audio_backend.add_sink(BackendSink(ref="bt2", name="CB-EVOLVE", kind="bluetooth"))

    _, out, _ = run(capsys, "status")
    assert "not currently present" not in out
    assert "CB-EVOLVE" in out


def test_an_absent_sink_can_still_be_unrouted(capsys, null_backends):
    """Preserving routes must not make them impossible to delete."""
    audio_backend, _ = null_backends
    run(capsys, "route", "default", "hesh", "cb-evolve")
    audio_backend.remove_sink("bt2")

    code, out, _ = run(capsys, "unroute", "default", "cb-evolve")
    assert code == 0 and "removed 1" in out
    assert cfg.load().routes == [["default", "hesh"]]


def test_unroute_all_clears_absent_routes_too(capsys, null_backends):
    audio_backend, _ = null_backends
    run(capsys, "route", "default", "hesh", "cb-evolve")
    audio_backend.remove_sink("bt2")
    code, out, _ = run(capsys, "unroute", "default")
    assert code == 0 and "removed 2" in out
    assert cfg.load().routes == []
