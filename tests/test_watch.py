"""phase 5 monitor: a headphone drops out and comes back, routes follow it."""

from __future__ import annotations

import pytest

from audiohub import cli, watch
from audiohub.backends.base import BackendSink


@pytest.fixture
def hub(monkeypatch, audio_backend, bt_backend):
    monkeypatch.setattr(cli, "detect", lambda: (audio_backend, bt_backend))
    assert cli.main(["route", "default", "hesh", "cb-evolve"]) in (0, 3)
    return cli.Hub()


def test_nothing_happens_when_all_is_fine(hub):
    st = watch.new_state()
    assert watch.step(hub, st, now=0) == []
    assert st["lost"] == {}


def test_lost_then_reconnect_then_back(hub, audio_backend, bt_backend):
    st = watch.new_state()
    watch.step(hub, st, now=0)

    audio_backend.remove_sink("bt2")  # crossbeats switched off
    events = watch.step(hub, st, now=1)
    assert any("lost cb-evolve" in e for e in events)
    assert "cb-evolve" in st["lost"]

    # too early for a reconnect try
    assert not any("reconnect" in e for e in watch.step(hub, st, now=3))

    events = watch.step(hub, st, now=1 + watch.BACKOFF[0])
    assert any("reconnected cb-evolve" in e for e in events)
    assert [d for d in bt_backend.list_devices() if d.address.endswith("02")][0].connected

    # the os shows the audio output again
    audio_backend.add_sink(BackendSink(ref="bt2", name="CB-EVOLVE", kind="bluetooth", address="AA:BB:CC:DD:EE:02"))
    events = watch.step(hub, st, now=20)
    assert any("cb-evolve is back" in e for e in events)
    assert any(e.startswith("applied") or "could not apply" in e for e in events)
    assert st["lost"] == {}
    assert hub.engine.is_connected("default", "cb-evolve")


def test_failed_reconnect_waits_longer_each_time(hub, audio_backend, monkeypatch):
    st = watch.new_state()
    audio_backend.remove_sink("bt1")
    monkeypatch.setattr(hub.bluetooth.backend, "connect", lambda address: False)
    watch.step(hub, st, now=0)
    t = watch.BACKOFF[0]
    waits = []
    for _ in range(3):
        events = watch.step(hub, st, now=t)
        assert any("failed" in e for e in events)
        waits.append(st["next_try"]["hesh"] - t)
        t = st["next_try"]["hesh"]
    assert waits == watch.BACKOFF[1:4]


def test_route_is_never_forgotten(hub, audio_backend):
    from audiohub import config as cfg

    st = watch.new_state()
    audio_backend.remove_sink("bt1")
    for t in range(0, 200, 5):
        watch.step(hub, st, now=t)
    assert ["default", "hesh"] in cfg.load().routes


def test_watch_once_from_cli(monkeypatch, audio_backend, bt_backend, capsys):
    monkeypatch.setattr(cli, "detect", lambda: (audio_backend, bt_backend))
    cli.main(["route", "default", "hesh"])
    audio_backend.remove_sink("bt1")
    assert cli.main(["watch", "--once"]) == 0
    assert "lost hesh" in capsys.readouterr().out


def test_bluetooth_address_is_saved(hub):
    # regression: the address never reached the config, so reconnect could not work
    from audiohub import config as cfg

    assert cfg.load().sink("hesh").address == "AA:BB:CC:DD:EE:01"
