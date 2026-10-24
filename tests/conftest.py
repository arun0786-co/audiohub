"""Shared fixtures.

Every test here runs with AUDIOHUB_BACKEND=null and a throwaway config dir, so
the suite never touches real audio hardware, real Bluetooth, or the developer's
own configuration. Section 24.
"""

from __future__ import annotations

import os

import pytest

from audiohub.backends.null import NullAudioBackend, NullBluetoothBackend
from audiohub.backends.base import BackendSink, BluetoothDevice
from audiohub.routing import EndpointKind, RoutingEngine, Sink, Source


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIOHUB_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("AUDIOHUB_BACKEND", "null")
    yield


@pytest.fixture
def engine() -> RoutingEngine:
    e = RoutingEngine()
    e.add_source(Source(id="default", name="Default audio", kind=EndpointKind.VIRTUAL))
    e.add_sink(Sink(id="hesh", name="Hesh ANC", kind=EndpointKind.BLUETOOTH, backend_ref="bt1"))
    e.add_sink(Sink(id="crossbeats", name="CB-EVOLVE", kind=EndpointKind.BLUETOOTH, backend_ref="bt2"))
    e.add_sink(Sink(id="speakers", name="Speakers", kind=EndpointKind.ALSA, backend_ref="alsa0"))
    return e


@pytest.fixture
def audio_backend() -> NullAudioBackend:
    return NullAudioBackend(
        sinks=[
            BackendSink(ref="bt1", name="Hesh ANC", kind="bluetooth", address="AA:BB:CC:DD:EE:01"),
            BackendSink(ref="bt2", name="CB-EVOLVE", kind="bluetooth", address="AA:BB:CC:DD:EE:02"),
            BackendSink(ref="alsa0", name="Speakers", kind="alsa", is_default=True),
        ]
    )


@pytest.fixture
def bt_backend() -> NullBluetoothBackend:
    return NullBluetoothBackend(
        devices=[
            BluetoothDevice(address="AA:BB:CC:DD:EE:01", name="Hesh ANC", device_class="Headset"),
            BluetoothDevice(address="AA:BB:CC:DD:EE:02", name="CB-EVOLVE", device_class="Headset"),
            BluetoothDevice(address="AA:BB:CC:DD:EE:03", name="A Mouse", device_class="Mouse"),
        ]
    )
