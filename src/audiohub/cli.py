"""AudioHub command line.

CLI before GUI (section 20). Plain argparse, plain text, no colour libraries --
this has to run over ssh on a headless board.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from typing import Dict, List, Optional, Sequence, Tuple

from . import __version__, config as config_mod
from .audio import DEFAULT_SOURCE_ID, AudioService
from .backends import Capability, NotSupported, detect, platform_name
from .bluetooth import BluetoothService
from .devices import DeviceRegistry
from .latency import MOVIE_RELATIVE_OFFSET_TARGET_MS, max_relative_offset
from .routing import RoutingEngine, RoutingError, UnknownSink, UnknownSource

OK, NO, UNKNOWN = "[✓]", "[✗]", "[?]"


class Hub:
    """Wires config, discovery and the routing engine together."""

    def __init__(self) -> None:
        audio_backend, bt_backend = detect()
        self.audio = AudioService(audio_backend)
        self.bluetooth = BluetoothService(bt_backend)
        self.registry = DeviceRegistry()
        self.engine = RoutingEngine()
        self.config = config_mod.load()
        #: Saved routes whose sink is not present right now. Held aside so that
        #: persisting does not amount to forgetting a switched-off headphone.
        self.missing_routes: List[List[str]] = []

    def discover(self) -> "Hub":
        self.audio.populate(self.engine, self.registry)
        return self

    def restore_routes(self) -> List[str]:
        """Re-apply saved routes, reporting sinks that are no longer present.

        A saved route to an absent sink is kept in config -- the headphone may
        simply be switched off -- but it is not silently pretended into the
        graph.
        """
        self.missing_routes = []
        missing = []
        for source_id, sink_id in self.config.routes:
            try:
                self.engine.connect(source_id, sink_id)
            except (UnknownSource, UnknownSink):
                self.missing_routes.append([source_id, sink_id])
                missing.append(sink_id)
        for saved in self.config.sinks:
            try:
                self.engine.set_latency_offset(saved.id, saved.latency_offset_ms)
                if saved.muted:
                    self.engine.mute(saved.id)
            except UnknownSink:
                continue
        return missing

    def forget_route(self, source_id: str, sink_id: str) -> bool:
        """Delete a route the user explicitly asked to remove.

        Works whether or not the sink is currently present -- otherwise an
        absent headphone could never be unrouted.
        """
        pair = [source_id, sink_id]
        removed = False
        if pair in self.missing_routes:
            self.missing_routes.remove(pair)
            removed = True
        try:
            removed = self.engine.disconnect(source_id, sink_id) or removed
        except (UnknownSource, UnknownSink):
            pass
        return removed

    def forget_source_routes(self, source_id: str) -> int:
        removed = len([r for r in self.missing_routes if r[0] == source_id])
        self.missing_routes = [r for r in self.missing_routes if r[0] != source_id]
        try:
            removed += self.engine.disconnect_all(source_id)
        except UnknownSource:
            pass
        return removed

    def persist(self) -> None:
        """Save state, preserving routes whose sink happens to be switched off.

        A sink being absent is a temporary fact about the world, not an
        instruction to delete the user's configuration (section 19).
        """
        routes = [[a, b] for a, b in self.engine.routes()]
        for pair in self.missing_routes:
            if pair not in routes:
                routes.append(pair)
        self.config.routes = sorted(routes)
        for sink in self.engine.sinks():
            self.config.upsert_sink(
                config_mod.SinkConfig(
                    id=sink.id,
                    name=sink.name,
                    kind=sink.kind.value,
                    address=sink.metadata.get("address"),
                    backend_ref=sink.backend_ref,
                    muted=sink.muted,
                    latency_offset_ms=sink.latency_offset_ms,
                    measured_latency_ms=sink.measured_latency_ms,
                )
            )
        config_mod.save(self.config)


# --------------------------------------------------------------------- output


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return "  (none)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()
    sep = "-" * len(line)
    body = [
        "  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip() for row in rows
    ]
    return "\n".join([line, sep, *body])


def _flag(value: Optional[bool]) -> str:
    if value is True:
        return OK
    if value is False:
        return NO
    return UNKNOWN


# -------------------------------------------------------------------- doctor


def cmd_doctor(args: argparse.Namespace) -> int:
    hub = Hub()
    audio, bt = hub.audio, hub.bluetooth
    server = audio.backend.server_info()
    caps = audio.capabilities()

    lines: List[str] = ["AudioHub System Diagnostics", ""]
    lines.append(f"OS:            {platform.platform()}")
    lines.append(f"Kernel:        {platform.system()} {platform.release()}")
    lines.append(f"Arch:          {platform.machine()}")
    lines.append(f"Python:        {platform.python_version()}")
    lines.append(f"Backend:       {audio.backend.name} / {bt.backend.name}"
                 f"  (platform={platform_name()})")
    lines.append("")

    if platform_name() == "linux":
        lines.append(f"PipeWire:      {server.get('pipewire') or 'not found'}")
        lines.append(f"WirePlumber:   {server.get('wireplumber') or 'not found'}")
        lines.append(f"Pulse compat:  {server.get('pulse_compat') or 'not found'}")
        lines.append(f"ALSA:          {server.get('alsa') or 'not found'}")
    else:
        lines.append(f"Audio Server:  {server.get('server', 'unknown')}")
        lines.append("PipeWire:      n/a on this platform")
        lines.append("WirePlumber:   n/a on this platform")
        lines.append("BlueZ:         n/a on this platform")
        lines.append("ALSA:          n/a on this platform")
    lines.append("")

    if bt.available():
        info = bt.backend.controller_info()
        lines.append(f"Bluetooth Controller: {info.chipset or info.name or 'unknown'}")
        lines.append(f"Bluetooth Address:    {info.address or 'unknown'}")
        lines.append(f"Bluetooth Transport:  {info.transport or 'unknown'}")
        lines.append(f"Bluetooth Firmware:   {info.firmware or 'unknown'}")
        lines.append(f"Bluetooth Powered:    {info.powered}")
        if info.services:
            lines.append(f"Bluetooth Services:   {' '.join(info.services)}")
    else:
        lines.append("Bluetooth Controller: UNAVAILABLE (no supported backend)")
    lines.append("")

    hub.discover()
    sink_rows = [
        [s.id, s.name, s.kind.value, s.metadata.get("default", "False")]
        for s in hub.engine.sinks()
    ]
    lines.append("Audio Sinks:")
    lines.append(_table(["ID", "NAME", "KIND", "DEFAULT"], sink_rows))
    lines.append("")
    src_rows = [[s.name, s.kind] for s in audio.backend.list_sources()]
    lines.append("Audio Sources:")
    lines.append(_table(["NAME", "KIND"], src_rows))
    lines.append("")

    bt_devices = bt.audio_devices() if bt.available() else []
    lines.append("Bluetooth Audio Devices (paired):")
    lines.append(
        _table(
            ["NAME", "ADDRESS", "CLASS", "CONNECTED"],
            [
                [d.name, d.address, d.device_class or "?", "yes" if d.connected else "no"]
                for d in bt_devices
            ],
        )
    )
    lines.append("")

    connected_bt_sinks = [s for s in hub.engine.sinks() if s.kind.value == "bluetooth"]
    lines.append("Capabilities:")
    lines.append(f"  {_flag(audio.available())} Audio backend ({audio.backend.name})")
    lines.append(f"  {_flag(bt.available())} Bluetooth backend ({bt.backend.name})")
    lines.append(f"  {_flag(caps.get(Capability.A2DP))} A2DP")
    lines.append(f"  {_flag(caps.get(Capability.ENUMERATE_SINKS))} Enumerate sinks")
    lines.append(f"  {_flag(caps.get(Capability.SET_DEFAULT_SINK))} Switch default sink")
    lines.append(f"  {_flag(caps.get(Capability.COMBINE_SINKS))} Multiple sinks (OS supports combining)")
    lines.append(
        f"  {_flag(caps.get(Capability.COMBINE_SINKS_SCRIPTABLE))} "
        "Multiple sinks, created programmatically"
    )
    lines.append(f"  {_flag(caps.get(Capability.PER_SINK_DELAY))} Per-sink delay (Phase 7)")
    lines.append(
        f"  {_flag(len(connected_bt_sinks) >= 2 if connected_bt_sinks else None)} "
        f"Multiple simultaneous Bluetooth sinks "
        f"({len(connected_bt_sinks)} currently present as audio sinks)"
    )
    lines.append("")
    lines.append(
        "  [?] means not yet measured. Run the Phase 6 experiment before\n"
        "      believing anything about synchronisation."
    )

    out = "\n".join(lines)
    if args.json:
        print(
            json.dumps(
                {
                    "platform": platform_name(),
                    "os": platform.platform(),
                    "backends": {"audio": audio.backend.name, "bluetooth": bt.backend.name},
                    "server": server,
                    "capabilities": {k.value: v for k, v in caps.items()},
                    "state": hub.engine.get_state(),
                    "bluetooth_devices": [
                        {
                            "name": d.name,
                            "address": d.address,
                            "connected": d.connected,
                            "class": d.device_class,
                        }
                        for d in bt_devices
                    ],
                },
                indent=2,
            )
        )
    else:
        print(out)
    return 0


# ------------------------------------------------------------------- devices


def cmd_devices(args: argparse.Namespace) -> int:
    hub = Hub().discover()
    bt = hub.bluetooth

    if args.json:
        print(
            json.dumps(
                {
                    "bluetooth": [
                        {
                            "name": d.name,
                            "address": d.address,
                            "connected": d.connected,
                            "paired": d.paired,
                        }
                        for d in bt.audio_devices()
                    ],
                    "sinks": hub.engine.get_state()["sinks"],
                },
                indent=2,
            )
        )
        return 0

    print("Bluetooth devices\n")
    rows = []
    for i, d in enumerate(bt.audio_devices()):
        rows.append([f"bt{i}", d.name, d.address, "yes" if d.connected else "no"])
    print(_table(["ID", "NAME", "ADDRESS", "CONNECTED"], rows))

    print("\nAudio sinks\n")
    print(
        _table(
            ["ID", "NAME", "KIND", "DEFAULT"],
            [
                [s.id, s.name, s.kind.value, "yes" if s.metadata.get("default") == "True" else ""]
                for s in hub.engine.sinks()
            ],
        )
    )
    return 0


# ------------------------------------------------------- connect / disconnect


def _resolve_bt(hub: Hub, token: str):
    lower = token.strip().lower()
    for dev in hub.bluetooth.audio_devices():
        if dev.address.upper() == token.strip().upper():
            return dev
        if dev.name.lower() == lower:
            return dev
    from .devices import slugify

    matches = [d for d in hub.bluetooth.audio_devices() if slugify(d.name) == lower]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(
            f"'{token}' is ambiguous -- {len(matches)} devices match. "
            "Use the full address.",
            file=sys.stderr,
        )
    return None


def cmd_connect(args: argparse.Namespace) -> int:
    hub = Hub()
    dev = _resolve_bt(hub, args.device)
    if dev is None:
        print(f"no paired Bluetooth audio device matches {args.device!r}", file=sys.stderr)
        return 2
    ok, reason = hub.bluetooth.connect(dev.address)
    print(f"{dev.name}: {reason}")
    return 0 if ok else 1


def cmd_disconnect(args: argparse.Namespace) -> int:
    hub = Hub()
    dev = _resolve_bt(hub, args.device)
    if dev is None:
        print(f"no paired Bluetooth audio device matches {args.device!r}", file=sys.stderr)
        return 2
    ok, reason = hub.bluetooth.disconnect(dev.address)
    print(f"{dev.name}: {reason}")
    return 0 if ok else 1


# --------------------------------------------------------------------- route


def cmd_route(args: argparse.Namespace) -> int:
    hub = Hub().discover()
    hub.restore_routes()
    source = args.source

    try:
        hub.engine.get_source(source)
    except UnknownSource:
        print(
            f"unknown source {source!r}. Known: "
            f"{', '.join(s.id for s in hub.engine.sources())}",
            file=sys.stderr,
        )
        return 2

    unknown = [s for s in args.sinks if s not in [k.id for k in hub.engine.sinks()]]
    if unknown:
        print(f"unknown sink(s): {', '.join(unknown)}", file=sys.stderr)
        print(
            "known sinks: " + ", ".join(s.id for s in hub.engine.sinks()),
            file=sys.stderr,
        )
        return 2

    if args.replace:
        hub.engine.disconnect_all(source)
    hub.engine.connect_many(source, args.sinks)

    try:
        description = hub.audio.apply(hub.engine, source)
        print(description)
    except NotSupported as exc:
        print(f"route saved, but not applied: {exc}", file=sys.stderr)
        hub.persist()
        return 3
    hub.persist()
    return 0


def cmd_unroute(args: argparse.Namespace) -> int:
    hub = Hub().discover()
    hub.restore_routes()
    if args.sinks:
        removed = sum(hub.forget_route(args.source, s) for s in args.sinks)
    else:
        removed = hub.forget_source_routes(args.source)
    hub.persist()
    print(f"removed {removed} route(s)")
    return 0


# -------------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    hub = Hub().discover()
    missing = hub.restore_routes()
    hub.bluetooth.sync_states()
    state = hub.engine.get_state()

    if args.json:
        print(json.dumps({"mode": hub.config.mode, "missing_sinks": missing, **state}, indent=2))
        return 0

    print("AudioHub\n")
    print(f"MODE: {hub.config.mode.upper()}\n")
    print("SOURCE")
    for s in hub.engine.sources():
        print(f"  ● {s.name} ({s.id})")
    print("\nOUTPUTS")
    statuses = hub.engine.route_statuses()
    if not statuses:
        print("  (no routes configured)")
    for r in statuses:
        mark = "✓" if r.active else "✗"
        offset = f"  +{r.latency_offset_ms:.0f} ms" if r.latency_offset_ms else ""
        note = "" if r.available else "  (unavailable)"
        note += "  (muted)" if r.muted else ""
        print(f"  {mark} {r.sink_name}{offset}{note}")
    if missing:
        print(
            "\n  Saved routes whose sink is not currently present: "
            + ", ".join(sorted(set(missing)))
        )

    measured = {
        s.id: s.measured_latency_ms
        for s in hub.engine.sinks()
        if s.measured_latency_ms is not None
    }
    print("\nSYNCHRONISATION")
    if len(measured) < 2:
        print("  not measured -- run the Phase 6 experiment (docs/experiments.md)")
    else:
        spread = max_relative_offset(measured)
        verdict = "within" if spread <= MOVIE_RELATIVE_OFFSET_TARGET_MS else "OVER"
        print(f"  max relative offset: {spread:.1f} ms "
              f"({verdict} the {MOVIE_RELATIVE_OFFSET_TARGET_MS:.0f} ms movie target)")
    return 0


# ----------------------------------------------------------------- mute/mode


def cmd_mute(args: argparse.Namespace) -> int:
    hub = Hub().discover()
    hub.restore_routes()
    try:
        hub.engine.mute(args.sink) if not args.unmute else hub.engine.unmute(args.sink)
    except UnknownSink as exc:
        print(str(exc), file=sys.stderr)
        return 2
    hub.persist()
    print(f"{args.sink}: {'unmuted' if args.unmute else 'muted'}")
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    hub = Hub().discover()
    hub.restore_routes()
    if args.mode == "personal":
        print(
            "personal mode models host -> sink routing, but this prototype has "
            "exactly one host (itself).\n"
            "Independent streams from a Mac and a Windows box need the USB "
            "gadget host layer described in docs/architecture.md, which no\n"
            "experiment has validated yet. Not faking it."
        )
    hub.config.mode = args.mode
    hub.persist()
    print(f"mode: {args.mode}")
    return 0


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audiohub",
        description="Route one audio source to many sinks.",
    )
    p.add_argument("--version", action="version", version=f"audiohub {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="report system capabilities (read-only)")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)

    dv = sub.add_parser("devices", help="list Bluetooth devices and audio sinks")
    dv.add_argument("--json", action="store_true")
    dv.set_defaults(func=cmd_devices)

    c = sub.add_parser("connect", help="connect a Bluetooth device")
    c.add_argument("device")
    c.set_defaults(func=cmd_connect)

    dc = sub.add_parser("disconnect", help="disconnect a Bluetooth device")
    dc.add_argument("device")
    dc.set_defaults(func=cmd_disconnect)

    r = sub.add_parser("route", help="route a source to one or more sinks")
    r.add_argument("source")
    r.add_argument("sinks", nargs="+")
    r.add_argument(
        "--replace",
        action="store_true",
        help="drop this source's existing routes first",
    )
    r.set_defaults(func=cmd_route)

    u = sub.add_parser("unroute", help="remove routes")
    u.add_argument("source", nargs="?", default=DEFAULT_SOURCE_ID)
    u.add_argument("sinks", nargs="*")
    u.set_defaults(func=cmd_unroute)

    s = sub.add_parser("status", help="show current routing state")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    m = sub.add_parser("mute", help="mute a sink")
    m.add_argument("sink")
    m.add_argument("--unmute", action="store_true")
    m.set_defaults(func=cmd_mute)

    um = sub.add_parser("unmute", help="unmute a sink")
    um.add_argument("sink")
    um.set_defaults(func=cmd_mute, unmute=True)

    md = sub.add_parser("mode", help="switch operating mode")
    md.add_argument("mode", choices=["idle", "movie", "personal"])
    md.set_defaults(func=cmd_mode)

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "unmute"):
        args.unmute = False
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except NotSupported as exc:
        print(f"unsupported on this platform: {exc}", file=sys.stderr)
        return 3
    except RoutingError as exc:
        print(f"routing error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
