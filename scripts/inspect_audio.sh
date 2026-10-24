#!/usr/bin/env bash
# Read-only audio graph inventory, with an emphasis on the questions that
# actually matter for AudioHub: which sinks exist, which are Bluetooth, what
# codec and profile each Bluetooth sink negotiated, and whether the OS can fan
# one stream out to several of them.
set -u

section() { printf '\n== %s ==\n' "$1"; }

if [ "$(uname -s)" = "Linux" ]; then
    section "Sinks"
    if command -v pw-dump >/dev/null 2>&1; then
        pw-dump 2>/dev/null | python3 -c '
import json, sys
try:
    objs = json.load(sys.stdin)
except Exception:
    sys.exit("could not parse pw-dump output")
for o in objs:
    if o.get("type") != "PipeWire:Interface:Node":
        continue
    p = (o.get("info") or {}).get("props") or {}
    if p.get("media.class") not in ("Audio/Sink", "Audio/Source"):
        continue
    print("%-12s %-11s %-40s api=%-8s codec=%-6s profile=%s" % (
        p.get("media.class", "?").split("/")[-1],
        p.get("device.api", "-"),
        p.get("node.name", "?")[:40],
        p.get("device.api", "-"),
        p.get("api.bluez5.codec", "-"),
        p.get("api.bluez5.profile", "-"),
    ))
'
    else
        echo "(pw-dump not present)"
    fi

    section "Bluetooth audio cards and available profiles"
    command -v pactl >/dev/null 2>&1 && pactl list cards 2>/dev/null \
        | grep -E 'Name: bluez|Active Profile|a2dp|Card #' || echo "(pactl not present)"

    section "Loaded combine/loopback modules"
    command -v pactl >/dev/null 2>&1 \
        && (pactl list modules short 2>/dev/null | grep -E 'combine|loopback|null-sink' || echo "(none loaded)") \
        || echo "(pactl not present)"
else
    section "CoreAudio devices"
    system_profiler -json SPAudioDataType 2>/dev/null | python3 -c '
import json, sys
data = json.load(sys.stdin).get("SPAudioDataType", [])
for section in data:
    for d in section.get("_items", []):
        print("%-28s in=%-3s out=%-3s %-12s %s" % (
            d.get("_name", "?")[:28],
            d.get("coreaudio_device_input", "-"),
            d.get("coreaudio_device_output", "-"),
            d.get("coreaudio_device_transport", "?").replace("coreaudio_device_type_", ""),
            "DEFAULT-OUT" if d.get("coreaudio_default_audio_output_device") == "spaudio_yes" else "",
        ))
'
    section "Multi-Output Devices"
    echo "macOS can combine sinks, but only Audio MIDI Setup can create the"
    echo "device. Any aggregate you build by hand appears above as transport"
    echo "'aggregate' and can then be used as an ordinary sink."
fi

printf '\nRead-only inspection complete. Nothing was modified.\n'
