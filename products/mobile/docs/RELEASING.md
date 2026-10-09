# Releasing

How to build the app with EAS, install it on test devices, and ship it to TestFlight, the Play internal track and the stores.
Over-the-air JavaScript updates are in [OTA.md](OTA.md). The CI workflows are in [CI.md](CI.md).

## Store records this app uses

This app replaces the existing "PostHog" mobile app on both stores.
It keeps that app's identity, so a store update replaces the old app on people's phones.

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

The old app shipped as version `1.0.0`, and this app also starts at `1.0.0`.
If App Store Connect already has a released `1.0.0`, Apple does not take new builds for that version.
In that case, raise `version` in `app.config.ts` (for example to `1.1.0`) before the first production build.
The version also sets the runtime version for updates, see [OTA.md](OTA.md#runtime-version).

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
5. Add the store submission keys in `eas credentials`:
   - iOS: an App Store Connect API key, under the production profile.
   - Android: a Google Play service account key with release access.
6. Add the push credentials that [PUSH.md](PUSH.md) lists: an APNs key for iOS and an FCM V1 service account for Android.
7. Add the build-time variables to each EAS environment (`development`, `preview`, `production`).
   They are public in the app bundle, so plain text visibility is correct:

   ```sh
   eas env:set production --name EXPO_PUBLIC_POSTHOG_KEY --value <project api key> --visibility plaintext
   eas env:set production --name EXPO_PUBLIC_POSTHOG_HOST --value https://us.i.posthog.com --visibility plaintext
   ```

8. Check that the repository secret `EXPO_TOKEN` exists. The desktop mobile workflows already use it.
   The "Mobile Build" workflow reads the same secret.

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
