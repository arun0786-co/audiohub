"""Linux backend: PipeWire + BlueZ.

This is the project's actual target platform and the one the final cheap device
will run. It is written against documented structured interfaces only:

  * `pw-dump`  -- PipeWire's own JSON object dump
  * `pactl --format=json` -- pipewire-pulse, for the default sink and modules
  * `busctl --json=short` -- BlueZ over D-Bus, no python-dbus dependency

STATUS: UNVERIFIED. The development machine for this repository is macOS, so
none of this has been executed against a real PipeWire/BlueZ host yet. It is
structured so that `audiohub doctor` on a Debian box is the first thing that
exercises it. Do not treat anything here as a measured result -- see
docs/limitations.md.
"""

from __future__ import annotations

import json
import platform
import re
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

COMBINE_SINK_NAME = "audiohub_combine"


def is_linux() -> bool:
    return platform.system() == "Linux"


def _pw_dump() -> List[Dict[str, Any]]:
    proc = run(["pw-dump"], timeout=15)
    if proc.returncode != 0 or not proc.stdout.strip():
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _pactl_json(*args: str) -> Optional[Any]:
    proc = run(["pactl", "--format=json", *args], timeout=10)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


class LinuxAudioBackend(AudioBackend):
    name = "pipewire"

    def available(self) -> bool:
        return is_linux() and (have("pw-dump") or have("pactl"))

    def capabilities(self) -> Dict[Capability, Optional[bool]]:
        combine = have("pactl") or have("pw-cli")
        return {
            Capability.ENUMERATE_SINKS: have("pw-dump") or have("pactl"),
            Capability.SET_DEFAULT_SINK: have("pactl") or have("wpctl"),
            # module-combine-sink / libpipewire-module-combine-stream.
            Capability.COMBINE_SINKS: combine,
            # Unlike macOS, this IS scriptable -- the whole reason Linux is the
            # target platform for AudioHub.
            Capability.COMBINE_SINKS_SCRIPTABLE: combine,
            # Planned via per-sink module-loopback latency_msec. Not yet proven.
            Capability.PER_SINK_DELAY: None,
            Capability.A2DP: None,  # depends on BlueZ config; doctor checks it
        }

    # ------------------------------------------------------------ enumeration

    def _nodes(self) -> List[Dict[str, Any]]:
        return [
            o
            for o in _pw_dump()
            if o.get("type") == "PipeWire:Interface:Node"
            and isinstance(o.get("info"), dict)
        ]

    def _default_sink_name(self) -> Optional[str]:
        info = _pactl_json("info")
        if isinstance(info, dict):
            name = info.get("default_sink_name")
            if name:
                return str(name)
        proc = run(["wpctl", "status"])  # best effort only
        return None if proc.returncode != 0 else None

    @staticmethod
    def _kind_from_props(props: Dict[str, Any]) -> str:
        api = str(props.get("device.api", ""))
        if api == "bluez5":
            return "bluetooth"
        if api == "alsa":
            return "alsa"
        factory = str(props.get("factory.name", ""))
        if "null" in factory or "combine" in factory or "loopback" in factory:
            return "virtual"
        return "pipewire"

    def _endpoints(self, media_class: str) -> List[Dict[str, Any]]:
        out = []
        for node in self._nodes():
            props = node["info"].get("props", {}) or {}
            if props.get("media.class") != media_class:
                continue
            out.append(props)
        return out

    def list_sinks(self) -> List[BackendSink]:
        default = self._default_sink_name()
        sinks = []
        for props in self._endpoints("Audio/Sink"):
            node_name = str(props.get("node.name", ""))
            sinks.append(
                BackendSink(
                    ref=node_name,
                    name=str(
                        props.get("node.description")
                        or props.get("node.nick")
                        or node_name
                    ),
                    kind=self._kind_from_props(props),
                    is_default=bool(default and node_name == default),
                    address=props.get("api.bluez5.address"),
                    sample_rate=props.get("audio.rate"),
                    metadata={
                        "codec": str(props.get("api.bluez5.codec", "")),
                        "profile": str(props.get("api.bluez5.profile", "")),
                        "object.serial": str(props.get("object.serial", "")),
                    },
                )
            )
        return sinks

    def list_sources(self) -> List[BackendSource]:
        sources = []
        for props in self._endpoints("Audio/Source"):
            node_name = str(props.get("node.name", ""))
            sources.append(
                BackendSource(
                    ref=node_name,
                    name=str(props.get("node.description") or node_name),
                    kind=self._kind_from_props(props),
                )
            )
        return sources

    # ------------------------------------------------------------------ control

    def set_default_sink(self, ref: str) -> None:
        proc = run(["pactl", "set-default-sink", ref])
        if proc.returncode != 0:
            raise NotSupported(f"pactl set-default-sink failed: {proc.stderr.strip()}")

    def create_combine_sink(
        self,
        name: str = COMBINE_SINK_NAME,
        member_refs: Sequence[str] = (),
        offsets_ms: Optional[Dict[str, float]] = None,
    ) -> str:
        """Fan one stream out to several sinks -- the Phase 4 milestone.

        Uses module-combine-sink, which PipeWire implements for Pulse
        compatibility. Per-sink delay is NOT available through this module.

        Phase 7 plan (deliberately not implemented until Phase 6 proves it is
        needed): replace this with a null sink plus one module-loopback per
        real sink, each carrying its own `latency_msec`, which is the only
        documented way to give members different delays. Building that now
        would be optimising against an unmeasured problem.
        """
        if offsets_ms and any(v for v in offsets_ms.values()):
            raise NotSupported(
                "module-combine-sink cannot apply per-sink delay; run Phase 6 "
                "first, then implement the null-sink + module-loopback fan-out"
            )
        if not member_refs:
            raise NotSupported("a combined sink needs at least one member")
        proc = run(
            [
                "pactl",
                "load-module",
                "module-combine-sink",
                f"sink_name={name}",
                "slaves=" + ",".join(member_refs),
                "channels=2",
            ],
            timeout=15,
        )
        if proc.returncode != 0:
            raise NotSupported(f"could not load module-combine-sink: {proc.stderr.strip()}")
        return name

    def destroy_combine_sink(self, ref: str = COMBINE_SINK_NAME) -> None:
        modules = _pactl_json("list", "modules")
        if not isinstance(modules, list):
            raise NotSupported("could not enumerate PipeWire/Pulse modules")
        for mod in modules:
            args = str(mod.get("argument") or "")
            if mod.get("name") == "module-combine-sink" and f"sink_name={ref}" in args:
                run(["pactl", "unload-module", str(mod.get("index"))])
                return

    def server_info(self) -> Dict[str, Optional[str]]:
        def version(cmd: Sequence[str]) -> Optional[str]:
            proc = run(list(cmd), timeout=5)
            if proc.returncode != 0:
                return None
            text = (proc.stdout or proc.stderr).strip()
            match = re.search(r"\d+\.\d+(\.\d+)?", text)
            return match.group(0) if match else (text.splitlines() or [None])[0]

        alsa = None
        try:
            with open("/proc/asound/version", "r", encoding="utf-8") as fh:
                alsa = fh.read().strip()
        except OSError:
            pass

        return {
            "server": "PipeWire",
            "pipewire": version(["pipewire", "--version"]),
            "wireplumber": version(["wireplumber", "--version"]),
            "pulse_compat": version(["pactl", "--version"]),
            "alsa": alsa,
            "arch": platform.machine(),
        }


