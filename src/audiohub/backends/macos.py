"""macOS backend: CoreAudio + Apple Bluetooth, via `system_profiler -json`.

Not the project's target platform -- Debian is -- but it is the platform the
first development machine actually runs, and the multi-sink Bluetooth question
can be investigated here at zero cost. Verified against macOS 15.7.7 on
Apple Silicon; see docs/experiments.md.

Everything here reads structured JSON. No scraping of human-readable output,
per section 18.
"""

from __future__ import annotations

import json
import platform
from typing import Any, Dict, List, Optional, Sequence

from .base import (
    AudioBackend,
    BackendSink,
    BackendSource,
    BluetoothBackend,
    BluetoothDevice,
    Capability,
    ControllerInfo,
    NotSupported,
    have,
    run,
)

_YES = "spaudio_yes"

#: CoreAudio transport constants seen in SPAudioDataType.
_TRANSPORT_MAP = {
    "coreaudio_device_type_builtin": "builtin",
    "coreaudio_device_type_bluetooth": "bluetooth",
    "coreaudio_device_type_usb": "usb",
    "coreaudio_device_type_virtual": "virtual",
    "coreaudio_device_type_hdmi": "hdmi",
    "coreaudio_device_type_displayport": "displayport",
    "coreaudio_device_type_aggregate": "aggregate",
}


def is_macos() -> bool:
    return platform.system() == "Darwin"


def _profile(datatype: str, timeout: float = 20.0) -> Optional[Any]:
    proc = run(["system_profiler", "-json", datatype], timeout=timeout)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout).get(datatype)
    except json.JSONDecodeError:
        return None


class MacOSAudioBackend(AudioBackend):
    name = "coreaudio"

    def available(self) -> bool:
        return is_macos() and have("system_profiler")

    def capabilities(self) -> Dict[Capability, Optional[bool]]:
        return {
            Capability.ENUMERATE_SINKS: True,
            # SwitchAudioSource is a free Homebrew formula; without it we can
            # enumerate but not switch.
            Capability.SET_DEFAULT_SINK: have("SwitchAudioSource"),
            # A Multi-Output Device does exactly this, and ships with macOS.
            Capability.COMBINE_SINKS: True,
            # ...but only Audio MIDI Setup can create one. There is no supported
            # CLI or public API for building an aggregate device. This is a real
            # platform limitation, not a gap in this file.
            Capability.COMBINE_SINKS_SCRIPTABLE: False,
            # A Multi-Output Device offers drift correction, not a settable
            # per-member delay. Unknown until measured.
            Capability.PER_SINK_DELAY: None,
            Capability.A2DP: True,
        }

    def _devices(self) -> List[Dict[str, Any]]:
        data = _profile("SPAudioDataType")
        if not data:
            return []
        out: List[Dict[str, Any]] = []
        for section in data:
            out.extend(section.get("_items", []))
        return out

    @staticmethod
    def _kind(dev: Dict[str, Any]) -> str:
        return _TRANSPORT_MAP.get(dev.get("coreaudio_device_transport", ""), "unknown")

    def list_sinks(self) -> List[BackendSink]:
        sinks = []
        for dev in self._devices():
            channels = dev.get("coreaudio_device_output")
            if not channels:
                continue
            name = dev.get("_name", "unknown")
            sinks.append(
                BackendSink(
                    ref=name,  # CoreAudio UIDs are not exposed by system_profiler
                    name=name,
                    kind=self._kind(dev),
                    is_default=dev.get("coreaudio_default_audio_output_device") == _YES,
                    sample_rate=dev.get("coreaudio_device_srate"),
                    channels=channels,
                    metadata={
                        "manufacturer": str(dev.get("coreaudio_device_manufacturer", "")),
                        "output_source": str(dev.get("coreaudio_output_source", "")),
                    },
                )
            )
        return sinks

    def list_sources(self) -> List[BackendSource]:
        sources = []
        for dev in self._devices():
            if not dev.get("coreaudio_device_input"):
                continue
            name = dev.get("_name", "unknown")
            sources.append(
                BackendSource(
                    ref=name,
                    name=name,
                    kind=self._kind(dev),
                    is_default=dev.get("coreaudio_default_audio_input_device") == _YES,
                )
            )
        return sources

    def set_default_sink(self, ref: str) -> None:
        if not have("SwitchAudioSource"):
            raise NotSupported(
                "switching the default output needs SwitchAudioSource "
                "(free: brew install switchaudio-osx)"
            )
        proc = run(["SwitchAudioSource", "-t", "output", "-s", ref])
        if proc.returncode != 0:
            raise NotSupported(f"could not select {ref!r}: {proc.stderr.strip()}")

    def create_combine_sink(
        self,
        name: str,
        member_refs: Sequence[str],
        offsets_ms: Optional[Dict[str, float]] = None,
    ) -> str:
        raise NotSupported(
            "macOS has no supported API for creating a Multi-Output Device. "
            "Create one by hand in Audio MIDI Setup, then treat it as a normal "
            "sink. On Linux this is a one-line PipeWire module-combine-sink."
        )

    def server_info(self) -> Dict[str, Optional[str]]:
        return {
            "server": "CoreAudio",
            "os": f"macOS {platform.mac_ver()[0]}".strip(),
            "arch": platform.machine(),
        }


