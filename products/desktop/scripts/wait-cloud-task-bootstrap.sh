#!/bin/sh
# Blocks until the backend-launched `pnpm bootstrap:cloud-task` finishes, then exits with its code.
# The state directory is written by _prepare_posthog_desktop_cloud_task in
# products/tasks/backend/temporal/process_task/activities/provision_sandbox.py.
set -eu

STATE_DIR=${POSTHOG_DESKTOP_BOOTSTRAP_STATE_DIR:-/tmp/posthog-desktop-bootstrap}
# Longer than the backend build deadline plus its kill grace, so a hung build reports exit 124.
TIMEOUT_SECONDS=${POSTHOG_DESKTOP_BOOTSTRAP_WAIT_SECONDS:-960}

if [ ! -f "$STATE_DIR/started" ]; then
    echo "No background Desktop bootstrap in this sandbox. Run: pnpm bootstrap:cloud-task" >&2
    exit 2
fi

waited=0
while [ ! -f "$STATE_DIR/exit" ]; do
    if [ "$waited" -ge "$TIMEOUT_SECONDS" ]; then
        echo "Desktop bootstrap still running after ${TIMEOUT_SECONDS}s. Log: $STATE_DIR/log" >&2
        exit 124
    fi
    sleep 1
    waited=$((waited + 1))
done

code=$(cat "$STATE_DIR/exit")
elapsed=$(($(date -r "$STATE_DIR/exit" +%s) - $(cat "$STATE_DIR/started")))
if [ "$code" -ne 0 ]; then
    tail -n 40 "$STATE_DIR/log" >&2
    echo "Desktop bootstrap failed with exit code $code after ${elapsed}s. Run: pnpm bootstrap:cloud-task" >&2
    exit "$code"
fi
echo "Desktop bootstrap finished in ${elapsed}s."
