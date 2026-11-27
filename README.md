# AudioHub

one sound source, many bluetooth headphones.

the idea: a very cheap box that sits between computers and bluetooth headphones. like a few friends watching one movie, each with their own earbuds. or one person sending different computers to different headsets, without touching bluetooth settings every time.

right now this is only the **software part**. no hardware is bought yet, and it should not be bought before the experiments say its worth it. cost so far: **₹0** (`docs/cost.md`).

## status

| phase | state |
| --- | --- |
| 0 - look at the repo | done |
| 1 - system check (`audiohub doctor`) | done, works on mac and linux |
| 2 - find devices (`audiohub devices`) | done |
| 3 - one source to one headphone | done in code, not tried with real bluetooth yet |
| 4 - one source to many headphones | done in code, **not tried yet** |
| 5 - movie mode + keep headphones connected (`audiohub watch`) | done in code, not tried with real bluetooth yet |
| 6 - measure if the headphones are in sync | tool done (`audiohub measure`), **not measured yet** - this is the next real experiment |
| 7 - fix the delay between headphones | maths done, waiting for phase 6 |
| 8/9 - personal mode, usb host part | planned, not built |
| web page | not started (command line first) |

the big open question is phase 6: are the headphones in sync enough to watch a movie? nothing here claims an answer yet. see `docs/experiments.md`.

## note: my laptop is not the target

the plan was a debian linux box with pipewire and bluez. i made it on a mac (coreaudio). both backends are written but only the mac one has touched real hardware. **the linux part is not tested yet**, see `docs/limitations.md`.

## install

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
```

no extra libraries, only python 3.9+ standard library, so it installs on a normal debian `python3`.

## use

```bash
audiohub doctor                          # what can this machine do (read only)
audiohub devices                         # bluetooth devices and audio outputs
audiohub connect hesh                    # connect a paired headphone
audiohub route default hesh              # one source -> one headphone
audiohub route default hesh crossbeats   # one source -> many headphones
audiohub status                          # what is routed where
audiohub watch                           # keeps routed headphones connected
audiohub mode movie
```

device names come from what the system finds. no MAC address is written in the code (a test checks that).

### watch

`audiohub watch` checks every 5 seconds. if a routed headphone drops out (switched off, battery dead, walked away) it:

1. marks it lost (but never deletes the route)
2. tries to reconnect it, waiting longer each time (5s, 10s, 20s, 40s, 60s) so the bluetooth chip is not spammed
3. stops trying after at least 10 tries and 10 minutes, so it does not go on all day (the route is kept)
4. when it shows up again, puts the route back by itself

### measure

how far apart are two headphones? you need both of them and a phone.

```bash
audiohub measure signal clicks.wav --seconds 60
# play clicks.wav to both headphones. keep the LEFT cup of one and the RIGHT cup
# of the other next to the phone, and record with the phone
ffmpeg -i recording.m4a -c:a pcm_s16le recording.wav
audiohub measure analyze recording.wav --left hesh --right cb-evolve
```

left and right have different tones, so it knows which headphone is late. for drift, record 5 minutes or more. it has only been tested on made up recordings, not on real headphones.

## test

```bash
.venv/bin/python -m pytest
```

92 tests, no bluetooth or audio hardware needed. tests that need real hardware are marked `hardware` and skipped by default.

## files

```text
src/audiohub/
  cli.py          the commands
  routing.py      the routing graph, nothing platform specific in here
  state.py        connected / disconnected / reconnecting ... for each device
  devices.py      friendly names -> backend ids
  config.py       saves to json
  audio.py        finding outputs and sending audio to many of them
  bluetooth.py    connecting
  watch.py        keeps routed headphones alive
  latency.py      delay maths
  measure.py      click track + offset from a recording
  backends/       linux (pipewire + bluez) | macos (coreaudio) | null (for tests)
scripts/          read only system checks
docs/             architecture | experiments | limitations | cost
```

## how i work on this

measure first, buy later. use existing standards before making new ones. `docs/experiments.md` only has things that were really run, never a guess written like a result. things not measured show as `[?]`, also in `audiohub doctor`.

## fixed

- the bluetooth address of a headphone was never saved in the config, so reconnecting by itself could never work. fixed while adding `watch`.
