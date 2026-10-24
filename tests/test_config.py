from __future__ import annotations

import json

from audiohub import config as cfg


def test_defaults_when_no_file_exists():
    c = cfg.load()
    assert c.mode == "idle"
    assert c.routes == []
    assert c.version == cfg.CONFIG_VERSION


def test_configuration_persistence_roundtrip():
    c = cfg.Config(mode="movie")
    c.upsert_source(cfg.SourceConfig(id="default", name="Default audio"))
    c.upsert_sink(
        cfg.SinkConfig(
            id="hesh",
            name="Hesh ANC",
            address="AA:BB:CC:DD:EE:01",
            latency_offset_ms=40.0,
        )
    )
    c.add_route("default", "hesh")
    cfg.save(c)

    loaded = cfg.load()
    assert loaded.mode == "movie"
    assert loaded.routes == [["default", "hesh"]]
    assert loaded.sink("hesh").latency_offset_ms == 40.0
    assert loaded.sink("hesh").address == "AA:BB:CC:DD:EE:01"
    assert loaded.updated_at is not None


def test_add_route_is_idempotent():
    c = cfg.Config()
    assert c.add_route("default", "hesh") is True
    assert c.add_route("default", "hesh") is False
    assert c.remove_route("default", "hesh") is True
    assert c.remove_route("default", "hesh") is False


def test_upsert_replaces_rather_than_duplicating():
    c = cfg.Config()
    c.upsert_sink(cfg.SinkConfig(id="hesh", name="old"))
    c.upsert_sink(cfg.SinkConfig(id="hesh", name="new"))
    assert len(c.sinks) == 1
    assert c.sink("hesh").name == "new"


def test_corrupt_config_is_quarantined_not_lost():
    path = cfg.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json at all", encoding="utf-8")

    loaded = cfg.load()
    assert loaded.mode == "idle", "must fall back to defaults"
    quarantined = list(path.parent.glob("config.corrupt.*.json"))
    assert quarantined, "the unreadable file must be preserved, not overwritten"
    assert "not json" in quarantined[0].read_text()


def test_save_is_atomic_and_leaves_no_temp_files():
    cfg.save(cfg.Config(mode="movie"))
    leftovers = list(cfg.config_dir().glob(".config-*"))
    assert leftovers == []


def test_unknown_future_keys_do_not_crash_load():
    path = cfg.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "mode": "movie", "future": 1}))
    assert cfg.load().mode == "movie"
