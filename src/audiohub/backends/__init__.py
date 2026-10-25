"""Backend selection.

`detect()` picks a platform pair at runtime. Nothing above this layer knows
which one it got.
"""

from __future__ import annotations

import os
import platform
from typing import Tuple

from .base import (
    AudioBackend,
    BackendError,
    BackendSink,
    BackendSource,
    BluetoothBackend,
    BluetoothDevice,
    Capability,
    ControllerInfo,
    NotSupported,
)
from .null import NullAudioBackend, NullBluetoothBackend

__all__ = [
    "AudioBackend",
    "BluetoothBackend",
    "BackendError",
    "BackendSink",
    "BackendSource",
    "BluetoothDevice",
    "Capability",
    "ControllerInfo",
    "NotSupported",
    "NullAudioBackend",
    "NullBluetoothBackend",
    "detect",
    "platform_name",
]


def platform_name() -> str:
    """Effective platform. AUDIOHUB_BACKEND forces one (used by tests and CI)."""
    forced = os.environ.get("AUDIOHUB_BACKEND", "").strip().lower()
    if forced:
        return forced
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "macos"
    return "null"


def detect() -> Tuple[AudioBackend, BluetoothBackend]:
    name = platform_name()
    if name == "linux":
        from .linux import LinuxAudioBackend, LinuxBluetoothBackend

        return LinuxAudioBackend(), LinuxBluetoothBackend()
    if name == "macos":
        from .macos import MacOSAudioBackend, MacOSBluetoothBackend

        return MacOSAudioBackend(), MacOSBluetoothBackend()
    return NullAudioBackend(), NullBluetoothBackend()
