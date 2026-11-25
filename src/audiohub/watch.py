"""watch - keeps routed headphones going (the phase 5 monitor).

every few seconds it looks at which sinks exist right now:
- a routed sink that went away is marked lost, and we try to reconnect it.
  the wait between tries grows (5s, 10s, 20s ...) so we dont hammer the
  bluetooth controller, a tight loop can wedge it (see bluetooth.reconnect).
- when it comes back, the route is applied again by itself.

it never deletes a route. a switched off headphone is not a reason to forget it.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

from .backends import NotSupported
from .routing import RoutingEngine
from .state import DeviceState

BACKOFF = [5, 10, 20, 40, 60]  # seconds before the 1st, 2nd, 3rd ... reconnect try

# give up only when both are true. a laptop that slept for an hour has a long
# lost time but few tries, so it still gets its tries after it wakes up.
GIVE_UP_TRIES = 10
GIVE_UP_AFTER_S = 600


def should_give_up(tries: int, lost_for_s: float) -> bool:
    """should we stop trying to reconnect a headphone that is still gone?

    `tries` is how many reconnect attempts were made since it was lost.
    `lost_for_s` is how long it has been missing, in seconds.

    giving up only stops the retry loop. the route is always kept, and if
    the headphone is switched on again `step` notices and puts it back.
    """
    return tries >= GIVE_UP_TRIES and lost_for_s >= GIVE_UP_AFTER_S


def new_state() -> Dict[str, dict]:
    return {"lost": {}, "tries": {}, "next_try": {}, "gave_up": {}}


def _address_of(hub, sink_id: str) -> Optional[str]:
    saved = hub.config.sink(sink_id)
    return saved.address if saved else None


def _try_reconnect(hub, address: str):
    machine = hub.bluetooth.machine(address)
    if machine.is_recoverable:
        return hub.bluetooth.reconnect(address)
    return hub.bluetooth.connect(address)


def step(hub, st: Dict[str, dict], now: float) -> List[str]:
    """one look at the world. returns what happened, in plain words"""
    events: List[str] = []
    # build the graph fresh, so sinks that vanished really are gone from it
    hub.engine = RoutingEngine()
    hub.discover()
    missing = set(hub.restore_routes())
    hub.bluetooth.sync_states()
    changed = False

    for sink_id in sorted(missing - set(st["lost"])):
        st["lost"][sink_id] = now
        st["tries"][sink_id] = 0
        st["next_try"][sink_id] = now + BACKOFF[0]
        events.append(f"lost {sink_id}, will try to reconnect in {BACKOFF[0]}s")
        changed = True

    for sink_id in sorted(set(st["lost"]) - missing):
        gone_for = now - st["lost"].pop(sink_id)
        st["tries"].pop(sink_id, None)
        st["next_try"].pop(sink_id, None)
        st["gave_up"].pop(sink_id, None)
        events.append(f"{sink_id} is back after {gone_for:.0f}s")
        changed = True

    for sink_id in sorted(st["lost"]):
        if now < st["next_try"][sink_id]:
            continue
        address = _address_of(hub, sink_id)
        if not address:
            st["next_try"][sink_id] = float("inf")
            events.append(f"{sink_id} is not a bluetooth device, cant reconnect it, waiting for it to come back")
            continue
        ok, reason = _try_reconnect(hub, address)
        st["tries"][sink_id] += 1
        wait = BACKOFF[min(st["tries"][sink_id], len(BACKOFF) - 1)]
        st["next_try"][sink_id] = now + wait
        if ok:
            events.append(f"reconnected {sink_id}, waiting for its audio output to show up")
            continue

        tries, lost_for = st["tries"][sink_id], now - st["lost"][sink_id]
        if should_give_up(tries, lost_for):
            st["gave_up"][sink_id] = now
            st["next_try"][sink_id] = float("inf")
            hub.bluetooth.machine(address).force(
                DeviceState.FAILED, "gave up reconnecting"
            )
            events.append(
                f"giving up on {sink_id} after {tries} tries ({lost_for:.0f}s). "
                "route kept, switch the headphone on and it comes back"
            )
            continue

        events.append(f"reconnect {sink_id} failed ({reason}), next try in {wait}s")

    if changed:
        sources = sorted({src for src, _ in hub.config.routes})
        for source_id in sources:
            try:
                events.append("applied: " + hub.audio.apply(hub.engine, source_id))
            except NotSupported as exc:
                events.append(f"could not apply routes for {source_id}: {exc}")
    return events


def run(
    hub,
    interval: float = 5.0,
    steps: Optional[int] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    out: Callable[[str], None] = print,
) -> int:
    """loop until ctrl-c (or `steps` rounds, for tests)"""
    st = new_state()
    n = 0
    try:
        while steps is None or n < steps:
            for e in step(hub, st, clock()):
                out(time.strftime("%H:%M:%S ") + e)
            n += 1
            if steps is None or n < steps:
                sleep(interval)
    except KeyboardInterrupt:
        out("stopped")
    return 0
