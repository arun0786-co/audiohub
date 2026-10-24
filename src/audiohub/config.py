"""Persistent configuration.

Plain JSON in an XDG directory. No database, no config library, no schema
framework -- all of which would cost bytes and build time on a cheap SBC and
buy us nothing at this size.

Corruption is handled by refusing to lose data: a config that will not parse is
moved aside rather than overwritten, so a bad write never silently discards a
working setup.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_VERSION = 1
_ENV_DIR = "AUDIOHUB_CONFIG_DIR"


def config_dir() -> Path:
    """Where config lives. Overridable via AUDIOHUB_CONFIG_DIR (used by tests)."""
    override = os.environ.get(_ENV_DIR)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "audiohub"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class SinkConfig:
    """A remembered sink. Addresses are discovered, never hard-coded."""

    id: str
    name: str
    kind: str = "bluetooth"
    address: Optional[str] = None
    backend_ref: Optional[str] = None
    enabled: bool = True
    muted: bool = False
    latency_offset_ms: float = 0.0
    measured_latency_ms: Optional[float] = None


@dataclass
class SourceConfig:
    id: str
    name: str
    kind: str = "virtual"
    backend_ref: Optional[str] = None


@dataclass
class Config:
    version: int = CONFIG_VERSION
    mode: str = "idle"                                  # idle | movie | personal
    sources: List[SourceConfig] = field(default_factory=list)
    sinks: List[SinkConfig] = field(default_factory=list)
    routes: List[List[str]] = field(default_factory=list)   # [source_id, sink_id]
    #: Phase 8 host map: logical host -> sink id. Modelled now, not faked.
    host_routes: Dict[str, str] = field(default_factory=dict)
    updated_at: Optional[float] = None

    # ------------------------------------------------------------ (de)serialise

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["routes"] = [list(r) for r in self.routes]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        return cls(
            version=int(data.get("version", CONFIG_VERSION)),
            mode=str(data.get("mode", "idle")),
            sources=[SourceConfig(**s) for s in data.get("sources", [])],
            sinks=[SinkConfig(**s) for s in data.get("sinks", [])],
            routes=[list(r) for r in data.get("routes", []) if len(r) == 2],
            host_routes=dict(data.get("host_routes", {})),
            updated_at=data.get("updated_at"),
        )

    # ------------------------------------------------------------------ lookup

    def sink(self, sink_id: str) -> Optional[SinkConfig]:
        return next((s for s in self.sinks if s.id == sink_id), None)

    def source(self, source_id: str) -> Optional[SourceConfig]:
        return next((s for s in self.sources if s.id == source_id), None)

    def upsert_sink(self, sink: SinkConfig) -> None:
        for i, existing in enumerate(self.sinks):
            if existing.id == sink.id:
                self.sinks[i] = sink
                return
        self.sinks.append(sink)

    def upsert_source(self, source: SourceConfig) -> None:
        for i, existing in enumerate(self.sources):
            if existing.id == source.id:
                self.sources[i] = source
                return
        self.sources.append(source)

    def add_route(self, source_id: str, sink_id: str) -> bool:
        pair = [source_id, sink_id]
        if pair in self.routes:
            return False
        self.routes.append(pair)
        return True

    def remove_route(self, source_id: str, sink_id: str) -> bool:
        pair = [source_id, sink_id]
        if pair not in self.routes:
            return False
        self.routes.remove(pair)
        return True


class ConfigError(Exception):
    pass


def load(path: Optional[Path] = None) -> Config:
    """Load config, returning defaults when absent.

    A corrupt file is quarantined (renamed with a timestamp) rather than
    deleted, and defaults are returned so the CLI still runs.
    """
    p = path or config_path()
    if not p.exists():
        return Config()
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        quarantine = p.with_suffix(f".corrupt.{int(time.time())}.json")
        try:
            shutil.move(str(p), str(quarantine))
        except OSError:
            pass
        return Config()
    if not isinstance(data, dict):
        return Config()
    try:
        return Config.from_dict(data)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"config at {p} has unexpected shape: {exc}") from exc


def save(cfg: Config, path: Optional[Path] = None) -> Path:
    """Write config atomically, so an interrupted write cannot truncate it."""
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cfg.updated_at = time.time()
    payload = json.dumps(cfg.to_dict(), indent=2, sort_keys=True) + "\n"

    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".config-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p
