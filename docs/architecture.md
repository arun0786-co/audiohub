# AudioHub architecture

## The question this architecture exists to answer

> Can one cheap software-defined router reliably distribute one audio stream to
> multiple Bluetooth headphones, synchronised well enough for movie watching?

Everything below is shaped so that answering that question does not require
buying anything, and so that a positive answer can be moved onto a cheap board
without a rewrite.

## Layers

```text
┌────────────────────────────────────────┐
│ CONTROL LAYER        cli.py            │  argparse, plain text, ssh-friendly
│                      (web UI later)    │
└────────────────────┬───────────────────┘
                     │
┌────────────────────▼───────────────────┐
│ ROUTING ENGINE      routing.py         │  pure graph, zero OS knowledge
│                     state.py           │  explicit device lifecycle
│                     devices.py         │  friendly name -> opaque ref
│                     config.py          │  JSON persistence
└────────────────────┬───────────────────┘
                     │
┌────────────────────▼───────────────────┐
│ AUDIO ENGINE        audio.py           │  discovery, fan-out, apply()
│                     latency.py         │  measurement maths, compensation
└────────────────────┬───────────────────┘
                     │
┌────────────────────▼───────────────────┐
│ BLUETOOTH CONTROL   bluetooth.py       │  connect/disconnect, state sync
└────────────────────┬───────────────────┘
                     │
┌────────────────────▼───────────────────┐
│ BACKENDS            backends/linux.py  │  PipeWire + BlueZ   (target)
│                     backends/macos.py  │  CoreAudio + Apple  (dev machine)
│                     backends/null.py   │  in-memory          (tests)
└────────────────────────────────────────┘
```

## The one rule that makes this portable

**The routing engine never learns what a sink is.**

`routing.py` imports nothing from `backends/`. It manipulates `Sink` objects
carrying an opaque `backend_ref` string it never interprets. Bluetooth, USB,
ALSA and a future network sink are all the same to it — which is what section 17
of the brief asks for, and what makes moving to an SBC a matter of verifying one
backend rather than rewriting the interesting code.

The consequence: the entire test suite runs with no audio hardware and no
Bluetooth, because `NullAudioBackend` satisfies the same contract the real ones
do.

## Backend contract

Two abstract classes in `backends/base.py`:

- `AudioBackend` — enumerate sinks/sources, set the default sink, build and tear
  down a combined sink, report capabilities.
- `BluetoothBackend` — controller info, device list, connect, disconnect.

`detect()` selects a pair at runtime from `platform.system()`, overridable with
`AUDIOHUB_BACKEND` for tests and CI.

### Capabilities are tri-state on purpose

`capabilities()` returns `True`, `False`, **or `None`**. `None` means *not yet
measured*. `audiohub doctor` prints it as `[?]`. This is a direct expression of
the project's measure-first rule: the system is not permitted to report a
synchronisation capability it has not demonstrated.

## Why a backend abstraction exists at all

Not architectural taste — a measured fact. The development machine for this
repository is macOS, and macOS and Linux differ on exactly the capability the
product depends on:

| Capability | Linux (PipeWire) | macOS (CoreAudio) |
|---|---|---|
| Enumerate sinks | yes | yes |
| Combine one source to many sinks | yes, `module-combine-sink` | yes, Multi-Output Device |
| **Create that combination programmatically** | **yes** | **no — Audio MIDI Setup only** |
| Per-sink delay | planned via `module-loopback` | unknown |

That last row is why Linux remains the target platform. macOS can *prove the
concept* at zero cost; only Linux can *be the product*.

## Failure handling

The contract, enforced by tests:

- A sink becoming unavailable **never mutates the routing graph.** Only
  `Sink.available` changes. The route survives so that reconnection restores it
  with no user action.
- A sink being absent when config is saved **never deletes its route.** `Hub`
  keeps absent routes aside and merges them back on save.
- `apply()` fans out to *active* sinks only, so one dead headphone does not stop
  the others.
- Every `DeviceState` can reach `FAILED` or `DISCONNECTED`. There are no dead
  ends, because the radio owes us nothing.
- `BluetoothService.connect()` returns `(ok, reason)` and never raises.
- Reconnection is deliberately dumb — one attempt per call, caller owns the
  backoff. A tight reconnect loop can wedge a controller, which is worse than a
  disconnected headphone.

## Future: the USB host layer (Phase 9, unbuilt)

Currently supported:

```text
Linux host ──► AudioHub ──► multiple Bluetooth sinks
```

Desired, and **not yet validated by any experiment**:

```text
Mac     ──USB Audio Class──┐
Windows ──USB Audio Class──┼──► AudioHub ──► multiple Bluetooth sinks
Debian  ──USB Audio Class──┘
```

The intended mechanism is the Linux **USB gadget** framework (`configfs` +
`f_uac2`), which makes a board with a USB device-capable port appear to a host
as an ordinary USB Audio Class device — no driver on the Mac, no driver on
Windows, no driver on Linux. Custom drivers are out of scope.

Two things must be true for this to work, and neither has been tested:

1. The eventual board must have a USB port that can act as a *device*, not only
   a host. This is a hard hardware constraint and it should drive board
   selection more than CPU speed does.
2. `f_uac2` must sustain several simultaneous host streams. Unknown.

In the engine this is already modelled: a USB host is just a `Source` with
`EndpointKind.USB`. No engine change is needed when the layer becomes real —
which is the point of building the abstraction now.

`audiohub mode personal` says so out loud rather than pretending, per section 15.

## Portability constraints held deliberately

- **Zero runtime dependencies.** Standard library only. The package installs on
  a stock Debian `python3` with no wheels to compile and no network.
- **`requires-python >= 3.9`**, so Debian Bullseye-era boards are not excluded.
- **Structured interfaces only** — `pw-dump` JSON, `pactl --format=json`,
  `busctl --json`, `system_profiler -json`. No scraping of human-readable
  output, per section 18. BlueZ is reached over D-Bus via `busctl` specifically
  to avoid a `python-dbus` build dependency on a slow board.
