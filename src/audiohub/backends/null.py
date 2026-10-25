"""An in-memory backend with no operating system behind it.

Exists so the entire unit test suite -- and `audiohub` on a machine with no
audio at all -- runs with zero hardware. Section 24: the unit suite must not
need Bluetooth.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .base import (
    AudioBackend,
    BackendSink,
    BackendSource,
    BluetoothBackend,
    BluetoothDevice,
    Capability,
    ControllerInfo,
)


class NullAudioBackend(AudioBackend):
    name = "null"

    def __init__(
        self,
        sinks: Optional[List[BackendSink]] = None,
        sources: Optional[List[BackendSource]] = None,
    ) -> None:
        self._sinks = list(sinks or [])
        self._sources = list(sources or [])
        self._combines: Dict[str, List[str]] = {}
        self._default: Optional[str] = None

    def available(self) -> bool:
        return True

    def capabilities(self) -> Dict[Capability, Optional[bool]]:
        return {
            Capability.ENUMERATE_SINKS: True,
            Capability.SET_DEFAULT_SINK: True,
            Capability.COMBINE_SINKS: True,
            Capability.COMBINE_SINKS_SCRIPTABLE: True,
            Capability.PER_SINK_DELAY: True,
            Capability.A2DP: False,
        }

    def list_sinks(self) -> List[BackendSink]:
        return list(self._sinks)

    def list_sources(self) -> List[BackendSource]:
        return list(self._sources)

    def add_sink(self, sink: BackendSink) -> BackendSink:
        self._sinks.append(sink)
        return sink

    def remove_sink(self, ref: str) -> None:
        self._sinks = [s for s in self._sinks if s.ref != ref]

    def set_default_sink(self, ref: str) -> None:
        self._default = ref
        for s in self._sinks:
            s.is_default = s.ref == ref

    def create_combine_sink(
        self,
        name: str,
        member_refs: Sequence[str],
        offsets_ms: Optional[Dict[str, float]] = None,
    ) -> str:
        ref = f"combine.{name}"
        self._combines[ref] = list(member_refs)
        self._sinks.append(BackendSink(ref=ref, name=name, kind="virtual"))
        return ref

    def destroy_combine_sink(self, ref: str) -> None:
        self._combines.pop(ref, None)
        self.remove_sink(ref)

    def combine_members(self, ref: str) -> List[str]:
        return list(self._combines.get(ref, []))


class NullBluetoothBackend(BluetoothBackend):
    name = "null"

    def __init__(self, devices: Optional[List[BluetoothDevice]] = None) -> None:
        self._devices = list(devices or [])

    def available(self) -> bool:
        return True

    def controller_info(self) -> ControllerInfo:
        return ControllerInfo(address="00:00:00:00:00:00", name="null", powered=True)

    def list_devices(self) -> List[BluetoothDevice]:
        return list(self._devices)

    def connect(self, address: str) -> bool:
        for d in self._devices:
            if d.address == address:
                d.connected = True
                return True
        return False

    def disconnect(self, address: str) -> bool:
        for d in self._devices:
            if d.address == address:
                d.connected = False
                return True
        return False
