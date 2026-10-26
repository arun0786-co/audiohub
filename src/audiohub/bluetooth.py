"""Bluetooth service layer: backend facts + explicit per-device state.

The backend reports what the OS believes right now. This layer remembers what
we believed, notices the difference, and decides whether that difference is a
disconnection worth reacting to. Section 19 lives here.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .backends import BluetoothBackend, BluetoothDevice, NotSupported
from .state import DeviceState, DeviceStateMachine


class BluetoothService:
    def __init__(self, backend: BluetoothBackend) -> None:
        self.backend = backend
        self._machines: Dict[str, DeviceStateMachine] = {}

    # ------------------------------------------------------------- discovery

    def available(self) -> bool:
        return self.backend.available()

    def devices(self) -> List[BluetoothDevice]:
        return sorted(self.backend.list_devices(), key=lambda d: d.name.lower())

    def audio_devices(self) -> List[BluetoothDevice]:
        """Devices that plausibly carry audio.

        Filtering on the class/icon avoids offering the user a mouse as a sink.
        Where BlueZ gave us UUIDs we use the A2DP Sink UUID, which is a fact
        rather than a guess.
        """
        out = []
        for dev in self.devices():
            if dev.metadata.get("a2dp_sink") == "True":
                out.append(dev)
                continue
            token = (dev.device_class or "").lower()
            if any(w in token for w in ("headset", "headphone", "speaker", "audio")):
                out.append(dev)
        return out

    def find(self, address: str) -> Optional[BluetoothDevice]:
        target = address.strip().upper()
        return next((d for d in self.devices() if d.address.upper() == target), None)

    # ----------------------------------------------------------------- state

    def machine(self, address: str) -> DeviceStateMachine:
        key = address.strip().upper()
        if key not in self._machines:
            self._machines[key] = DeviceStateMachine(key, DeviceState.DISCOVERED)
        return self._machines[key]

    def sync_states(self) -> Dict[str, DeviceState]:
        """Reconcile our beliefs with the OS.

        Uses `force`, not `transition_to`: the OS is ground truth, and it is
        entitled to jump from CONNECTING straight to DISCONNECTED without
        telling us why.
        """
        observed: Dict[str, DeviceState] = {}
        for dev in self.devices():
            machine = self.machine(dev.address)
            if dev.connected:
                if machine.state not in (DeviceState.CONNECTED, DeviceState.PLAYING):
                    machine.force(DeviceState.CONNECTED, "observed connected")
            elif dev.paired:
                if machine.state in (DeviceState.CONNECTED, DeviceState.PLAYING):
                    machine.force(DeviceState.DISCONNECTED, "observed disconnected")
                elif machine.state is DeviceState.DISCOVERED:
                    machine.force(DeviceState.PAIRED, "observed paired")
            observed[dev.address.upper()] = machine.state
        return observed

    # ----------------------------------------------------------------- control

    def connect(self, address: str) -> Tuple[bool, str]:
        """Connect, returning (ok, human-readable reason). Never raises."""
        machine = self.machine(address)
        try:
            machine.force(DeviceState.CONNECTING, "requested")
            ok = self.backend.connect(address)
        except NotSupported as exc:
            machine.force(DeviceState.FAILED, str(exc))
            return False, str(exc)
        if ok:
            machine.force(DeviceState.CONNECTED, "connected")
            return True, "connected"
        machine.force(DeviceState.FAILED, "connect failed")
        return False, "connect failed"

    def disconnect(self, address: str) -> Tuple[bool, str]:
        machine = self.machine(address)
        try:
            ok = self.backend.disconnect(address)
        except NotSupported as exc:
            return False, str(exc)
        machine.force(
            DeviceState.DISCONNECTED if ok else DeviceState.FAILED,
            "disconnected" if ok else "disconnect failed",
        )
        return ok, "disconnected" if ok else "disconnect failed"

    def reconnect(self, address: str, max_attempts: int = 1) -> Tuple[bool, str]:
        """Attempt recovery. Caller owns the retry cadence and backoff.

        Kept dumb on purpose: a tight reconnect loop is worse than a
        disconnected headphone, because it can wedge the controller.
        """
        machine = self.machine(address)
        if not machine.is_recoverable:
            return False, f"not in a recoverable state ({machine.state.value})"
        for _ in range(max(1, max_attempts)):
            machine.force(DeviceState.RECONNECTING, "auto reconnect")
            ok, reason = self.connect(address)
            if ok:
                return True, reason
        return False, "reconnect exhausted"
