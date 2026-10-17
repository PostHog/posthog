# Releasing

How to build the app with EAS, install it on test devices, and ship it to TestFlight, the Play internal track and the stores.
Over-the-air JavaScript updates are in [OTA.md](OTA.md). The CI workflows are in [CI.md](CI.md).

## Store records this app uses

This app replaces the existing "PostHog" mobile app on both stores.
The store build keeps that app's identity, so a store update replaces the old app on people's phones.
Development and preview builds use their own identities, see [Build variants](#build-variants).

| Field | Value |
| --- | --- |
| App name | PostHog |
| iOS bundle id and Android package | `com.posthog.code.mobile` |
| Expo owner and slug | `posthog` / `posthog` |
| EAS project id | `4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9` |
| App Store Connect app id | `6762366098` |
| Google Play track for submissions | `internal` |

The old app's source is `products/desktop/apps/mobile`, and its workflows are "Desktop Mobile Build" and "Desktop Mobile Promote".
Both apps share the same records and the same remote build-number counter.
Stop building the old app before the first build of this one goes to a store.

The old app shipped as version `1.0.0`. This app starts at `1.1.0`, so its builds do not collide with a released `1.0.0` in App Store Connect.
The version also sets the runtime version for updates, see [OTA.md](OTA.md#runtime-version).

Version `1.1.0` adds a native module, Skia, for the report charts.
The runtime version follows the app version, so an update published for `1.1.0` never reaches a `1.0.0` build.
Every EAS profile (development, preview and production) needs a new native build before it can run `1.1.0` code.

Version `1.2.0` adds native modules for chat attachments: `expo-image-picker` and `expo-document-picker`.
`expo-file-system` becomes a direct dependency; it was already linked through `expo`, so it is not a new native module.
The image picker's config plugin writes the photo library usage description and removes the camera and microphone permissions.
Every EAS profile needs a new native build before it can run `1.2.0` code.
Do not publish `1.2.0` code as an update to `1.1.0` builds: the runtime versions differ, so those builds never receive it, and the picker modules are not in them.

## Build profiles

Profiles are in `eas.json`. Each profile has its own update channel and EAS environment.

| Profile | Signing | Who installs it | Update channel | Command |
| --- | --- | --- | --- | --- |
| `development` | Ad hoc (iOS), APK (Android) | Developers, with Metro for live reload | `development` | `pnpm build:dev`, `pnpm build:dev:android` |
| `preview` | Ad hoc (iOS), APK (Android) | Internal testers on registered devices | `preview` | `pnpm build:preview`, `pnpm build:preview:android` |
| `production` | App Store (iOS), app bundle (Android) | TestFlight, Play internal track, then the stores | `production` | `pnpm build:production`, `pnpm build:production:android` |

`appVersionSource` is `remote`, so EAS stores the iOS build number and the Android version code.
Production builds raise them automatically (`autoIncrement`).
Check the current values with `eas build:version:get`.

The `pnpm build:*` scripts run `scripts/eas-build.sh`.
It uploads only `products/mobile`, filtered by `.easignore`.
Without it, EAS uploads the whole repository and installs the root pnpm workspace, which excludes this app.

## Build variants

Each profile sets `APP_VARIANT` in its `env` block in `eas.json`, and `app.config.ts` gives each variant its own identity.
The three variants install side by side on one device. They do not share sign-in, settings or the widget's data.
The names, id suffixes and schemes are in `src/lib/appVariants.json`.

| Variant | Profile | App name | iOS bundle id and Android package | URL scheme | iOS App Group | Icon |
| --- | --- | --- | --- | --- | --- | --- |
| `development` | `development` | PostHog Dev | `com.posthog.code.mobile.dev` | `posthog-dev` | `group.com.posthog.code.mobile.dev` | `icon-dev.png`, amber DEV band |
| `preview` | `preview` | PostHog Preview | `com.posthog.code.mobile.preview` | `posthog-preview` | `group.com.posthog.code.mobile.preview` | `icon-preview.png`, purple PREVIEW band |
| `production` | `production` | PostHog | `com.posthog.code.mobile` | `posthog` | `group.com.posthog.code.mobile` | `app.icon` on iOS 26, `icon.png` elsewhere |

- The widget extension's bundle id is the app's id plus `.HedgehogWidget`, for example `com.posthog.code.mobile.dev.HedgehogWidget`.
- The production profile also sets `EXPO_PUBLIC_SIGNUP_LINK=0`, so store builds hide "Create an account".
- A local build without `APP_VARIANT` (`pnpm ios`, `pnpm android`, and the local phone installs below) gets the production identity.
  `APP_VARIANT=development pnpm ios` builds the dev identity locally; its Xcode workspace is `ios/PostHogDev.xcworkspace`, because prebuild names the project after the app.
- In the app, `src/lib/environment.ts` reads the variant from the bundle id, so an update cannot change it.
  A Metro bundle always counts as development.
- Development and preview builds show an environment ribbon on the sign-in screen and in Settings, and a Settings Environment group.
  They accept `http://localhost` hosts and prefill the local dev OAuth client id. Store builds do none of this.
  A store build shows a red ribbon only when the session's host is not PostHog Cloud.

## One-time setup

Someone with these accounts does each step once. An agent cannot do them.

1. Get access:
   - Membership of the `posthog` organization on [expo.dev](https://expo.dev).
   - The App Manager or Admin role for the PostHog app in App Store Connect, in the PostHog Apple Developer team.
   - Release manager access to the PostHog app in the Google Play Console.
2. Install the EAS CLI and sign in:

   ```sh
   npm install -g eas-cli
   eas login        # or: npx eas-cli login
   eas whoami
   ```

3. Check that this directory links to the existing EAS project:

   ```sh
   cd products/mobile
   eas project:info     # expect @posthog/posthog and id 4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9
   eas init             # expect "already linked"; if it offers to create a project, stop and check your account
   ```

4. Check the signing credentials with `eas credentials`.
   The old app already built with this bundle id, so EAS should hold the iOS distribution certificate, the provisioning profiles and the Android upload keystore.
   Reuse them. Do not generate a new Android keystore: Google Play rejects bundles signed with a different upload key.
5. Register the internal identities from [Build variants](#build-variants) in the Apple Developer account, under Certificates, Identifiers & Profiles:
   - App IDs `com.posthog.code.mobile.dev`, `com.posthog.code.mobile.dev.HedgehogWidget`, `com.posthog.code.mobile.preview` and `com.posthog.code.mobile.preview.HedgehogWidget`.
   - App Groups `group.com.posthog.code.mobile.dev` and `group.com.posthog.code.mobile.preview`.
   - Turn on the App Groups capability for all four App IDs and select the group of the same variant. Turn on Push Notifications for the two app ids.

   The first `pnpm build:dev` or `pnpm build:preview` with Apple login lets EAS create missing App IDs, sync capabilities and make the ad hoc provisioning profiles.
   Check afterwards that each App ID has its App Group linked. A missing group leaves the widget without the app's data.
   Android needs no registration for these packages, because development and preview builds are APKs outside Google Play.
6. Add the store submission keys in `eas credentials`:
   - iOS: an App Store Connect API key, under the production profile.
   - Android: a Google Play service account key with release access.
7. Set up push for each variant as [PUSH.md](PUSH.md#credentials) describes: the APNs key for each iOS bundle id, a Firebase Android app for each package, the FCM V1 service account key in `eas credentials`, and the `GOOGLE_SERVICES_JSON` file variable in each EAS environment.
8. Add the build-time variables to each EAS environment (`development`, `preview`, `production`).
   They are public in the app bundle, so plain text visibility is correct:

   ```sh
   eas env:set production --name EXPO_PUBLIC_POSTHOG_KEY --value <project api key> --visibility plaintext
   eas env:set production --name EXPO_PUBLIC_POSTHOG_HOST --value https://us.i.posthog.com --visibility plaintext
   ```

   Do not add `APP_VARIANT` or `EXPO_PUBLIC_SIGNUP_LINK` here. `eas.json` and the update scripts set them.
9. Add `posthog-dev://callback` and `posthog-preview://callback` to the redirect URIs of the US and EU mobile OAuth applications in Django admin, so internal builds can sign in to PostHog Cloud. See [AUTH.md](AUTH.md#redirect-uris).
10. Check that the repository secret `EXPO_TOKEN` exists. The desktop mobile workflows already use it.
   The "Mobile Build" workflow reads the same secret.

## Install the current checkout on a connected iPhone

Use a local Release build to put the current source on a phone with its JavaScript bundled in.
It runs without Metro or a connection to the Mac. This builds the selected checkout, including
uncommitted changes; it does not fetch a newer branch or install the latest store release.
Check the branch and local changes first. The displayed app version comes from `app.config.ts`,
so two local builds can show the same version while containing different code.

### Prepare the Mac and phone

- Use macOS with Xcode and its command-line tools selected (`xcode-select -p`), CocoaPods,
  the Node version in `.node-version`, and pnpm 10.
- Add an Apple Developer account in Xcode's Settings, Accounts. Its team must be allowed to
  sign `com.posthog.code.mobile`, the `HedgehogWidget` extension, and their shared App Group.
  A signing certificate alone does not establish access to those identifiers.
- Connect the iPhone by USB, unlock it, and accept **Trust This Computer** if prompted.
  On iOS 16 and later, enable **Developer Mode** in Settings, Privacy & Security, and complete
  the restart and confirmation. Keep the phone connected through installation and launch.

Run commands from this app's workspace, not the repository root:

```sh
cd products/mobile
pnpm install --frozen-lockfile
pnpm typecheck
xcrun devicectl list devices
```

Select a row whose reality is `physical`, rather than a simulator. Copy its identifier and
use the Apple team ID from Xcode's account settings; do not reuse another developer's device
identifier or assume their signing team is available:

```sh
export DEVICE_ID='<physical device identifier>'
export APPLE_TEAM_ID='<Apple Developer team ID>'
xcrun devicectl device info details --device "$DEVICE_ID"
security find-identity -v -p codesigning
```

The device details should report a paired, connected phone with Developer Mode enabled.
`security find-identity` should list a valid Apple Development identity with its private key
available in the login keychain. Xcode manages the corresponding provisioning profiles.

### Generate, build and install

```sh
CI=1 pnpm exec expo prebuild --platform ios --pnpm --skip-dependency-update react,react-native
CI=1 pnpm exec expo run:ios --device "$DEVICE_ID" --configuration Release --no-bundler --no-install
```

The first command regenerates the ignored `ios/` directory and installs CocoaPods. With the
current Expo CLI, regeneration clears the existing native directory by default; preserve any
manual native experiments before running it. Native changes belong in config plugins or
the source under `modules/` and `targets/`, so they survive regeneration. This also applies
the app's scene-lifecycle plugin and generates the widget target.

For repeat installs after JavaScript or TypeScript changes only, reuse the generated native
project: rerun the dependency install and type check, then the `expo run:ios` command above.
Regenerate first when changing native dependencies, app configuration, config plugins,
native modules or widget sources, or when switching app variants.

The second command builds the workspace for that physical device, signs both targets,
installs the app, and launches it. `Release` embeds the current JavaScript and assets.
The output can still say **Starting Metro Bundler** while generating that bundle;
`--no-bundler` avoids leaving a development server running. `--no-install` skips another
dependency installation because prebuild already installed the pods.
Expo can also print **Waiting on http://localhost:8081** at the end of a successful Release
build. That message alone does not mean the installed app requires Metro.

Install over the existing app to retain its data when signing is compatible. Do not uninstall
as a routine update step. These local builds use development signing and do not consume the
EAS remote build-number counter or select an EAS update channel. Use the preview or production
profiles below when testing channel updates or distributing a build to other people.

### Verify the installation

```sh
xcrun devicectl device info apps --device "$DEVICE_ID" --bundle-id com.posthog.code.mobile
xcrun devicectl device process launch --device "$DEVICE_ID" --terminate-existing com.posthog.code.mobile
xcrun devicectl device info processes --device "$DEVICE_ID" --search PostHog
```

Confirm that the installed version matches `app.config.ts`, the launch succeeds, and the
PostHog process remains running. Inspect the phone: the app should render its sign-in screen
or the existing session, rather than a development-server picker or an error screen.
Relaunch without Metro to check that the embedded bundle works. Launch success alone does
not verify sign-in, API calls, push notifications, or the full [demo walkthrough](TESTING.md).

On Xcode versions that provide screen capture, a local screenshot can help verify rendering:

```sh
xcrun devicectl device capture screenshot --device "$DEVICE_ID" --destination /tmp/posthog-mobile-install.png
```

Keep device identifiers, signing details, logs and screenshots out of committed notes;
screenshots of an existing session can contain private project data.

### If installation or launch fails

- **Prebuild fails updating the widget target with `removeFromProject` undefined:** rerun
  the prebuild command above without `--no-clean`. With `@bacons/apple-targets` 5.0.0,
  updating an existing widget target can fail; regenerating the native project succeeds.
  Preserve any manual native experiments first.
- **Signing or provisioning fails:** open `ios/PostHog.xcworkspace` in Xcode and check
  Signing & Capabilities for both PostHog and HedgehogWidget. Use the authorized team and
  automatic signing. Resolve certificate, device-registration and App Group access through
  that team; do not change the app's identifiers to bypass an error.
- **The build succeeds but installation fails:** reconnect and unlock the phone, then retry
  the signed `.app` from the successful build with the commands below. Set `APP_PATH` to the
  actual `Release-iphoneos/PostHog.app` path from that build, not a simulator binary.
- **The phone is locked:** unlock it and retry launch. Trust and Developer Mode prompts
  require interaction on the phone.
- **A native module or scene-lifecycle error appears:** regenerate with prebuild and rebuild;
  restarting Metro does not update native code. Build through the `.xcworkspace`, which
  includes Pods, rather than the `.xcodeproj`.

```sh
export APP_PATH='<absolute path to the signed Release-iphoneos/PostHog.app>'
xcrun devicectl device install app --device "$DEVICE_ID" "$APP_PATH"
xcrun devicectl device process launch --device "$DEVICE_ID" --terminate-existing com.posthog.code.mobile
```

For a connected Android phone, use the [local Android process below](#install-the-current-checkout-on-a-connected-android-phone).
For devices that are not connected to the build machine, use the
[preview-build distribution process](#share-a-preview-build). Android takes the APK directly;
iOS ad hoc builds must include each recipient's device in the provisioning profile.
TestFlight uses production builds and does not require registering each tester's device.

References: [Expo local builds](https://docs.expo.dev/guides/local-app-development/),
[Expo CLI](https://docs.expo.dev/more/expo-cli/), and
[Apple Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device).

### Swift errors after upgrading Xcode

If importing `ExpoModulesJSI` fails with `cannot find type '__ObjC::expo' in scope`,
the generated bridge framework may belong to the previous SDK. Its cache can survive
an Xcode upgrade when the Swift compiler version stays the same, as described in
[this upstream report](https://github.com/expo/expo/issues/50365).

The recovery verified with Xcode 27.1 regenerates the physical-device bridge slice and
builds Expo modules from source. Run from this app's workspace, with the existing `ios/`
project and the device and signing setup above:

```sh
rm node_modules/expo-modules-jsi/apple/Products/ExpoModulesJSI.xcframework/ios-arm64/.build-hash
(cd ios && EXPO_USE_PRECOMPILED_MODULES=0 pod install)
CI=1 EXPO_USE_PRECOMPILED_MODULES=0 pnpm exec expo run:ios --device "$DEVICE_ID" --configuration Release --no-bundler --no-install
```

The removed file is a generated cache marker; it is recreated by the bridge build.
For a simulator error, invalidate the corresponding simulator slice instead of `ios-arm64`.
The source-build setting applies to this local pod installation; a later pod install or
prebuild without it returns to the default. No dependency-source or Swift-interface edits
are needed. After installation, repeat the launch and rendering checks above.

### Verification record

On October 14, 2026, this process installed app version `1.1.0` (local build `1`) from the
current working tree on a physical iPhone running iOS 26.2, using Xcode 27.0 and Expo SDK 57.
The frozen dependency install, type check, prebuild and Release build succeeded.
The signed app and embedded extension passed `codesign --verify --deep --strict`.
After installation, an explicit relaunch succeeded, the PostHog process remained running,
and a local screenshot confirmed that the inbox rendered with the existing session.
No server was listening on Metro's default port 8081. Full feature QA and installation on
other devices were not performed; the parameters and distribution options above cover reuse.

On October 16, 2026, the Xcode 27.1 recovery above produced and installed a new Release
build of `1.1.0`. The type check and signature verification passed. An explicit relaunch
kept the app running, and a local screenshot confirmed the inbox with the existing session.

## Install the current checkout on a connected Android phone

This produces a local Release APK with JavaScript and assets embedded, so the installed app
runs without Metro. It builds the current checkout, including local changes.

### Prepare the build machine and phone

Install the app's Node and pnpm versions, a JDK compatible with the Gradle wrapper, and the
Android SDK. The verified setup uses JDK 17, Android SDK platform and build tools 36, and
NDK `27.1.12297006`. Gradle reports its required SDK and NDK versions during configuration.
Find your SDK location in Android Studio's SDK settings, then set these for your machine:

```sh
export ANDROID_HOME='<Android SDK directory>'
export JAVA_HOME='<JDK home directory>'
export PATH="$ANDROID_HOME/platform-tools:$JAVA_HOME/bin:$PATH"
```

On the phone, enable Developer options and **USB debugging**, connect a data-capable USB
cable, unlock the screen, and accept the debugging authorization prompt. Then run:

```sh
adb devices -l
```

Select the physical device's row, whose state must be `device`. `unauthorized` means the
phone still needs to approve the Mac. `offline` means it is not ready; reconnect and check
again. An identifier beginning with `emulator-` belongs to an emulator.

Keep the serial for commands that target the phone, and the row's `model:` value for Expo:

```sh
export ANDROID_SERIAL='<physical device serial>'
export ANDROID_DEVICE_NAME='<model value from adb devices -l>'
adb -s "$ANDROID_SERIAL" shell getprop ro.build.version.release
adb -s "$ANDROID_SERIAL" shell getprop ro.product.cpu.abilist
```

### Sync, build and install

From the repository root:

```sh
cd products/mobile
pnpm install --frozen-lockfile
pnpm typecheck
CI=1 pnpm exec expo prebuild --platform android --no-clean --pnpm --skip-dependency-update react,react-native
CI=1 pnpm exec expo run:android --device "$ANDROID_DEVICE_NAME" --variant release --no-bundler --no-install
```

Prebuild updates the ignored Android project from `app.config.ts`, including the version;
`--no-clean` preserves the existing native directory. If native configuration is stale,
regenerate without `--no-clean`, after preserving any manual native experiments.
The build includes native dependencies, creates the APK, installs it on the selected phone,
and launches it. The first Release build can compile libraries for several CPU architectures.
Later builds reuse Gradle's cache. Metro messages during bundling do not mean a server must
remain running after installation.

Expo's `--device` selects by device name. If multiple connected phones have the same model,
build without choosing a device and install explicitly by serial instead:

```sh
cd android
./gradlew :app:assembleRelease
cd ..
adb -s "$ANDROID_SERIAL" install -r android/app/build/outputs/apk/release/app-release.apk
```

The generated local Release variant uses the project's debug keystore. Keep that key for
subsequent local updates. Store releases use the existing production signing credentials
through EAS. If `install -r` reports a signing mismatch, use a build signed with the matching
key; do not uninstall the existing app automatically, because that clears its app data.

### Verify the installation

```sh
adb -s "$ANDROID_SERIAL" shell dumpsys package com.posthog.code.mobile
adb -s "$ANDROID_SERIAL" shell am force-stop com.posthog.code.mobile
adb -s "$ANDROID_SERIAL" shell am start -W -n com.posthog.code.mobile/.MainActivity
adb -s "$ANDROID_SERIAL" shell pidof com.posthog.code.mobile
adb -s "$ANDROID_SERIAL" exec-out screencap -p > /tmp/posthog-mobile-android-install.png
```

Check `versionName` against `app.config.ts`, confirm launch succeeds and the process remains
running, then inspect the phone or screenshot after startup. A fresh device should show sign-in;
an update can retain the existing session. This verifies installation and startup, not every
feature or a new sign-in. Keep serials, private screenshots and device logs out of the repository.

If a screenshot is black, wake and unlock the phone before checking the screen. USB debugging
can remain connected while the display is off. `adb -s "$ANDROID_SERIAL" shell input keyevent KEYCODE_WAKEUP`
wakes the display; complete any secure unlock on the phone itself.

### Verification record

On October 15, 2026, this process installed version `1.1.0` (local build `1`) on a physical
Moto G Play (2024) running Android 14 with an ARM64 CPU. The frozen dependency install, type
check, Android prebuild and Gradle Release build succeeded. The APK passed `apksigner verify`.
An explicit cold launch succeeded, the app stayed running in the foreground, and a local
screenshot confirmed that the sign-in screen rendered. The app was left ready for sign-in;
no account credentials were entered and full feature QA was not performed.

References: [Android hardware-device setup](https://developer.android.com/studio/run/device),
[Expo CLI](https://docs.expo.dev/more/expo-cli/), and
[Android APK distribution](https://docs.expo.dev/build-reference/apk/).

## Install a development build on an iPhone

A development build is the app with the Expo dev client.
It loads JavaScript from Metro on your Mac, so you rebuild it only when native code changes.

1. Register the iPhone:

   ```sh
   cd products/mobile
   eas device:create
   ```

   Open the link or scan the QR code on the iPhone and install the profile it offers.
   On iOS 16 and later, turn on Developer Mode in Settings, Privacy & Security.
2. Build:

   ```sh
   pnpm build:dev
   ```

   When EAS asks, include the new device in the provisioning profile.
3. When the build finishes, scan the QR code that `eas` prints, or open the build page on the iPhone, and tap Install.
4. Start Metro on your Mac and open the app on the iPhone:

   ```sh
   pnpm start --dev-client
   ```

   The iPhone and the Mac must be on the same network.
   The app lists the running server. You can also scan the QR code from the terminal with the camera.

For Android, run `pnpm build:dev:android` and install the APK from the build page.
No device registration is needed.

The development build installs as "PostHog Dev" next to the store app, and shows an amber "Dev build" ribbon on the sign-in screen and in Settings.

Rebuild the development build after a change to native code:
a new native module, a config plugin, or a native field in `app.config.ts`.

## Share a preview build

Preview builds have the release JavaScript bundled in, and they take updates from the `preview` channel.
Use them to test a change before it goes to TestFlight.

```sh
pnpm build:preview            # iOS, for devices registered with eas device:create
pnpm build:preview:android    # Android APK
```

You can also run the "Mobile Build" workflow with the `preview` profile.
Testers install from the EAS build page. iOS testers need a registered device.

## Ship to TestFlight and the Play internal track

Only production builds can go to TestFlight. Preview builds use ad hoc signing, which App Store Connect does not take.

From your machine:

```sh
pnpm build:production                 # iOS
pnpm submit:ios --latest              # to App Store Connect, then TestFlight
pnpm build:production:android
pnpm submit:android --latest          # to the Play internal track
```

Pass `--latest` without a `--` before it. pnpm forwards a `--` to `eas`, which then reads `--latest` as an argument instead of a flag.

From CI: run the "Mobile Build" workflow from `master` with profile `production`, platform `all`, and submit checked.
EAS submits each build when it finishes. Follow progress on the EAS project page.

After the iOS upload, App Store Connect processes the build for 5 to 30 minutes before it shows in TestFlight.

## Release to the stores

1. Test the TestFlight build and the Play internal build.
2. In App Store Connect, add the build to a new version, write the release notes, and submit it for review.
3. In the Play Console, promote the internal release to production.
4. Raise `version` in `app.config.ts` after the release, so the next native build gets a new version and runtime version.

## Before you share a build

- `pnpm typecheck`, `pnpm lint` and `pnpm test` pass.
- The demo walkthrough passes on the iOS simulator. See [TESTING.md](TESTING.md).
- Sign in to a real project and open a report, on the build you are about to share.
