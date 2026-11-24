#!/usr/bin/env bash
# Builds Hogs and starts it as a macOS app bundle.
# A bundle, not `cargo run`, because macOS ties the keychain entry, notifications and the
# app's name in the menu bar to a bundle identifier.
set -euo pipefail

cd "$(dirname "$0")/.."
cargo build --release

APP="target/Hogs.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp target/release/hogs "$APP/Contents/MacOS/Hogs"
cat >"$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>Hogs</string>
    <key>CFBundleIdentifier</key><string>com.posthog.hogs.dev</string>
    <key>CFBundleName</key><string>Hogs</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.0.1</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP" >/dev/null

if [ "${1:-}" = "--no-open" ]; then
    echo "$PWD/$APP"
else
    # Started directly so that environment variables such as HOGS_DEV_TOKEN reach the app.
    exec "$APP/Contents/MacOS/Hogs"
fi
