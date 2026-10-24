# Limitations

What is actually known, and — more importantly — what is not. Anything not
demonstrated by an entry in `experiments.md` is listed here as unknown.

## Measured

| Property | Value | Source |
|---|---|---|
| Development machine OS | macOS 15.7.7, arm64 | E0 |
| Bluetooth controller | Broadcom BCM_4388C2, PCIe transport | E0 |
| A2DP supported by controller | yes | E0 |
| LE Audio (`LEA`) supported by controller | yes | E0 |
| Paired Bluetooth audio devices available | 3 | E0 |
| Bluetooth passthrough to a VM on this Mac | **impossible** (PCIe, not USB) | E0 |
| Unit tests passing without any hardware | 86 | test suite |

## Not measured — do not assume

- **Maximum simultaneous Bluetooth sinks.** Untested. Zero have been connected.
- **Synchronisation accuracy between sinks.** Untested. No claim is made.
- **Latency, jitter, drift.** Untested for every sink.
- **Reconnection behaviour under real radio failure.** Only simulated, in unit
  tests against an in-memory backend.
- **CPU and memory cost of fan-out.** Unmeasured on any platform, and therefore
  no statement can be made about whether a low-end SBC could carry it.
- **Codec negotiation.** Whether SBC/AAC/aptX is chosen per sink, and whether
  connecting a third device forces a codec or profile downgrade, is unknown.
- **Whether three A2DP sinks can even coexist** on this or any controller.

## Platform limitations

### macOS (development machine, not the target)

- **A Multi-Output Device cannot be created programmatically.** There is no
  supported CLI or public API for building an aggregate device; Audio MIDI Setup
  is the only route. `audiohub route` with multiple sinks therefore fails with a
  clear `NotSupported` on macOS. This is a platform fact, not a missing feature.
- Switching the default output requires `SwitchAudioSource`; connecting
  Bluetooth devices requires `blueutil`. Both are free Homebrew formulae, not
  installed. Without them AudioHub can enumerate but not actuate.
- Per-sink delay within a Multi-Output Device: unknown. macOS offers drift
  correction against a master device, not a settable per-member delay.

### Linux (target platform)

- **The entire Linux backend is UNVERIFIED.** It has never been executed
  against a real PipeWire or BlueZ host, because no such host was available. It
  is written against documented structured interfaces and is expected to need
  correction on first contact. `audiohub doctor` on a Debian box is the
  intended first test.
- `module-combine-sink` cannot apply per-sink delay. Phase 7 will need a null
  sink plus one `module-loopback` per sink, each with its own `latency_msec`.
  Deliberately not implemented until Phase 6 proves it is needed.

### Unsupported today

- **Multiple independent hosts.** One Linux/macOS host only. The USB Audio Class
  gadget layer described in `architecture.md` is designed but unbuilt and
  unvalidated. `audiohub mode personal` says so rather than faking it.
- **Network audio sinks.** Modelled in `EndpointKind`, not implemented.
- **Web UI.** Not started — CLI before GUI, section 20.
- **Pairing new devices.** AudioHub connects and disconnects already-paired
  devices; it does not run discovery or pairing.

## Known weaknesses in the current code

- `MacOSAudioBackend` uses the device *name* as its `backend_ref`, because
  `system_profiler` does not expose CoreAudio UIDs. Two identically-named output
  devices would therefore be indistinguishable to the backend. The two
  identically-named CB-EVOLVE headsets make this a realistic hazard, not a
  theoretical one. `DeviceRegistry` disambiguates them by address at the
  registry level, but the backend ref remains ambiguous.
- `LinuxAudioBackend._default_sink_name()` falls back to `None` when `pactl` is
  absent; the `wpctl` path is a stub.
- Reconnection has no backoff policy. Callers must supply one; nothing does yet.
- There is no daemon. Nothing monitors sink state between CLI invocations, so
  Phase 5's "detect disconnections and attempt reconnection" is currently a
  manual `audiohub status` rather than a running service.
