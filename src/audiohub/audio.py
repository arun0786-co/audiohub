"""Audio service layer: turns backend sinks/sources into engine endpoints."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .backends import AudioBackend, BackendSink, Capability, NotSupported
from .devices import DeviceRegistry
from .routing import EndpointKind, RoutingEngine, Sink, Source

#: backend `kind` strings -> engine EndpointKind
_KIND_MAP = {
    "bluetooth": EndpointKind.BLUETOOTH,
    "usb": EndpointKind.USB,
    "alsa": EndpointKind.ALSA,
    "pipewire": EndpointKind.PIPEWIRE,
    "builtin": EndpointKind.COREAUDIO,
    "aggregate": EndpointKind.VIRTUAL,
    "virtual": EndpointKind.VIRTUAL,
    "hdmi": EndpointKind.VIRTUAL,
    "displayport": EndpointKind.VIRTUAL,
}

DEFAULT_SOURCE_ID = "default"


class AudioService:
    def __init__(self, backend: AudioBackend) -> None:
        self.backend = backend

    def available(self) -> bool:
        return self.backend.available()

    def capabilities(self) -> Dict[Capability, Optional[bool]]:
        return self.backend.capabilities()

    @staticmethod
    def _kind(backend_kind: str) -> EndpointKind:
        return _KIND_MAP.get(backend_kind, EndpointKind.PIPEWIRE)

    def sinks(self) -> List[BackendSink]:
        return self.backend.list_sinks()

    def populate(
        self, engine: RoutingEngine, registry: DeviceRegistry
    ) -> RoutingEngine:
        """Discover the real audio graph and load it into the engine.

        Every id is derived from what the machine reports. Nothing about any
        specific pair of headphones is written down in this repository.
        """
        engine.add_source(
            Source(
                id=DEFAULT_SOURCE_ID,
                name="Default audio",
                kind=EndpointKind.VIRTUAL,
                backend_ref=None,
            ),
            replace=True,
        )

        for backend_sink in self.sinks():
            record = registry.register(
                name=backend_sink.name,
                address=backend_sink.address,
                backend_ref=backend_sink.ref,
                kind=backend_sink.kind,
            )
            engine.add_sink(
                Sink(
                    id=record.id,
                    name=backend_sink.name,
                    kind=self._kind(backend_sink.kind),
                    backend_ref=backend_sink.ref,
                    available=True,
                    metadata={
                        "default": str(backend_sink.is_default),
                        **backend_sink.metadata,
                    },
                ),
                replace=True,
            )
        return engine

    # ---------------------------------------------------------------- applying

    def apply(self, engine: RoutingEngine, source_id: str = DEFAULT_SOURCE_ID) -> str:
        """Make the OS match the graph. Returns a human-readable description.

        One sink  -> set it as the default output.
        Many sinks -> build a combined sink, if the platform allows it.
        """
        targets = engine.sinks_for(source_id, only_active=True)
        if not targets:
            raise NotSupported("no active sinks routed from " + source_id)

        if len(targets) == 1:
            self.backend.set_default_sink(targets[0].backend_ref or targets[0].id)
            return f"default output -> {targets[0].name}"

        caps = self.backend.capabilities()
        if not caps.get(Capability.COMBINE_SINKS_SCRIPTABLE):
            raise NotSupported(
                f"{self.backend.name} cannot build a multi-sink output "
                f"programmatically (wanted: {', '.join(t.name for t in targets)})"
            )
        offsets = {
            (t.backend_ref or t.id): t.latency_offset_ms
            for t in targets
            if t.latency_offset_ms
        }
        ref = self.backend.create_combine_sink(
            "audiohub_combine",
            [t.backend_ref or t.id for t in targets],
            offsets or None,
        )
        self.backend.set_default_sink(ref)
        return f"combined output -> {', '.join(t.name for t in targets)}"
