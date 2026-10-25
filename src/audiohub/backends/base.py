"""Backend contracts.

Everything platform-specific lives behind these two interfaces. The routing
engine, the CLI, the config and the tests never import a platform module
directly. That is the portability guarantee: moving to a cheap SBC means
writing and verifying one backend, not rewriting AudioHub.
"""

from __future__ import annotations

import abc
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence


class Capability(str, Enum):
    ENUMERATE_SINKS = "enumerate_sinks"
    SET_DEFAULT_SINK = "set_default_sink"
    #: Can the OS fan one stream out to many sinks by itself?
    COMBINE_SINKS = "combine_sinks"
    #: Can that fan-out be created/destroyed programmatically, or only by hand?
    COMBINE_SINKS_SCRIPTABLE = "combine_sinks_scriptable"
    PER_SINK_DELAY = "per_sink_delay"
    BLUETOOTH_CONTROL = "bluetooth_control"
    A2DP = "a2dp"


class BackendError(Exception):
    pass


class NotSupported(BackendError):
    """The platform genuinely cannot do this -- not "not implemented yet".

    Raising this is a *finding*, and callers should surface it to the user
    rather than swallowing it.
    """


@dataclass
class BackendSink:
    ref: str                      # opaque, backend-owned identifier
    name: str
    kind: str = "unknown"
    is_default: bool = False
    address: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class BackendSource:
    ref: str
    name: str
    kind: str = "unknown"
    is_default: bool = False
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class BluetoothDevice:
    address: str
    name: str
    connected: bool = False
    paired: bool = True
    device_class: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class ControllerInfo:
    address: Optional[str] = None
    name: Optional[str] = None
    powered: Optional[bool] = None
    chipset: Optional[str] = None
    transport: Optional[str] = None
    firmware: Optional[str] = None
    services: List[str] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)


def run(cmd: Sequence[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
    """Run a command without ever raising on failure or absence.

    Diagnostics must never crash just because a tool is missing -- a missing
    tool IS the diagnostic result.
    """
    if shutil.which(cmd[0]) is None:
        return subprocess.CompletedProcess(cmd, 127, "", f"{cmd[0]}: not found")
    try:
        return subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timed out")
    except OSError as exc:  # pragma: no cover - platform dependent
        return subprocess.CompletedProcess(cmd, 126, "", str(exc))


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


class AudioBackend(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def available(self) -> bool:
        """True if this backend can run on the current host."""

    @abc.abstractmethod
    def capabilities(self) -> Dict[Capability, Optional[bool]]:
        """Capability -> True / False / None.

        None means "unknown, needs an experiment". Reporting None is
        deliberately allowed: claiming a capability we have not demonstrated
        would violate the project's measure-first rule.
        """

    @abc.abstractmethod
    def list_sinks(self) -> List[BackendSink]:
        ...

    @abc.abstractmethod
    def list_sources(self) -> List[BackendSource]:
        ...

    def default_sink(self) -> Optional[BackendSink]:
        return next((s for s in self.list_sinks() if s.is_default), None)

    def set_default_sink(self, ref: str) -> None:
        raise NotSupported(f"{self.name}: cannot set the default sink")

    def create_combine_sink(
        self,
        name: str,
        member_refs: Sequence[str],
        offsets_ms: Optional[Dict[str, float]] = None,
    ) -> str:
        raise NotSupported(f"{self.name}: cannot create a combined sink")

    def destroy_combine_sink(self, ref: str) -> None:
        raise NotSupported(f"{self.name}: cannot destroy a combined sink")

    def server_info(self) -> Dict[str, Optional[str]]:
        return {}


class BluetoothBackend(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def available(self) -> bool:
        ...

    @abc.abstractmethod
    def controller_info(self) -> ControllerInfo:
        ...

    @abc.abstractmethod
    def list_devices(self) -> List[BluetoothDevice]:
        ...

    def connect(self, address: str) -> bool:
        raise NotSupported(f"{self.name}: cannot connect devices")

    def disconnect(self, address: str) -> bool:
        raise NotSupported(f"{self.name}: cannot disconnect devices")
