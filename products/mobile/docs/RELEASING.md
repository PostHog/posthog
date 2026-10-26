# Releasing

Use the repository's **Mobile Build** workflow to build the app with EAS and submit it to TestFlight and the Play internal track.
The workflow and its inputs are documented in [CI.md](CI.md#mobile-build).
Over-the-air JavaScript updates are in [OTA.md](OTA.md). The CI workflows are in [CI.md](CI.md).

## Store records this app uses

This app replaces the existing "PostHog" iOS app and uses a new Google Play app record.
The iOS store build keeps the existing identity, so an update replaces the old app on people's phones.
Android uses `com.posthog.mobile`, which installs separately from the older `com.posthog.code.mobile` app.
Development and preview builds use their own identities, see [Build variants](#build-variants).

| Field | Value |
| --- | --- |
| App name | PostHog |
| iOS bundle id | `com.posthog.code.mobile` |
| Android package | `com.posthog.mobile` |
| Expo owner and slug | `posthog` / `posthog` |
| EAS project id | `4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9` |
| App Store Connect app id | `6762366098` |
| Google Play track for submissions | `internal` |

The old app's source is `products/desktop/apps/mobile`, and its workflows are "Desktop Mobile Build" and "Desktop Mobile Promote".
Both iOS apps share the same store record and remote build-number counter.
Stop building the old iOS app before the first build of this one goes to the store.

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

Version `1.3.0` adds `expo-system-ui`, automatic native appearance and a dark launch screen.
Every EAS profile needs a new native build to include these changes.
JavaScript-only updates for existing `1.2.0` and `1.2.1` builds must retain their native dependencies and configuration.

## Build profiles

Profiles are in `eas.json`. Each profile has its own update channel and EAS environment.

| Workflow profile | Signing | Who installs it | Update channel |
| --- | --- | --- | --- |
| `development` | Ad hoc (iOS), APK (Android) | Developers, with Metro for live reload | `development` |
| `preview` | Ad hoc (iOS), APK (Android) | Internal testers on registered devices | `preview` |
| `production` | App Store (iOS), app bundle (Android) | TestFlight, Play internal track, then the stores | `production` |

`appVersionSource` is `remote`, so EAS stores the iOS build number and the Android version code.
Production builds raise them automatically (`autoIncrement`).
Check the current values with `eas build:version:get`.

The workflow runs `scripts/eas-build.sh`.
It uploads only `products/mobile`, filtered by `.easignore`.
Without it, EAS uploads the whole repository and installs the root pnpm workspace, which excludes this app.

## Build variants

Each profile sets `APP_VARIANT` in its `env` block in `eas.json`, and `app.config.ts` gives each variant its own identity.
The three variants install side by side on one device. They do not share sign-in, settings or the widget's data.
The names, id suffixes and schemes are in `src/lib/appVariants.json`.

| Variant | Profile | App name | iOS bundle id | Android package | URL scheme | iOS App Group | Icon |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `development` | `development` | PostHog Dev | `com.posthog.code.mobile.dev` | `com.posthog.mobile.dev` | `posthog-dev` | `group.com.posthog.code.mobile.dev` | `icon-dev.png`, amber DEV band |
| `preview` | `preview` | PostHog Preview | `com.posthog.code.mobile.preview` | `com.posthog.mobile.preview` | `posthog-preview` | `group.com.posthog.code.mobile.preview` | `icon-preview.png`, purple PREVIEW band |
| `production` | `production` | PostHog | `com.posthog.code.mobile` | `com.posthog.mobile` | `posthog` | `group.com.posthog.code.mobile` | `app.icon` on iOS 26, `icon.png` elsewhere |

- The widget extension's bundle id is the app's id plus `.HedgehogWidget`, for example `com.posthog.code.mobile.dev.HedgehogWidget`.
- The production profile also sets `EXPO_PUBLIC_SIGNUP_LINK=0`, so store builds hide "Create an account".
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
   Reuse the existing iOS distribution certificate and provisioning profiles.
   Set up an Android upload keystore for `com.posthog.mobile` before its first build.
   Reuse that keystore for subsequent releases: Google Play rejects bundles signed with a different upload key.
5. Register the internal identities from [Build variants](#build-variants) in the Apple Developer account, under Certificates, Identifiers & Profiles:
   - App IDs `com.posthog.code.mobile.dev`, `com.posthog.code.mobile.dev.HedgehogWidget`, `com.posthog.code.mobile.preview` and `com.posthog.code.mobile.preview.HedgehogWidget`.
   - App Groups `group.com.posthog.code.mobile.dev` and `group.com.posthog.code.mobile.preview`.
   - Turn on the App Groups capability for all four App IDs and select the group of the same variant. Turn on Push Notifications for the two app ids.

   Configure the matching ad hoc provisioning profiles in EAS before starting the workflow.
   Check that each App ID has its App Group linked. A missing group leaves the widget without the app's data.
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
2. Include the device in the development provisioning profile in EAS. Start **Mobile Build** from
   GitHub Actions with profile `development`, platform `ios`, and submit unchecked.
3. When the build finishes, open the EAS build page on the iPhone and tap Install.
4. Start Metro on your Mac and open the app on the iPhone:

   ```sh
   pnpm start --dev-client
   ```

   The iPhone and the Mac must be on the same network.
   The app lists the running server. You can also scan the QR code from the terminal with the camera.

For Android, use the same workflow with profile `development` and platform `android`, then install the APK from the EAS build page.
No device registration is needed.

The development build installs as "PostHog Dev" next to the store app, and shows an amber "Dev build" ribbon on the sign-in screen and in Settings.

Rebuild the development build after a change to native code:
a new native module, a config plugin, or a native field in `app.config.ts`.

## Share a preview build

Preview builds have the release JavaScript bundled in, and they take updates from the `preview` channel.
Use them to test a change before it goes to TestFlight.

Start **Mobile Build** in GitHub Actions with profile `preview`, the platforms to test, and submit unchecked.
Testers install from the EAS build page. iOS testers need a registered device.

## Ship to TestFlight and the Play internal track

Only production builds can go to TestFlight. Preview builds use ad hoc signing, which App Store Connect does not take.
Google Play also uses the `production` build profile: it creates an app bundle with the store package,
while `preview` creates an APK with a separate package for direct installation.

For the first Google Play release, create a free app record for `com.posthog.mobile` in Play Console.
An account owner must approve the policy, Play App Signing and export declarations.
On **Testing > Internal testing**, create and select a tester email list, then upload the production `.aab`
under **Create new release**. Review and publish to the internal track, then share the opt-in link from
the **Testers** tab. Tester email addresses must belong to Google accounts.
The store listing and other setup tasks can be completed before expanding beyond internal testing.
See [Google Play internal testing](https://support.google.com/googleplay/android-developer/answer/9845334)
and [Expo manual submission](https://docs.expo.dev/submit/android-manual/).

Run **Mobile Build** in GitHub Actions from `master`, with profile `production`, the target platforms,
and submit checked. Store submissions are allowed only from `master`.
EAS submits each build when it finishes. Follow progress on the EAS project page; a successful workflow
run means EAS accepted the build request, so confirm the build and submission also finish successfully.

After the iOS upload, App Store Connect processes the build for 5 to 30 minutes before it shows in TestFlight.

## Release to the stores

1. Test the TestFlight build and the Play internal build.
2. In App Store Connect, add the build to a new version, write the release notes, and submit it for review.
3. In the Play Console, promote the internal release to production.
4. Raise `version` in `app.config.ts` after the release, so the next native build gets a new version and runtime version.

## Before you share a build

- Complete the [mobile app release checks](../../../docs/internal/mobile-release-checks.md).
- `pnpm typecheck`, `pnpm lint` and `pnpm test` pass.
- The demo walkthrough passes on the iOS simulator. See [TESTING.md](TESTING.md).
- Sign in to a real project and open a report, on the build you are about to share.
