#!/usr/bin/env bash
set -euo pipefail

platform=$1
app_dir=$(pwd)
repo_dir=$(git rev-parse --show-toplevel)
capture_dir=/tmp/report-header-captures
mkdir -p "$capture_dir"
export PATH="/tmp/mobile-argent-tools/node_modules/.bin:$PATH"
export CI=1 EXPO_NO_DOTENV=1 EXPO_NO_TELEMETRY=1 DO_NOT_TRACK=1
export APP_VARIANT=production EXPO_PUBLIC_DEMO_MODE=0
export EXPO_PUBLIC_POSTHOG_KEY='' EXPO_PUBLIC_POSTHOG_HOST=''
unset EXPO_TOKEN APPLE_TEAM_ID GOOGLE_SERVICES_JSON ARGENT_TOOLS_URL ARGENT_AUTH_TOKEN
after_revision=$(git rev-parse HEAD)
before_revision=$(git rev-parse HEAD^)
files=(
    products/mobile/src/ui/ScreenChrome.tsx
    products/mobile/src/features/report/TopChrome.tsx
    products/mobile/src/features/report/ReportScreen.tsx
    products/mobile/src/features/report/details/ReportDetailsScreen.tsx
)

cat > "$capture_dir/report-header.yaml" <<'YAML'
steps:
    - launch: { ios: com.posthog.code.mobile, android: com.posthog.mobile }
    - await: { visible: { id: try-demo }, timeout: 30000 }
    - tap: { id: try-demo }
    - await: { visible: { id: inbox-screen } }
    - tap: { id: inbox-row-demo-report-load-time }
    - await: { visible: { id: report-scroll } }
    - await: { idle: true }
    - echo: report-initial
    - tool: screenshot
      args: { scale: 1, includeImageInContext: false }
    - tool: gesture-swipe
      args: { fromX: 0.5, fromY: 0.65, toX: 0.5, toY: 0.59, durationMs: 500, momentum: false }
    - await: { idle: true }
    - echo: report-scroll-1
    - tool: screenshot
      args: { scale: 1, includeImageInContext: false }
    - tool: gesture-swipe
      args: { fromX: 0.5, fromY: 0.65, toX: 0.5, toY: 0.59, durationMs: 500, momentum: false }
    - await: { idle: true }
    - echo: report-scroll-2
    - tool: screenshot
      args: { scale: 1, includeImageInContext: false }
    - tool: gesture-swipe
      args: { fromX: 0.5, fromY: 0.65, toX: 0.5, toY: 0.59, durationMs: 500, momentum: false }
    - await: { idle: true }
    - echo: report-scroll-3
    - tool: screenshot
      args: { scale: 1, includeImageInContext: false }
YAML

python3 - "$capture_dir" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
report = (root / 'report-header.yaml').read_text()
suffix = report[report.index('    - await: { idle: true }'):]
details = 'steps:\n    - tool: gesture-tap\n      args: { x: 0.3, y: 0.217 }\n' + suffix.replace('report-', 'details-')
(root / 'details-header.yaml').write_text(details)
(root / 'report-header.yaml').write_text((report + details.removeprefix('steps:\n')).replace('    - await: { idle: true }\n', ''))
PY

for file in "${files[@]}"; do
    git -C "$repo_dir" show "$before_revision:$file" > "$repo_dir/$file"
done

if [[ "$platform" == ios ]]; then
    xcodebuild -version > "$capture_dir/device.txt"
    xcrun simctl list runtimes -j > "$capture_dir/runtimes.json"
    runtime=$(python3 - "$capture_dir/runtimes.json" <<'PY'
import json, sys
runtimes = json.load(open(sys.argv[1]))['runtimes']
print(sorted((r for r in runtimes if r.get('isAvailable') and 'iOS' in r['identifier']), key=lambda r: tuple(map(int, r['version'].split('.'))))[-1]['identifier'])
PY
)
    if [[ -n "${REPORT_HEADER_PREBUILT_APP:-}" ]]; then
        binary=$REPORT_HEADER_PREBUILT_APP
    else
        bash scripts/ci-argent-build.sh /tmp/mobile-header-build "$capture_dir/build"
        binary=/tmp/mobile-header-build/Build/Products/Release-iphonesimulator/PostHog.app
    fi
    tar -czf "$capture_dir/PostHog-before.app.tar.gz" -C "$(dirname "$binary")" PostHog.app
    device=$(xcrun simctl create 'Report header comparison' com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro "$runtime")
    xcrun simctl boot "$device"
    xcrun simctl bootstatus "$device" -b
    xcrun simctl ui "$device" appearance light
    xcrun simctl status_bar "$device" override --time '9:41' --batteryState charged --batteryLevel 100
    printf 'iPhone 17 Pro\n%s\n%s\n' "$runtime" "$device" >> "$capture_dir/device.txt"
