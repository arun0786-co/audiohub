"""Explicit device state machine.

Bluetooth devices fail constantly: they sleep, wander out of range, get grabbed
by a phone, or vanish when a controller resets. Rather than inferring state from
whatever a command happened to print, every device carries an explicit state and
transitions are validated. An illegal transition is a bug in our logic, and we
want it to be loud in tests and survivable in production.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Dict, FrozenSet, List, NamedTuple, Optional


class DeviceState(str, Enum):
    DISCOVERED = "DISCOVERED"
    PAIRED = "PAIRED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    PLAYING = "PLAYING"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"

    def __str__(self) -> str:  # pragma: no cover - display only
        return self.value


#: Legal transitions. Deliberately permissive around failure paths -- anything
#: can drop to FAILED or DISCONNECTED, because the radio owes us nothing.
TRANSITIONS: Dict[DeviceState, FrozenSet[DeviceState]] = {
    DeviceState.DISCOVERED: frozenset(
        {DeviceState.PAIRED, DeviceState.CONNECTING, DeviceState.FAILED}
    ),
    DeviceState.PAIRED: frozenset(
        {DeviceState.CONNECTING, DeviceState.DISCOVERED, DeviceState.FAILED}
    ),
    DeviceState.CONNECTING: frozenset(
        {DeviceState.CONNECTED, DeviceState.DISCONNECTED, DeviceState.FAILED}
    ),
    DeviceState.CONNECTED: frozenset(
        {DeviceState.PLAYING, DeviceState.DISCONNECTED, DeviceState.FAILED}
    ),
    DeviceState.PLAYING: frozenset(
        {DeviceState.CONNECTED, DeviceState.DISCONNECTED, DeviceState.FAILED}
    ),
    DeviceState.DISCONNECTED: frozenset(
        {
            DeviceState.RECONNECTING,
            DeviceState.CONNECTING,
            DeviceState.PAIRED,
            DeviceState.FAILED,
        }
    ),
    DeviceState.RECONNECTING: frozenset(
        {DeviceState.CONNECTED, DeviceState.DISCONNECTED, DeviceState.FAILED}
    ),
    DeviceState.FAILED: frozenset(
        {
            DeviceState.RECONNECTING,
            DeviceState.CONNECTING,
            DeviceState.DISCONNECTED,
            DeviceState.DISCOVERED,
        }
    ),
}

#: States in which the device can actually carry audio.
LIVE_STATES = frozenset({DeviceState.CONNECTED, DeviceState.PLAYING})

#: States from which an automatic reconnect attempt is reasonable.
RECOVERABLE_STATES = frozenset({DeviceState.DISCONNECTED, DeviceState.FAILED})


class InvalidTransition(Exception):
    def __init__(self, device_id: str, src: DeviceState, dst: DeviceState) -> None:
        super().__init__(f"{device_id}: illegal transition {src.value} -> {dst.value}")
        self.device_id = device_id
        self.src = src
        self.dst = dst


class TransitionRecord(NamedTuple):
    at: float
    src: DeviceState
    dst: DeviceState
    reason: str


class DeviceStateMachine:
    """Tracks one device's lifecycle, with history for post-mortem debugging."""

    def __init__(
        self,
        device_id: str,
        initial: DeviceState = DeviceState.DISCOVERED,
        clock=time.monotonic,
    ) -> None:
        self.device_id = device_id
        self._state = initial
        self._clock = clock
        self.history: List[TransitionRecord] = []
        self.failure_count = 0

    @property
    def state(self) -> DeviceState:
        return self._state

    @property
    def is_live(self) -> bool:
        return self._state in LIVE_STATES

    @property
    def is_recoverable(self) -> bool:
        return self._state in RECOVERABLE_STATES

    def can_transition_to(self, dst: DeviceState) -> bool:
        return dst in TRANSITIONS[self._state]

    def transition_to(self, dst: DeviceState, reason: str = "") -> DeviceState:
        """Move to `dst`, raising InvalidTransition if the move is not legal.

        Transitioning to the current state is a no-op rather than an error --
        polling a backend that reports the same state twice is normal, not a bug.
        """
        if dst is self._state:
            return self._state
        if not self.can_transition_to(dst):
            raise InvalidTransition(self.device_id, self._state, dst)
        return self._apply(dst, reason)

    def force(self, dst: DeviceState, reason: str = "forced") -> DeviceState:
        """Set state without validation.

        Reserved for resynchronising with ground truth from the OS, which may
        legitimately disagree with whatever we believed.
        """
        if dst is self._state:
            return self._state
        return self._apply(dst, reason)

    def _apply(self, dst: DeviceState, reason: str) -> DeviceState:
        src = self._state
        self._state = dst
        self.history.append(TransitionRecord(self._clock(), src, dst, reason))
        if dst is DeviceState.FAILED:
            self.failure_count += 1
        elif dst in LIVE_STATES:
            self.failure_count = 0
        return dst

    def last_reason(self) -> Optional[str]:
        return self.history[-1].reason if self.history else None

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"<DeviceStateMachine {self.device_id} {self._state.value}>"