class LinuxBluetoothBackend(BluetoothBackend):
    """BlueZ over D-Bus using busctl, so we need no python-dbus wheel."""

    name = "bluez"

    def available(self) -> bool:
        return is_linux() and (have("busctl") or have("bluetoothctl"))

    # busctl --json=short wraps every value as {"type": ..., "data": ...}.
    @staticmethod
    def _unwrap(node: Any) -> Any:
        if isinstance(node, dict) and set(node.keys()) == {"type", "data"}:
            return LinuxBluetoothBackend._unwrap(node["data"])
        if isinstance(node, dict):
            return {k: LinuxBluetoothBackend._unwrap(v) for k, v in node.items()}
        if isinstance(node, list):
            return [LinuxBluetoothBackend._unwrap(v) for v in node]
        return node

    def _managed_objects(self) -> Dict[str, Dict[str, Any]]:
        proc = run(
            [
                "busctl",
                "--json=short",
                "call",
                "org.bluez",
                "/",
                "org.freedesktop.DBus.ObjectManager",
                "GetManagedObjects",
            ],
            timeout=15,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {}
        try:
            raw = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {}
        data = self._unwrap(raw).get("data")
        if isinstance(data, list) and data:
            data = data[0]
        return data if isinstance(data, dict) else {}

    def controller_info(self) -> ControllerInfo:
        for path, interfaces in self._managed_objects().items():
            adapter = interfaces.get("org.bluez.Adapter1")
            if not adapter:
                continue
            return ControllerInfo(
                address=adapter.get("Address"),
                name=adapter.get("Name") or adapter.get("Alias"),
                powered=adapter.get("Powered"),
                metadata={
                    "path": path,
                    "discoverable": str(adapter.get("Discoverable", "")),
                    "class": str(adapter.get("Class", "")),
                },
            )
        return ControllerInfo()

    def list_devices(self) -> List[BluetoothDevice]:
        devices = []
        for path, interfaces in self._managed_objects().items():
            dev = interfaces.get("org.bluez.Device1")
            if not dev:
                continue
            uuids = dev.get("UUIDs") or []
            devices.append(
                BluetoothDevice(
                    address=str(dev.get("Address", "")),
                    name=str(dev.get("Alias") or dev.get("Name") or "unknown"),
                    connected=bool(dev.get("Connected", False)),
                    paired=bool(dev.get("Paired", False)),
                    device_class=str(dev.get("Icon", "")) or None,
                    metadata={
                        "path": path,
                        "trusted": str(dev.get("Trusted", "")),
                        # 0000110b = A2DP Audio Sink -- proof the device can be
                        # a music output, not just a headset microphone.
                        "a2dp_sink": str(
                            any(str(u).lower().startswith("0000110b") for u in uuids)
                        ),
                    },
                )
            )
        return devices

    def _device_path(self, address: str) -> Optional[str]:
        for dev in self.list_devices():
            if dev.address.upper() == address.strip().upper():
                return dev.metadata.get("path")
        return None

    def _call(self, address: str, method: str, timeout: float) -> bool:
        path = self._device_path(address)
        if not path:
            return False
        proc = run(
            ["busctl", "call", "org.bluez", path, "org.bluez.Device1", method],
            timeout=timeout,
        )
        return proc.returncode == 0

    def connect(self, address: str) -> bool:
        return self._call(address, "Connect", timeout=30)

    def disconnect(self, address: str) -> bool:
        return self._call(address, "Disconnect", timeout=15)
