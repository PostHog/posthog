#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <derived-data-directory> <artifact-directory>" >&2
    exit 2
fi

app_dir=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$1" "$2"
build_dir=$(cd "$1" && pwd)
artifact_dir=$(cd "$2" && pwd)
cd "$app_dir"

export CI=1 EXPO_NO_DOTENV=1 EXPO_NO_TELEMETRY=1 DO_NOT_TRACK=1
export COCOAPODS_DISABLE_STATS=true
export APP_VARIANT=production EXPO_PUBLIC_DEMO_MODE=0
export EXPO_PUBLIC_POSTHOG_KEY='' EXPO_PUBLIC_POSTHOG_HOST=''
export EXTRA_PACKAGER_ARGS='--max-workers 2'
unset EXPO_TOKEN APPLE_TEAM_ID GOOGLE_SERVICES_JSON

# Regenerate like EAS: apple-targets cannot reliably update an existing widget Xcode target in place.
pnpm exec expo prebuild --platform ios --no-install --clean 2>&1 | tee "$artifact_dir/prebuild.log"
pod install --project-directory=ios 2>&1 | tee "$artifact_dir/pods.log"

# A demo smoke must exercise this checkout's bundle, never download an update from its EAS project.
/usr/libexec/PlistBuddy -c 'Set :EXUpdatesEnabled false' ios/PostHog/Supporting/Expo.plist

xcodebuild \
    -workspace ios/PostHog.xcworkspace \
    -scheme PostHog \
    -configuration Release \
    -sdk iphonesimulator \
    -destination 'generic/platform=iOS Simulator' \
    -derivedDataPath "$build_dir" \
    -jobs 2 \
    ARCHS="$(uname -m)" \
    ONLY_ACTIVE_ARCH=YES \
    CODE_SIGNING_ALLOWED=NO \
    CODE_SIGN_IDENTITY='' \
    build 2>&1 | tee "$artifact_dir/build.log"

binary="$build_dir/Build/Products/Release-iphonesimulator/PostHog.app"
test -f "$binary/main.jsbundle"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "app_path=$binary" >> "$GITHUB_OUTPUT"
fi
echo "Built simulator app: $binary"
