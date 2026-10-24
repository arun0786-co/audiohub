# Experiments

Every entry records what was actually run and what actually came back.
**Nothing in this file may be an assumption.** Unmeasured quantities are written
as `not measured`, never as a plausible number.

---

## E0 — System audit

**Date:** 2026-09-15
**Question:** What does the development machine actually provide?
**Method:** Read-only. `uname`, `sw_vers`, `system_profiler -json`
(`SPAudioDataType`, `SPBluetoothDataType`), `arp -an`, tool presence checks.
Nothing installed, nothing modified.
**Cost:** ₹0

### Result: the development machine is not the machine the brief assumed

| | Assumed by brief | Actually found |
|---|---|---|
| OS | Debian-based Linux | macOS 15.7.7 (build 24G720) |
| Kernel | Linux | Darwin 24.6.0, `xnu-11417.140.69.710.16` |
| Arch | — | arm64, Apple T6041 (M4 Pro) |
| Audio server | PipeWire | CoreAudio |
| Session manager | WirePlumber | n/a |
| Bluetooth stack | BlueZ | Apple Bluetooth |
| ALSA | present | n/a |

No Debian machine was reachable: `~/.ssh/config` is empty and `known_hosts`
contains only GitHub and university hosts.

### Bluetooth controller

```text
Chipset:    BCM_4388C2 (Broadcom)
Vendor:     0x004C (Apple)
Address:    84:2F:57:xx:xx:xx  (hidden)
Firmware:   22.5.190.755
Transport:  PCIe
State:      On
Services:   HFP AVRCP A2DP HID Braille LEA AACP GATT SerialPort
```

Two findings from that block matter to the project:

- **A2DP is supported**, so multi-sink music output is at least conceivable here.
- **`LEA` — LE Audio is supported by the controller.** See the note below.

### Paired Bluetooth audio devices

Three usable audio sinks already exist, at ₹0. That is enough for the
three-sink Phase 5/6 experiment without buying anything.

| Name | Class | Connected at audit |
|---|---|---|
| Hesh ANC | Headset | no |
| CB-EVOLVE | Headset | no |
| CB-EVOLVE (second unit, distinct address) | Headset | no |
| Dell Mouse MS3320W | Mouse | no |

Addresses were discovered at runtime and are deliberately not recorded in the
repository; `tests/test_devices.py::test_no_hardcoded_addresses_in_source`
enforces that.

### Audio devices

| Name | In | Out | Transport | Default |
|---|---|---|---|---|
| MacBook Pro Microphone | 1 | — | builtin | input |
| MacBook Pro Speakers | — | 2 | builtin | output |
| Microsoft Teams Audio | 1 | 1 | virtual | — |

No aggregate or Multi-Output device was configured.

### Conclusion: a VM on this Mac cannot substitute for a Debian box

`Transport: PCIe`. Apple Silicon puts the Bluetooth controller on the internal
PCIe bus, not USB. VM USB passthrough — the normal way to give a Linux guest a
Bluetooth radio — has nothing to grab. Docker Desktop's Linux VM has neither
Bluetooth nor USB passthrough on macOS.

**A Linux VM on this Mac can validate the routing engine, the CLI and the state
machine. It can run no Bluetooth experiment whatsoever.** Phases 6 and 7 are
impossible there. This is worth knowing before building it.

### Note for later: LE Audio / Auracast

The controller reports `LEA`. LE Audio Broadcast (Auracast) is the standards-
based answer to "one source, many synchronised listeners" — it is designed for
this exact problem and provides genuine synchronised playback, unlike N
independent A2DP links. The headphones on hand almost certainly do not support
it. Recorded as a branch to investigate, **not** as a reason to buy anything.

---

## E1 — Multiple simultaneous Bluetooth A2DP sinks  (PROPOSED, not yet run)

**Status:** not run.
**Cost:** ₹0 — uses only hardware already owned.

**Question.** Can this machine hold three A2DP connections at once and play the
same stream to all of them? What is the relative offset between them, and does
it drift?

Why this experiment first: A2DP has **no multi-sink synchronisation
mechanism.** Each sink negotiates its own codec and buffer and runs on its own
crystal. Drift between sinks is a property of the protocol and the headphones,
not of the host audio server. So this is mostly *not* a PipeWire question, and
it is the riskiest assumption in the whole project.

If three sinks cannot hold sync on an Apple BCM4388 controller with Apple's own
stack, they will not hold sync on a ₹2,000 board with a cheap dongle. A negative
result here is cheap and saves building the entire Linux implementation first.

**Method.**

1. Power on all three headphones; connect each; record how many stay connected.
   *(Failure mode to watch for: the controller may drop one when the third
   connects, or silently downgrade a device to HFP.)*
2. If all three hold: build a Multi-Output Device in Audio MIDI Setup
   containing all three. Record whether macOS permits three Bluetooth members.
3. Play a test signal through it. Record whether all three produce audio.
4. Measure the relative offset — see the measurement note below.
5. Repeat the offset measurement after 30 and 60 minutes to estimate drift.
6. Disconnect one headphone mid-playback; record whether the others continue.

**Measurement.** A phone voice recorder placed between two headphone cups,
capturing a click track, is sufficient to resolve tens of milliseconds and costs
nothing. Load the recording into any waveform editor and measure the separation
between the two click onsets. `ffmpeg` is already installed for generating the
signal. The measurement rig is **not** part of the product architecture.

**Record here:** per-sink mean latency, jitter, max relative offset, drift over
one hour, and the reconnection behaviour.

```text
Hesh:        mean latency: not measured   jitter: not measured
Crossbeats1: mean latency: not measured   jitter: not measured
Crossbeats2: mean latency: not measured   jitter: not measured

Maximum relative offset: not measured
Drift over 1 h:          not measured
```

**Caveat to apply to whatever comes back.** macOS results are indicative, not
transferable. Different controller, different scheduler, different codec
negotiation. A positive result here means "worth building on Linux", not
"Linux will behave the same".
