"""The routing engine: a pure, backend-agnostic source -> sink graph.

Deliberately knows nothing about PipeWire, CoreAudio, BlueZ or Bluetooth. It
answers "what *should* be playing where", and an AudioBackend is responsible for
making the operating system agree. That split is what lets the same engine move
from this laptop to a cheap SBC later without rewriting the interesting logic.

Design rule for failure handling (see docs/architecture.md): a sink going away
never mutates the graph. The route survives; only the sink's availability
changes. One headphone walking out of the room must not tear down the movie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Set, Tuple


class EndpointKind(str, Enum):
    """What a source/sink physically is. The engine treats these identically."""

    BLUETOOTH = "bluetooth"
    USB = "usb"
    ALSA = "alsa"
    PIPEWIRE = "pipewire"
    COREAUDIO = "coreaudio"
    NETWORK = "network"
    VIRTUAL = "virtual"
    NULL = "null"


class RoutingError(Exception):
    pass


class UnknownSource(RoutingError):
    def __init__(self, source_id: str) -> None:
        super().__init__(f"unknown source: {source_id!r}")
        self.source_id = source_id


class UnknownSink(RoutingError):
    def __init__(self, sink_id: str) -> None:
        super().__init__(f"unknown sink: {sink_id!r}")
        self.sink_id = sink_id


class DuplicateEndpoint(RoutingError):
    pass


@dataclass
class Endpoint:
    """A source or sink.

    `backend_ref` is the opaque identifier the backend uses (a PipeWire node
    name, a CoreAudio UID, a Bluetooth MAC). The engine never interprets it, and
    the CLI never shows it as the primary handle -- users deal in `id`.
    """

    id: str
    name: str
    kind: EndpointKind
    backend_ref: Optional[str] = None
    available: bool = True
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class Sink(Endpoint):
    muted: bool = False
    #: Extra delay applied to this sink to align it with slower sinks (Phase 7).
    latency_offset_ms: float = 0.0
    #: Last measured end-to-end latency, if Phase 6 has been run. None = unknown.
    measured_latency_ms: Optional[float] = None


@dataclass
class Source(Endpoint):
    pass


@dataclass
class RouteStatus:
    source_id: str
    sink_id: str
    sink_name: str
    available: bool
    muted: bool
    latency_offset_ms: float

    @property
    def active(self) -> bool:
        """Audio is actually expected to be audible on this route."""
        return self.available and not self.muted


class RoutingEngine:
    def __init__(self) -> None:
        self._sources: Dict[str, Source] = {}
        self._sinks: Dict[str, Sink] = {}
        self._edges: Set[Tuple[str, str]] = set()

    # ---------------------------------------------------------------- sources

    def add_source(self, source: Source, replace: bool = False) -> Source:
        if source.id in self._sources and not replace:
            raise DuplicateEndpoint(f"source already exists: {source.id!r}")
        self._sources[source.id] = source
        return source

    def remove_source(self, source_id: str) -> None:
        self._require_source(source_id)
        del self._sources[source_id]
        self._edges = {e for e in self._edges if e[0] != source_id}

    def get_source(self, source_id: str) -> Source:
        return self._require_source(source_id)

    def sources(self) -> List[Source]:
        return sorted(self._sources.values(), key=lambda s: s.id)

    # ------------------------------------------------------------------ sinks

    def add_sink(self, sink: Sink, replace: bool = False) -> Sink:
        if sink.id in self._sinks and not replace:
            raise DuplicateEndpoint(f"sink already exists: {sink.id!r}")
        self._sinks[sink.id] = sink
        return sink

    def remove_sink(self, sink_id: str) -> None:
        self._require_sink(sink_id)
        del self._sinks[sink_id]
        self._edges = {e for e in self._edges if e[1] != sink_id}

    def get_sink(self, sink_id: str) -> Sink:
        return self._require_sink(sink_id)

    def sinks(self) -> List[Sink]:
        return sorted(self._sinks.values(), key=lambda s: s.id)

    # ------------------------------------------------------------------ edges

    def connect(self, source_id: str, sink_id: str) -> bool:
        """Route `source_id` to `sink_id`.

        Idempotent: returns True if the route was newly created, False if it
        already existed. Re-issuing a route is a normal thing for a reconnect
        loop to do, so it must not be an error.
        """
        self._require_source(source_id)
        self._require_sink(sink_id)
        edge = (source_id, sink_id)
        if edge in self._edges:
            return False
        self._edges.add(edge)
        return True

    def connect_many(self, source_id: str, sink_ids: Iterable[str]) -> List[str]:
        """Connect one source to several sinks -- the Phase 4 milestone.

        Validates every sink before mutating anything, so a typo in the third
        sink does not leave a half-applied route behind.
        """
        self._require_source(source_id)
        sink_ids = list(sink_ids)
        for sink_id in sink_ids:
            self._require_sink(sink_id)
        return [s for s in sink_ids if self.connect(source_id, s)]

    def disconnect(self, source_id: str, sink_id: str) -> bool:
        """Remove a route. Returns False if it was not there to begin with."""
        self._require_source(source_id)
        self._require_sink(sink_id)
        edge = (source_id, sink_id)
        if edge not in self._edges:
            return False
        self._edges.discard(edge)
        return True

    def disconnect_all(self, source_id: str) -> int:
        self._require_source(source_id)
        doomed = {e for e in self._edges if e[0] == source_id}
        self._edges -= doomed
        return len(doomed)

    def is_connected(self, source_id: str, sink_id: str) -> bool:
        return (source_id, sink_id) in self._edges

    def routes(self) -> List[Tuple[str, str]]:
        return sorted(self._edges)

    def sinks_for(self, source_id: str, only_active: bool = False) -> List[Sink]:
        self._require_source(source_id)
        out = [self._sinks[b] for (a, b) in self._edges if a == source_id]
        if only_active:
            out = [s for s in out if s.available and not s.muted]
        return sorted(out, key=lambda s: s.id)

    def sources_for(self, sink_id: str) -> List[Source]:
        self._require_sink(sink_id)
        return sorted(
            (self._sources[a] for (a, b) in self._edges if b == sink_id),
            key=lambda s: s.id,
        )

    # ------------------------------------------------------------ mute / avail

    def mute(self, sink_id: str) -> None:
        self._require_sink(sink_id).muted = True

    def unmute(self, sink_id: str) -> None:
        self._require_sink(sink_id).muted = False

    def set_available(self, sink_id: str, available: bool) -> None:
        """Mark a sink present or absent WITHOUT touching its routes.

        This is the Phase 5 / section 19 contract: when Crossbeats disconnects,
        the route stays configured so that reconnection restores it with no
        user action, and the other sinks keep playing.
        """
        self._require_sink(sink_id).available = available

    def set_latency_offset(self, sink_id: str, offset_ms: float) -> None:
        if offset_ms < 0:
            raise RoutingError("latency offset must be >= 0 (we can delay, not predict)")
        self._require_sink(sink_id).latency_offset_ms = float(offset_ms)

    # ------------------------------------------------------------------ state

    def route_statuses(self) -> List[RouteStatus]:
        out = []
        for source_id, sink_id in sorted(self._edges):
            sink = self._sinks[sink_id]
            out.append(
                RouteStatus(
                    source_id=source_id,
                    sink_id=sink_id,
                    sink_name=sink.name,
                    available=sink.available,
                    muted=sink.muted,
                    latency_offset_ms=sink.latency_offset_ms,
                )
            )
        return out

    def get_state(self) -> Dict[str, object]:
        """A serialisable snapshot. The CLI, the web UI and the tests all read this."""
        return {
            "sources": [
                {
                    "id": s.id,
                    "name": s.name,
                    "kind": s.kind.value,
                    "available": s.available,
                }
                for s in self.sources()
            ],
            "sinks": [
                {
                    "id": s.id,
                    "name": s.name,
                    "kind": s.kind.value,
                    "available": s.available,
                    "muted": s.muted,
                    "latency_offset_ms": s.latency_offset_ms,
                    "measured_latency_ms": s.measured_latency_ms,
                }
                for s in self.sinks()
            ],
            "routes": [
                {
                    "source": r.source_id,
                    "sink": r.sink_id,
                    "active": r.active,
                    "available": r.available,
                    "muted": r.muted,
                    "latency_offset_ms": r.latency_offset_ms,
                }
                for r in self.route_statuses()
            ],
        }

    # ------------------------------------------------------------- internals

    def _require_source(self, source_id: str) -> Source:
        try:
            return self._sources[source_id]
        except KeyError:
            raise UnknownSource(source_id) from None

    def _require_sink(self, sink_id: str) -> Sink:
        try:
            return self._sinks[sink_id]
        except KeyError:
            raise UnknownSink(sink_id) from None
