"""Routing engine tests -- no hardware, no OS calls."""

from __future__ import annotations

import pytest

from audiohub.routing import (
    DuplicateEndpoint,
    EndpointKind,
    RoutingEngine,
    RoutingError,
    Sink,
    Source,
    UnknownSink,
    UnknownSource,
)


def test_single_route(engine):
    assert engine.connect("default", "hesh") is True
    assert engine.is_connected("default", "hesh")
    assert [s.id for s in engine.sinks_for("default")] == ["hesh"]


def test_multiple_routes(engine):
    added = engine.connect_many("default", ["hesh", "crossbeats"])
    assert added == ["hesh", "crossbeats"]
    assert [s.id for s in engine.sinks_for("default")] == ["crossbeats", "hesh"]


def test_duplicate_route_is_idempotent(engine):
    assert engine.connect("default", "hesh") is True
    assert engine.connect("default", "hesh") is False
    assert len(engine.routes()) == 1


def test_remove_route(engine):
    engine.connect_many("default", ["hesh", "crossbeats"])
    assert engine.disconnect("default", "hesh") is True
    assert engine.disconnect("default", "hesh") is False
    assert [s.id for s in engine.sinks_for("default")] == ["crossbeats"]


def test_disconnect_all(engine):
    engine.connect_many("default", ["hesh", "crossbeats", "speakers"])
    assert engine.disconnect_all("default") == 3
    assert engine.routes() == []


def test_sink_disconnect_preserves_route(engine):
    """Section 19: a headphone vanishing must not tear the graph down."""
    engine.connect_many("default", ["hesh", "crossbeats"])
    engine.set_available("crossbeats", False)

    assert engine.is_connected("default", "crossbeats"), "route must survive"
    assert [s.id for s in engine.sinks_for("default", only_active=True)] == ["hesh"]
    statuses = {r.sink_id: r for r in engine.route_statuses()}
    assert statuses["crossbeats"].active is False
    assert statuses["hesh"].active is True


def test_sink_reconnect_restores_without_reconfiguration(engine):
    engine.connect_many("default", ["hesh", "crossbeats"])
    engine.set_available("crossbeats", False)
    engine.set_available("crossbeats", True)
    assert [s.id for s in engine.sinks_for("default", only_active=True)] == [
        "crossbeats",
        "hesh",
    ]


def test_invalid_sink(engine):
    with pytest.raises(UnknownSink):
        engine.connect("default", "nonexistent")


def test_invalid_source(engine):
    with pytest.raises(UnknownSource):
        engine.connect("nonexistent", "hesh")


def test_connect_many_is_all_or_nothing(engine):
    """A typo in the last sink must not leave a half-applied route."""
    with pytest.raises(UnknownSink):
        engine.connect_many("default", ["hesh", "typo"])
    assert engine.routes() == []


def test_mute_excludes_sink_from_active_without_removing_route(engine):
    engine.connect_many("default", ["hesh", "crossbeats"])
    engine.mute("hesh")
    assert [s.id for s in engine.sinks_for("default", only_active=True)] == ["crossbeats"]
    assert engine.is_connected("default", "hesh")
    engine.unmute("hesh")
    assert len(engine.sinks_for("default", only_active=True)) == 2


def test_removing_sink_removes_its_edges(engine):
    engine.connect_many("default", ["hesh", "crossbeats"])
    engine.remove_sink("hesh")
    assert engine.routes() == [("default", "crossbeats")]
    with pytest.raises(UnknownSink):
        engine.get_sink("hesh")


def test_removing_source_removes_its_edges(engine):
    engine.connect_many("default", ["hesh"])
    engine.remove_source("default")
    assert engine.routes() == []


def test_duplicate_endpoint_rejected_unless_replacing(engine):
    with pytest.raises(DuplicateEndpoint):
        engine.add_sink(Sink(id="hesh", name="dup", kind=EndpointKind.BLUETOOTH))
    engine.add_sink(Sink(id="hesh", name="renamed", kind=EndpointKind.BLUETOOTH), replace=True)
    assert engine.get_sink("hesh").name == "renamed"


def test_negative_latency_offset_rejected(engine):
    with pytest.raises(RoutingError):
        engine.set_latency_offset("hesh", -5)


def test_engine_is_backend_agnostic(engine):
    """The engine must treat every sink kind identically (section 17)."""
    engine.connect_many("default", ["hesh", "speakers"])
    kinds = {s.kind for s in engine.sinks_for("default")}
    assert kinds == {EndpointKind.BLUETOOTH, EndpointKind.ALSA}
    assert len(engine.sinks_for("default", only_active=True)) == 2


def test_get_state_is_json_serialisable(engine):
    import json

    engine.connect_many("default", ["hesh", "crossbeats"])
    engine.set_latency_offset("hesh", 40)
    json.dumps(engine.get_state())  # must not raise


def test_many_sinks(engine):
    """Nothing in the engine caps sink count -- the radio does that, not us."""
    for i in range(16):
        engine.add_sink(Sink(id=f"s{i}", name=f"S{i}", kind=EndpointKind.BLUETOOTH))
    engine.connect_many("default", [f"s{i}" for i in range(16)])
    assert len(engine.sinks_for("default")) == 16
