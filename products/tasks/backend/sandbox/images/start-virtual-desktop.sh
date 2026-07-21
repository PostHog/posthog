#!/usr/bin/env bash
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"

if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    exit 0
fi

rm -f "/tmp/.X${DISPLAY#:}-lock"
nohup Xvfb "$DISPLAY" -screen 0 1440x900x24 -nolisten tcp -ac >/tmp/xvfb.log 2>&1 &

for _ in $(seq 1 100); do
    if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
        nohup openbox-session >/tmp/openbox.log 2>&1 &
        for _ in $(seq 1 50); do
            wmctrl -m >/dev/null 2>&1 && exit 0
            sleep 0.1
        done
        echo "Window manager failed to start" >&2
        exit 1
    fi
    sleep 0.1
done

echo "Virtual display failed to start" >&2
exit 1
