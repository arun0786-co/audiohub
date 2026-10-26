"""Service-layer tests against the null backend -- still no hardware."""

from __future__ import annotations

import pytest

from audiohub.audio import AudioService
from audiohub.backends.base import Capability, NotSupported
from audiohub.bluetooth import BluetoothService
from audiohub.devices import DeviceRegistry
from audiohub.routing import EndpointKind, RoutingEngine
from audiohub.state import DeviceState


def test_populate_discovers_sinks_without_hardcoding_anything(audio_backend):
    engine = AudioService(audio_backend).populate(RoutingEngine(), DeviceRegistry())
    assert {s.id for s in engine.sinks()} == {"hesh", "cb-evolve", "speakers"}
    assert engine.get_sink("hesh").kind is EndpointKind.BLUETOOTH
    assert engine.get_sink("speakers").kind is EndpointKind.ALSA
    assert [s.id for s in engine.sources()] == ["default"]


def test_populate_is_repeatable(audio_backend):
    """Rediscovery must not duplicate or renumber anything."""
    svc, registry, engine = AudioService(audio_backend), DeviceRegistry(), RoutingEngine()
    svc.populate(engine, registry)
    ids_first = [s.id for s in engine.sinks()]
    svc.populate(engine, registry)
    assert [s.id for s in engine.sinks()] == ids_first


def test_apply_single_sink_sets_default_output(audio_backend):
    svc = AudioService(audio_backend)
    engine = svc.populate(RoutingEngine(), DeviceRegistry())
    engine.connect("default", "hesh")
    assert "Hesh" in svc.apply(engine)
    assert audio_backend.default_sink().ref == "bt1"


def test_apply_multiple_sinks_builds_a_combined_output(audio_backend):
    svc = AudioService(audio_backend)
    engine = svc.populate(RoutingEngine(), DeviceRegistry())
    engine.connect_many("default", ["hesh", "cb-evolve"])
    svc.apply(engine)
    assert sorted(audio_backend.combine_members("combine.audiohub_combine")) == ["bt1", "bt2"]


def test_apply_skips_unavailable_sinks(audio_backend):
    """One headphone leaving must not stop the others (section 19)."""
    svc = AudioService(audio_backend)
    engine = svc.populate(RoutingEngine(), DeviceRegistry())
    engine.connect_many("default", ["hesh", "cb-evolve"])
    engine.set_available("cb-evolve", False)
    assert "Hesh" in svc.apply(engine)


def test_apply_with_no_active_sinks_reports_clearly(audio_backend):
    svc = AudioService(audio_backend)
    engine = svc.populate(RoutingEngine(), DeviceRegistry())
    engine.connect("default", "hesh")
    engine.set_available("hesh", False)
    with pytest.raises(NotSupported):
        svc.apply(engine)


def test_apply_refuses_multi_sink_when_platform_cannot(audio_backend, monkeypatch):
    """macOS is this case: it can combine, but only by hand."""
    monkeypatch.setattr(
        audio_backend,
        "capabilities",
        lambda: {Capability.COMBINE_SINKS_SCRIPTABLE: False},
    )
    svc = AudioService(audio_backend)
    engine = svc.populate(RoutingEngine(), DeviceRegistry())
    engine.connect_many("default", ["hesh", "cb-evolve"])
    with pytest.raises(NotSupported) as exc:
        svc.apply(engine)
    assert "programmatically" in str(exc.value)


def test_bluetooth_audio_devices_exclude_non_audio(bt_backend):
    names = {d.name for d in BluetoothService(bt_backend).audio_devices()}
    assert names == {"Hesh ANC", "CB-EVOLVE"}, "a mouse is not a sink"


def test_bluetooth_connect_updates_state(bt_backend):
    svc = BluetoothService(bt_backend)
    ok, _ = svc.connect("AA:BB:CC:DD:EE:01")
    assert ok
    assert svc.machine("AA:BB:CC:DD:EE:01").state is DeviceState.CONNECTED


def test_bluetooth_connect_failure_is_reported_not_raised(bt_backend):
    svc = BluetoothService(bt_backend)
    ok, reason = svc.connect("FF:FF:FF:FF:FF:FF")
    assert ok is False and reason
    assert svc.machine("FF:FF:FF:FF:FF:FF").state is DeviceState.FAILED


def test_sync_states_notices_a_device_disappearing(bt_backend):
    svc = BluetoothService(bt_backend)
    svc.connect("AA:BB:CC:DD:EE:01")
    bt_backend.disconnect("AA:BB:CC:DD:EE:01")  # simulate the headphone sleeping
    states = svc.sync_states()
    assert states["AA:BB:CC:DD:EE:01"] is DeviceState.DISCONNECTED


def test_reconnect_recovers_a_disconnected_device(bt_backend):
    svc = BluetoothService(bt_backend)
    svc.connect("AA:BB:CC:DD:EE:01")
    svc.disconnect("AA:BB:CC:DD:EE:01")
    ok, _ = svc.reconnect("AA:BB:CC:DD:EE:01")
    assert ok
    assert svc.machine("AA:BB:CC:DD:EE:01").state is DeviceState.CONNECTED


def test_reconnect_refuses_when_already_connected(bt_backend):
    svc = BluetoothService(bt_backend)
    svc.connect("AA:BB:CC:DD:EE:01")
    ok, reason = svc.reconnect("AA:BB:CC:DD:EE:01")
    assert ok is False and "recoverable" in reason
