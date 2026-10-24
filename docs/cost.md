# Cost accounting

Cost minimisation is a primary engineering objective, not an afterthought.
Running total for the project so far:

## **₹0**

## Software

| Item | Cost | Notes |
|---|---|---|
| Python 3 (stdlib only) | ₹0 | already installed |
| PipeWire / WirePlumber | ₹0 | ships with Debian; not yet used |
| BlueZ | ₹0 | ships with Debian; not yet used |
| ALSA | ₹0 | ships with Debian; not yet used |
| CoreAudio / Apple Bluetooth | ₹0 | ships with macOS |
| `system_profiler`, `busctl`, `pactl`, `pw-dump` | ₹0 | OS-provided |
| ffmpeg (test signal generation) | ₹0 | already installed |
| pytest | ₹0 | dev-only, not shipped |
| External APIs / cloud services | ₹0 | **none, by design — fully offline** |

**Runtime dependencies: zero.** This is enforced in `pyproject.toml` and is a
cost decision, not a style one: no wheels to compile on a slow board, no
network needed at install time, no supply chain to audit.

## Hardware

| Item | Cost | Notes |
|---|---|---|
| Existing MacBook Pro | ₹0 | already owned |
| Hesh ANC | ₹0 | already owned |
| CB-EVOLVE ×2 | ₹0 | already owned |
| Prototype SBC | **not required yet** | no experiment justifies it |
| USB Bluetooth adapters | **not required yet** | — |
| DAC / microphone / display / PCB / battery / enclosure | **not required** | — |

Three Bluetooth audio sinks are already owned, which is exactly enough for the
three-sink Phase 5/6 experiment. **No hardware purchase is justified today.**

## Measurement rig

The Phase 6 latency measurement needs a recording device. A phone voice
recorder resolves tens of milliseconds and costs ₹0. This is measurement
apparatus and is explicitly **not** part of the product architecture — no
microphone belongs in the shipped device.

## Free software that would extend what AudioHub can do on macOS

Not installed. Listed for honesty about what is currently blocked. Both are
free and open source; neither is needed on the Linux target.

| Item | Cost | Unlocks |
|---|---|---|
| `switchaudio-osx` | ₹0 | switching the default output from the CLI |
| `blueutil` | ₹0 | connecting/disconnecting Bluetooth from the CLI |

## The test every new dependency must pass

> Can the existing OS or standard library already provide this capability?

Applied so far:

| Temptation | Rejected in favour of | Saving |
|---|---|---|
| `click` / `typer` | `argparse` | one dependency |
| `rich` | plain text tables | one dependency, and it works over ssh |
| `python-dbus` / `pydbus` | `busctl --json` | a compiled dependency on a slow board |
| `pydantic` | `dataclasses` + `json` | a large dependency for ~200 lines of config |
| A database | one JSON file | a whole subsystem |
| Docker for the Linux test | — | see below |

## Hardware decisions deliberately deferred

No SBC has been chosen, and none should be until E1 produces a result. If
Phase 6 shows that multi-sink A2DP cannot hold sync, the cheapest correct
outcome is **to buy nothing at all** and reconsider the approach — for example
LE Audio Broadcast, which would change the hardware requirements completely.

One hardware constraint is already known and should dominate board selection
when the time comes: the board needs a **USB port that can act as a device**,
not only a host, or the Phase 9 USB Audio Class plan is impossible. That
matters more than CPU speed.

A note on the obvious ₹0 workaround: running Debian in a VM on the Mac **cannot
test Bluetooth**, because this Mac's controller is on internal PCIe with no
passthrough path (see `experiments.md`, E0). It would validate the software and
prove nothing about the product.