class MacOSBluetoothBackend(BluetoothBackend):
    name = "apple-bluetooth"

    def available(self) -> bool:
        return is_macos() and have("system_profiler")

    def _root(self) -> Dict[str, Any]:
        data = _profile("SPBluetoothDataType")
        if not data:
            return {}
        return data[0] if isinstance(data, list) and data else {}

    def controller_info(self) -> ControllerInfo:
        props = self._root().get("controller_properties", {}) or {}
        # Format: "0x392039 < HFP AVRCP A2DP HID Braille LEA AACP GATT SerialPort >"
        # Take only what is inside the angle brackets; the leading value is a
        # bitmask, and service names may contain digits (A2DP) or be mixed
        # case (SerialPort), so no character-class filter is safe here.
        services_raw = str(props.get("controller_supportedServices", "") or "")
        services: List[str] = []
        if "<" in services_raw and ">" in services_raw:
            inner = services_raw[services_raw.index("<") + 1 : services_raw.rindex(">")]
            services = inner.split()
        state = props.get("controller_state", "")
        return ControllerInfo(
            address=props.get("controller_address"),
            name=props.get("controller_chipset"),
            powered=("on" in str(state).lower()) if state else None,
            chipset=props.get("controller_chipset"),
            transport=props.get("controller_transport"),
            firmware=props.get("controller_firmwareVersion"),
            services=services,
            metadata={"vendor_id": str(props.get("controller_vendorID", ""))},
        )

    def list_devices(self) -> List[BluetoothDevice]:
        root = self._root()
        devices: List[BluetoothDevice] = []
        for key, connected in (
            ("device_connected", True),
            ("device_not_connected", False),
        ):
            for entry in root.get(key, []) or []:
                # Each entry is a single-key dict: {"Hesh ANC": {...}}
                for dev_name, props in entry.items():
                    props = props or {}
                    devices.append(
                        BluetoothDevice(
                            address=props.get("device_address", ""),
                            name=dev_name,
                            connected=connected,
                            paired=True,
                            device_class=props.get("device_minorType"),
                            metadata={
                                k: str(v)
                                for k, v in props.items()
                                if k != "device_address"
                            },
                        )
                    )
        return devices

    def connect(self, address: str) -> bool:
        if not have("blueutil"):
            raise NotSupported(
                "connecting devices needs blueutil (free: brew install blueutil)"
            )
        return run(["blueutil", "--connect", address], timeout=30).returncode == 0

    def disconnect(self, address: str) -> bool:
        if not have("blueutil"):
            raise NotSupported(
                "disconnecting devices needs blueutil (free: brew install blueutil)"
            )
        return run(["blueutil", "--disconnect", address], timeout=30).returncode == 0
