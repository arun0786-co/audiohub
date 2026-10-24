from __future__ import annotations

from audiohub.devices import DeviceRegistry, slugify


def test_slugify_produces_typeable_handles():
    assert slugify("Hesh ANC") == "hesh"
    assert slugify("CB-EVOLVE") == "cb-evolve"
    assert slugify("MacBook Pro Speakers") == "macbook-pro-speakers"


def test_slugify_never_returns_empty():
    """A device called only by a noise word must still get a handle."""
    assert slugify("Headset") == "headset"
    assert slugify("!!!") == "device"
    assert slugify("") == "device"


def test_duplicate_names_get_distinct_ids():
    """Two identically-named earbuds is the real case on this hardware."""
    r = DeviceRegistry()
    a = r.register("CB-EVOLVE", address="00:14:BE:00:00:01")
    b = r.register("CB-EVOLVE", address="00:14:BE:00:00:02")
    assert a.id != b.id
    assert {a.id, b.id} == {"cb-evolve", "cb-evolve-2"}


def test_reregistering_the_same_hardware_keeps_the_id_stable():
    """Ids must survive rediscovery, or every saved route would break."""
    r = DeviceRegistry()
    first = r.register("Hesh ANC", address="AA:BB:CC:DD:EE:01")
    again = r.register("Hesh ANC", address="AA:BB:CC:DD:EE:01", backend_ref="node.7")
    assert first.id == again.id
    assert len(r) == 1
    assert again.backend_ref == "node.7"


def test_id_is_keyed_on_address_not_name():
    r = DeviceRegistry()
    first = r.register("Hesh ANC", address="AA:BB:CC:DD:EE:01")
    renamed = r.register("Arun's Hesh", address="AA:BB:CC:DD:EE:01")
    assert renamed.id == first.id, "renaming a device must not orphan its routes"
    assert renamed.name == "Arun's Hesh"


def test_resolve_by_id_name_address_and_prefix():
    r = DeviceRegistry()
    r.register("Hesh ANC", address="AA:BB:CC:DD:EE:01")
    assert r.resolve("hesh").id == "hesh"
    assert r.resolve("Hesh ANC").id == "hesh"
    assert r.resolve("aa:bb:cc:dd:ee:01").id == "hesh"
    assert r.resolve("he").id == "hesh"
    assert r.resolve("nope") is None


def test_ambiguous_prefix_resolves_to_nothing():
    r = DeviceRegistry()
    r.register("CB-EVOLVE", address="00:14:BE:00:00:01")
    r.register("CB-EVOLVE", address="00:14:BE:00:00:02")
    assert r.resolve("cb") is None, "ambiguity must not silently pick one"


def test_no_hardcoded_addresses_in_source():
    """Section 9: my headphones' MAC addresses must not be in the repository."""
    import pathlib
    import re

    mac = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    offenders = []
    for py in src.rglob("*.py"):
        for m in mac.findall(py.read_text(encoding="utf-8")):
            if m.upper() not in {"00:00:00:00:00:00"}:  # null backend placeholder
                offenders.append(f"{py.name}: {m}")
    assert not offenders, f"hard-coded MAC addresses found: {offenders}"