else
    device=emulator-5554
    adb shell getprop ro.product.model > "$capture_dir/device.txt"
    adb shell getprop ro.build.version.release >> "$capture_dir/device.txt"
    adb shell wm size >> "$capture_dir/device.txt"
    adb shell settings put secure stylus_handwriting_enabled 0
    pnpm exec expo prebuild --platform android --no-install --clean > "$capture_dir/prebuild.log" 2>&1
    python3 - <<'PY'
from pathlib import Path
path = Path('android/app/src/main/AndroidManifest.xml')
text = path.read_text().replace('android:name="expo.modules.updates.ENABLED" android:value="true"', 'android:name="expo.modules.updates.ENABLED" android:value="false"')
path.write_text(text)
PY
fi

trap 'argent server logs > "$capture_dir/tools-server.log" 2>&1 || true' EXIT
argent server start --port 0 --detach > "$capture_dir/server-start.log"
connection=$(sed -n 's/.*argent link argent:\/\/\([^ ]*\).*/\1/p' "$capture_dir/server-start.log" | head -1)
[[ "$connection" == *@127.0.0.1:* ]]
export ARGENT_TOOLS_URL="http://${connection#*@}"
export ARGENT_AUTH_TOKEN="${connection%@*}"

for phase in before after; do
    phase_dir="$capture_dir/$phase"
    mkdir -p "$phase_dir"
    if [[ "$phase" == after ]]; then
        for file in "${files[@]}"; do
            git -C "$repo_dir" show "$after_revision:$file" > "$repo_dir/$file"
        done
        if [[ "$platform" == ios ]]; then
            pnpm exec expo export:embed --entry-file node_modules/expo-router/entry.js --platform ios --dev false --bundle-output "$binary/main.jsbundle" --assets-dest "$binary" --max-workers 2 > "$phase_dir/bundle.log" 2>&1
        fi
    fi
    if [[ "$platform" == ios ]]; then
        if [[ "$phase" == after ]]; then
            tar -czf "$capture_dir/PostHog-after.app.tar.gz" -C "$(dirname "$binary")" PostHog.app
        fi
        xcrun simctl terminate "$device" com.posthog.code.mobile >/dev/null 2>&1 || true
        xcrun simctl uninstall "$device" com.posthog.code.mobile >/dev/null 2>&1 || true
        xcrun simctl install "$device" "$binary"
    else
        (cd android && ./gradlew assembleRelease -PreactNativeArchitectures=x86_64 --max-workers=2 --console=plain '-Dorg.gradle.jvmargs=-Xmx3g -XX:MaxMetaspaceSize=1g') > "$phase_dir/build.log" 2>&1
        cp android/app/build/outputs/apk/release/app-release.apk "$phase_dir/app-release.apk"
        adb install -r "$phase_dir/app-release.apk"
        adb shell pm clear com.posthog.mobile
    fi
    if [[ "$platform" == android ]]; then
        python3 scripts/capture-android-header.py "$phase_dir"
        continue
    fi
    xcrun simctl terminate "$device" com.apple.mobilecal >/dev/null 2>&1 || true
    argent e2e run "$capture_dir/report-header.yaml" --platform "$platform" --device "$device" --output "$phase_dir" --json > "$phase_dir/report.json" || true
    python3 - "$phase_dir" <<'PY_COPY'
from pathlib import Path
import json, shutil, sys
root = Path(sys.argv[1])
report = json.loads((root / 'report.json').read_text())
for step in report['steps']:
    if step['kind'] == 'echo':
        name = step['message']
    if step.get('tool') == 'screenshot' and step.get('status') == 'pass':
        shutil.copyfile(step['result']['image']['hostPath'], root / f'{name}.png')
if not report['ok']:
    raise SystemExit('Native report capture failed')
PY_COPY
done

argent server stop
if [[ "$platform" == ios ]]; then
    xcrun simctl shutdown "$device"
    xcrun simctl delete "$device"
    ARGENT_IOS_RUNTIME="$runtime" bash scripts/ci-argent.sh "$binary" "$capture_dir/smoke"
fi
printf 'before=%s\nafter=%s\n' "$before_revision" "$after_revision" > "$capture_dir/revisions.txt"
