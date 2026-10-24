"""Friendly-name registry: human handles -> opaque backend identifiers.

Users type `hesh`. The system needs a MAC address, or a node name like
`bluez_output.XX_XX_XX_XX_XX_XX.1`. Neither belongs on a command line,
and neither belongs hard-coded in this repository -- both are discovered at
runtime and remembered in the config file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
#: Noise words that make slugs long without making them distinguishable.
_NOISE = {"anc", "bluetooth", "bt", "audio", "headset", "headphones", "earbuds"}


def slugify(name: str, keep_noise: bool = False) -> str:
    """Turn a device name into a short, typeable handle.

        "Hesh ANC"   -> "hesh"
        "CB-EVOLVE"  -> "cb-evolve"

    Noise words are dropped only when something distinguishing survives -- a
    device literally called "Headset" must not slugify to the empty string.
    """
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    if not slug:
        return "device"
    if keep_noise:
        return slug
    parts = [p for p in slug.split("-") if p]
    kept = [p for p in parts if p not in _NOISE]
    return "-".join(kept) if kept else "-".join(parts)


@dataclass
class DeviceRecord:
    """One physical device as AudioHub knows it."""

    id: str
    name: str
    address: Optional[str] = None       # Bluetooth MAC, if applicable
    backend_ref: Optional[str] = None   # PipeWire node / CoreAudio UID
    kind: str = "bluetooth"
    metadata: Dict[str, str] = field(default_factory=dict)


class DeviceRegistry:
    """Assigns stable, unique, human-friendly ids to discovered devices.

    Stability matters: if `hesh` became `hesh-2` after a reboot, every saved
    route and every shell alias would break. Ids are therefore keyed on the
    device's hardware address wherever one exists.
    """

    def __init__(self) -> None:
        self._by_id: Dict[str, DeviceRecord] = {}
        self._key_to_id: Dict[str, str] = {}

    @staticmethod
    def _key(address: Optional[str], backend_ref: Optional[str], name: str) -> str:
        if address:
            return "addr:" + address.strip().upper()
        if backend_ref:
            return "ref:" + backend_ref
        return "name:" + name.strip().lower()

    def register(
        self,
        name: str,
        address: Optional[str] = None,
        backend_ref: Optional[str] = None,
        kind: str = "bluetooth",
        preferred_id: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> DeviceRecord:
        """Add or update a device. Re-registering the same hardware is a no-op
        on the id, so discovery can be run repeatedly without churn."""
        key = self._key(address, backend_ref, name)
        existing_id = self._key_to_id.get(key)
        if existing_id is not None:
            rec = self._by_id[existing_id]
            rec.name = name
            if address:
                rec.address = address
            if backend_ref:
                rec.backend_ref = backend_ref
            if metadata:
                rec.metadata.update(metadata)
            return rec

        base = preferred_id or slugify(name)
        device_id = self._unique(base)
        rec = DeviceRecord(
            id=device_id,
            name=name,
            address=address,
            backend_ref=backend_ref,
            kind=kind,
            metadata=dict(metadata or {}),
        )
        self._by_id[device_id] = rec
        self._key_to_id[key] = device_id
        return rec

    def _unique(self, base: str) -> str:
        if base not in self._by_id:
            return base
        n = 2
        while f"{base}-{n}" in self._by_id:
            n += 1
        return f"{base}-{n}"

    def get(self, device_id: str) -> Optional[DeviceRecord]:
        return self._by_id.get(device_id)

    def resolve(self, token: str) -> Optional[DeviceRecord]:
        """Look a device up by id, exact name, MAC, or unambiguous id prefix."""
        if token in self._by_id:
            return self._by_id[token]
        upper = token.strip().upper()
        for rec in self._by_id.values():
            if rec.address and rec.address.upper() == upper:
                return rec
        lower = token.strip().lower()
        for rec in self._by_id.values():
            if rec.name.lower() == lower:
                return rec
        prefixed = [r for r in self._by_id.values() if r.id.startswith(lower)]
        return prefixed[0] if len(prefixed) == 1 else None

    def all(self) -> List[DeviceRecord]:
        return sorted(self._by_id.values(), key=lambda r: r.id)

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, device_id: object) -> bool:
        return device_id in self._by_id
