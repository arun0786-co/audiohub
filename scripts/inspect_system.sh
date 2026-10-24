#!/usr/bin/env bash
# Read-only system inventory. Installs nothing, changes nothing.
# Works on Debian-family Linux and on macOS, so the same script can be run on
# the development machine and on a candidate target board.
set -u

section() { printf '\n== %s ==\n' "$1"; }
try()     { command -v "$1" >/dev/null 2>&1 && "$@" 2>&1 | head -"${HEAD:-20}" || echo "($1 not present)"; }

section "Host"
uname -a
if [ -r /etc/os-release ]; then
    . /etc/os-release && echo "Distro: ${PRETTY_NAME:-unknown}"
elif command -v sw_vers >/dev/null 2>&1; then
    sw_vers
fi
echo "CPU cores: $(getconf _NPROCESSORS_ONLN 2>/dev/null || echo '?')"

section "Audio server"
if [ "$(uname -s)" = "Linux" ]; then
    try pipewire --version
    try wireplumber --version
    try pactl --version
    [ -r /proc/asound/version ] && cat /proc/asound/version || echo "(no /proc/asound)"
    section "Is PipeWire actually running?"
    try pgrep -a pipewire
    try pgrep -a wireplumber
    section "Is PulseAudio compatibility present?"
    if command -v pactl >/dev/null 2>&1; then
        pactl info 2>&1 | grep -Ei 'server name|server version|default sink' || true
    else
        echo "(pactl not present)"
    fi
else
    echo "Audio server: CoreAudio (macOS)"
    echo "PipeWire/WirePlumber/BlueZ/ALSA: not applicable on this platform"
fi

section "Bluetooth stack"
if [ "$(uname -s)" = "Linux" ]; then
    try bluetoothctl --version
    try hciconfig -a
    HEAD=40 try systemctl --no-pager status bluetooth
else
    HEAD=30 try system_profiler SPBluetoothDataType
fi

section "Python"
try python3 --version

printf '\nRead-only inspection complete. Nothing was modified.\n'
