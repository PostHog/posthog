#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <simulator-app-path> <artifact-directory>" >&2
    exit 2
fi

app_dir=$(cd "$(dirname "$0")/.." && pwd)
binary=$(cd "$1" && pwd)
mkdir -p "$2"
artifact_dir=$(cd "$2" && pwd)
cd "$app_dir"

export DO_NOT_TRACK=1
unset ARGENT_TOOLS_URL ARGENT_AUTH_TOKEN
if [[ $(argent --version) != '0.30.1' ]]; then
    echo 'Install the pinned CLI: npm install --prefix <tools-directory> @swmansion/argent@0.30.1' >&2
    exit 1
fi

bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$binary/Info.plist")
if [[ "$bundle_id" != 'com.posthog.code.mobile' || ! -f "$binary/main.jsbundle" ]]; then
    echo 'Expected the bundled production-identity simulator app from ci-argent-build.sh.' >&2
    exit 1
fi
if [[ $(/usr/libexec/PlistBuddy -c 'Print :EXUpdatesEnabled' "$binary/Expo.plist") != 'false' ]]; then
    echo 'The simulator app must have OTA updates disabled by ci-argent-build.sh.' >&2
    exit 1
fi

private_dir=$(mktemp -d "${TMPDIR:-/tmp}/mobile-argent.XXXXXX")
simulator=''
server_started=false
# shellcheck disable=SC2329 # Invoked by the EXIT trap.
cleanup() {
    result=$1
    trap - EXIT
    if [[ -n "$simulator" ]]; then
        if [[ "$result" -ne 0 ]]; then
            xcrun simctl io "$simulator" screenshot "$artifact_dir/failure.png" >/dev/null 2>&1 || true
        fi
        xcrun simctl shutdown "$simulator" >/dev/null 2>&1 || true
        xcrun simctl delete "$simulator" >/dev/null 2>&1 || true
    fi
    if [[ "$server_started" == true ]]; then
        argent server stop >/dev/null 2>&1 || true
    fi
    rm -rf "$private_dir"
    exit "$result"
}
trap 'cleanup "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

runtime=${ARGENT_IOS_RUNTIME:-com.apple.CoreSimulator.SimRuntime.iOS-26-5}
simulator=$(xcrun simctl create "PostHog Argent $$" com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro "$runtime")
echo "Demo simulator: $simulator"
xcrun simctl boot "$simulator"
xcrun simctl bootstatus "$simulator" -b
xcrun simctl ui "$simulator" appearance light

# The dedicated CLI install owns this server; never replace a developer's running Argent server.
argent server start --port 0 --detach > "$private_dir/server-start.log"
server_started=true
connection=$(sed -n 's/.*argent link argent:\/\/\([^ ]*\).*/\1/p' "$private_dir/server-start.log" | head -1)
if [[ "$connection" != *@127.0.0.1:* ]]; then
    echo 'Argent did not return a local authenticated tool-server connection.' >&2
    exit 1
fi
export ARGENT_TOOLS_URL="http://${connection#*@}"
export ARGENT_AUTH_TOKEN="${connection%@*}"

failed=0
for flow in demo-smoke views-smoke; do
    # Reinstalling drops demo changes even when the preceding flow stopped before Exit demo.
    xcrun simctl terminate "$simulator" "$bundle_id" >/dev/null 2>&1 || true
    xcrun simctl uninstall "$simulator" "$bundle_id" >/dev/null 2>&1 || true
    xcrun simctl install "$simulator" "$binary"
    echo "Running $flow"
    if ! argent e2e run "$flow" --platform ios --device "$simulator" --output "$artifact_dir" --json > "$artifact_dir/$flow.json"; then
        failed=1
        xcrun simctl io "$simulator" screenshot "$artifact_dir/$flow-failure.png" >/dev/null 2>&1 || true
        echo "$flow failed; see $artifact_dir/$flow.json and its failed-step screenshots." >&2
    fi
done
exit "$failed"
