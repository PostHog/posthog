# Releasing

Use **Mobile Release** for native store builds and production OTA updates after a release request merges to `master`.
Native releases stop at TestFlight and the Play internal track; public-store promotion follows testing.
Use **Mobile Build** for development and preview builds. Both workflows are documented in [CI.md](CI.md).
Over-the-air JavaScript updates are in [OTA.md](OTA.md). The CI workflows are in [CI.md](CI.md).

## Request a hosted release

Production releases run in GitHub Actions after a release request merges to `master` and an authorized reviewer approves the `mobile-production` deployment.
Add the request to the same PR as the app changes. Do not publish production builds or updates from a local checkout.
The implementation includes no active request, so merging the release tooling alone publishes nothing.

From `products/mobile`, choose one:

```sh
# First hosted release: raise version in app.config.ts above 1.4.0 first.
pnpm release:request native --id native-150 --initial --notes "Describe the changes testers should verify."

# Later native release: raise version again; name the last completed request.
pnpm release:request native --id native-160 --previous native-150 --notes "Describe the native changes."

# JavaScript/assets only: keep the installed native runtime version.
pnpm release:request ota --id chart-legend-fix --previous native-160 --notes "Fix the chart legend."

pnpm release:check
pnpm release:test
```

Commit the generated `releases/requests/<id>.json` with the source changes. Review its kind, version, predecessor and release notes.
IDs use lowercase letters, digits and hyphens. Requests are append-only: never edit, rename or delete one after merging it.
Only one new request may appear in a master push. `previousRelease` names the last completed request, including OTA requests. A corrective request can explicitly follow that receipt when an earlier request failed before publication; the failed manifest remains historical and inert.
The template at `releases/request.json.example` is inert and may also be copied and filled in manually.
Release notes and receipts are public; keep customer data, credentials and private operational details out of them.

`native` produces both production binaries, waits for both builds to finish, then submits those exact build IDs to TestFlight and Play internal testing.
It never selects `--latest`. The job waits for EAS submission to finish; Apple can still need processing time before TestFlight makes the build available.
Public App Store review and Play production promotion remain manual after testing.

`ota` requires a successful hosted native release first. The request version must match the current app version and that native receipt's runtime.
The workflow compares Expo fingerprints for both platforms against the recorded native baseline.
Native build results must also provide matching EAS fingerprints before either binary is submitted.
A new native dependency, native configuration change, widget/plugin change or other fingerprint difference blocks OTA and requires a native request with a higher app version.
Remote EAS variables that affect native configuration must stay stable for a runtime; change them only with a new native release.
The first hosted native release must raise `version` above the existing `1.4.0` baseline in `releases/config.json`.
This deliberately establishes new binaries and a verified baseline instead of guessing compatibility with older manually built apps.

### What runs after merge

1. `Mobile Release` checks the exact master push diff. It selects only the newly added request, rather than sweeping historical requests.
2. The reusable `Mobile CI` runs typecheck, lint, Jest, release metadata validation and release policy tests on that exact commit. The simulator demo flows do not run in CI; run them locally before you merge.
3. An authorized reviewer approves the exact commit in the protected `mobile-production` GitHub environment. The publisher then loads the EAS `production` environment, fixes `APP_VARIANT=production` and disables the signup link.
4. Before contacting EAS to build or publish, it creates a durable draft GitHub receipt at `mobile-release/<id>`. This claims the request so an interrupted retry cannot duplicate a release.
5. A `mobile-staging` deployment records the stage. Native requests build production binaries with the pinned public OTA certificate; OTA requests sign and publish to an unlinked `mobile-staging-<id>` EAS branch.
6. Native requests submit the completed binaries. OTA requests sign and republish the exact staged group to the production channel; they do not rebuild the bundle during promotion.
7. The receipt records the source commit, request, staging deployment, build IDs or update groups, and the native runtime/fingerprints and OTA certificate fingerprint. It becomes a GitHub prerelease, and the dedicated annotated `mobile-production` tag points at the completed source.

The workflow runs only on trusted master pushes in `PostHog/posthog`. Pull requests have no publishing step or Expo token.
Development/preview builds remain manually available from `master` through `Mobile Build`; production is handled by release requests.
The package's old production build, submit and update commands stop with a hosted-release instruction.

### One-time hosted release setup

Keep the EAS credentials and store setup below. Also:

- Protect the `mobile-production` GitHub environment with **required reviewer Chris Volzer (`@cvolzer3`)**, allow self-review so the release owner can explicitly approve their own requests, disable administrator bypass, and restrict deployments to `master`. Review the request and full source diff of the exact deployment commit before approval. The workflow's `environment` field does not configure these server-side protections: a repository administrator must set them before any release request merges.
- Store a dedicated `MOBILE_PRODUCTION_EXPO_TOKEN` only in `mobile-production`. Create a separate `mobile-build` environment restricted to `master`, with a different `MOBILE_BUILD_EXPO_TOKEN` environment secret for internal builds. Do not create repository or organization secrets under these names; that would make them available outside their environment. Neither workflow falls back to the shared `EXPO_TOKEN`. Remove or revoke the inherited shared `EXPO_TOKEN` access to this production EAS project; changing these workflow references does not revoke an organization secret or its Expo authority. Coordinate any other workflows that still use it. Use the narrowest Expo account/project access available for the new tokens. Separate tokens do not impose EAS channel or build-profile authorization: both workflows also require trusted master source, and production OTA has an independent signing key.
- Provision OTA signing as described below before the first hosted native release. The public certificate belongs in the repository; the private key belongs only in the protected `mobile-production` environment. Native build jobs and dependency installation do not receive the private key.
- Permit the workflow's `GITHUB_TOKEN` to create releases/tags and deployment records. The workflow requests only contents and deployments write access in its publishing job.
- Keep production build-time variables readable as Plain text or Sensitive. The publisher audits both project variables and linked account variables before claiming a request; any Secret value blocks the release because it cannot be included in the compatibility check. Native signing/submission keys belong in EAS credentials; the OTA signing key belongs in the protected GitHub environment. Neither belongs in these variables.
- Set `GOOGLE_SERVICES_JSON` to a **Sensitive file** variable. The publisher reads its base64 file content through the authenticated Expo API, writes an ignored file with owner-only permissions, and uses it during fingerprinting and configuration. Neither contents nor other variable values appear in receipts or artifacts. Secret files, unreadable file values and other file-variable names fail closed before an EAS build or OTA publish. Native EAS fingerprint results must match these materialized inputs.
- The native environment is audited and fingerprinted again after staging. A change to variable names, types or contents blocks production publication, including removed values. Snapshot hashes stay in memory. Variables that overwrite GitHub identity, credentials or the runner command environment are rejected before any values are applied; the script imports the audited environment itself.
- Complete the initial Play Console app/signing/internal-tester setup before requesting the first Android submission. Confirm the production iOS App Store Connect record and stored API key.
- Stop using the older Desktop Mobile Build/Promote workflows for this iOS store identity. The release request flow does not retire those separate workflows.

### OTA signing setup and rotation

An operator must provision the signing material; no production key or certificate is generated by this implementation.
Follow [Expo's code-signing guide](https://docs.expo.dev/eas-update/code-signing/) using an account with the required EAS plan.
Generate an RSA key of at least 2048 bits outside this checkout. Commit only its public certificate as `releases/ota-certificate.pem`; keep the private key in the team's secure key store and as the `MOBILE_OTA_SIGNING_KEY` PEM secret only in `mobile-production`.
Never put it in EAS variables, the app directory, artifacts or a repository/organization secret.

Production config pins that certificate with key id `main` and algorithm `rsa-v1_5-sha256`.
Without the certificate, local development still works with production OTA disabled, and hosted native/OTA releases fail before claiming a request.
The publisher rejects an invalid or expired certificate and requires its matching private key before OTA staging.
Only an approved OTA publishing step writes the private key to an owner-readable temporary file outside the app upload; it deletes the file on exit.
Staging and promotion both pass the key to EAS, which signs the manifests locally. The native client verifies updates against its embedded certificate before applying them.

The first signed release must be **native**, with a version above the unsigned `1.4.0` baseline. Existing unsigned binaries must upgrade through TestFlight or the stores; this change cannot add verification to them through OTA.

Version `1.5.0` establishes that signed native baseline through the `native-150` release request.
It targets TestFlight and Google Play internal testing. Compatible OTA requests can follow only after its hosted release receipt is complete.

Version `1.6.0` follows `native-150` through the `native-160` native release request.
It includes full-screen chats with Back, New chat, Copy link to chat and Archive chat controls, readable insight-table numbers with horizontal scrolling, and safer release retries.
It targets TestFlight and Google Play internal testing and establishes a new runtime for compatible OTA updates.

The native receipt records the certificate fingerprint. An OTA request must match it as well as the native fingerprints; a receipt without a certificate fingerprint cannot authorize an OTA.
Rotate the key and certificate together, retain the old material securely for older runtimes, and raise the app version in a new native release before publishing updates with the new key.

### Receipts, ordering and retries

The workflow run and `mobile-production` deployment report its outcome. The `mobile-staging` deployment records the build/update staging outcome.
The GitHub prerelease `mobile-release/<id>` contains a machine-readable JSON receipt; the Actions run also retains a receipt artifact, including a claimed receipt if publishing fails.
Receipt lookup includes draft releases across every page of the release list. GitHub's release-by-tag endpoint only returns published releases and cannot find an interrupted draft claim.
Repeated entries across pages are deduplicated by numeric release ID, so only distinct releases can cause a duplicate-receipt error.
Receipt writes use the numeric release ID returned when the claim is created and explicitly retain its request tag. If multiple releases share a request tag, publication stops before any EAS operation; reconcile every named release ID before retrying.
A completed request rerun does not repeat EAS publication. If only the production pointer update failed, rerunning repairs it without resubmitting.

GitHub keeps at most one pending job in a concurrency group. When several requests merge quickly, a newer pending job can replace an older one.
The predecessor check prevents the newer request from skipping it: it fails before claiming or publishing, with the missing predecessor named in its request.
Rerun the original predecessor workflow, then rerun its successor. Keep one release outstanding at a time for the simplest operation.
No run automatically changes its checkout to a newer master commit.

If a request has a draft/claimed receipt, **do not delete it and blindly rerun**. A timeout may have happened after EAS accepted an upload or submission.
Use its source commit, run URL, staged build IDs/group and EAS message (`mobile-release:<id>@<commit>`) to reconcile both platforms in EAS and the stores.
If nothing reached EAS, an operator may remove the draft receipt and rerun the original workflow.
If publication happened, repair that receipt and production pointer from the verified EAS results, without resubmitting; retain the claim until reconciliation is complete.
A partially submitted native release needs operator recovery of the unfinished platform using its recorded build ID, rather than a new automatic build.
A corrective request may follow the last completed receipt only when the failed request was never claimed. Any sibling request with a receipt blocks that correction until its publication or production pointer has been reconciled.
These recovery operations require release access and are exceptional; routine publication stays in GitHub Actions.

## Store records this app uses

This app replaces the existing "PostHog" iOS app and uses a new Google Play app record.
The iOS store build keeps the existing identity, so an update replaces the old app on people's phones.
Android uses `com.posthog.mobile`, which installs separately from the older `com.posthog.code.mobile` app.
Development and preview builds use their own identities, see [Build variants](#build-variants).

| Field                             | Value                                  |
| --------------------------------- | -------------------------------------- |
| App name                          | PostHog                                |
| iOS bundle id                     | `com.posthog.code.mobile`              |
| Android package                   | `com.posthog.mobile`                   |
| Expo owner and slug               | `posthog` / `posthog`                  |
| EAS project id                    | `4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9` |
| App Store Connect app id          | `6762366098`                           |
| Google Play track for submissions | `internal`                             |

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

| Workflow profile | Signing                               | Who installs it                                  | Update channel |
| ---------------- | ------------------------------------- | ------------------------------------------------ | -------------- |
| `development`    | Ad hoc (iOS), APK (Android)           | Developers, with Metro for live reload           | `development`  |
| `preview`        | Ad hoc (iOS), APK (Android)           | Internal testers on registered devices           | `preview`      |
| `production`     | App Store (iOS), app bundle (Android) | TestFlight, Play internal track, then the stores | `production`   |

`appVersionSource` is `remote`, so EAS stores the iOS build number and the Android version code.
Production builds raise them automatically (`autoIncrement`); the public app/runtime version still needs a deliberate bump in each native release PR.
Check the current values with `eas build:version:get`.

Mobile Build runs `scripts/eas-build.sh`; Mobile Release uses the hosted release helper.
Both upload only `products/mobile`, filtered by `.easignore`.
Without it, EAS uploads the whole repository and installs the root pnpm workspace, which excludes this app.

The hosted publisher accepts only these EAS production inputs: `APP_VARIANT`, `APPLE_TEAM_ID`,
`GOOGLE_SERVICES_JSON`, `EXPO_PUBLIC_POSTHOG_KEY`, `EXPO_PUBLIC_POSTHOG_HOST`,
`EXPO_PUBLIC_DEMO_MODE`, `EXPO_PUBLIC_SIGNUP_LINK`, `EXPO_PUBLIC_OAUTH_US_CLIENT_ID`, and
`EXPO_PUBLIC_OAUTH_EU_CLIENT_ID`. It refuses unrecognized names before importing any values.
Adding an app build input requires updating the publisher's allowlist. The publisher always sets
`APP_VARIANT=production` and `EXPO_PUBLIC_SIGNUP_LINK=0`.

## Build variants

Each profile sets `APP_VARIANT` in its `env` block in `eas.json`, and `app.config.ts` gives each variant its own identity.
The three variants install side by side on one device. They do not share sign-in, settings or the widget's data.
The names, id suffixes and schemes are in `src/lib/appVariants.json`.

| Variant       | Profile       | App name        | iOS bundle id                     | Android package              | URL scheme        | iOS App Group                           | Icon                                       |
| ------------- | ------------- | --------------- | --------------------------------- | ---------------------------- | ----------------- | --------------------------------------- | ------------------------------------------ |
| `development` | `development` | PostHog Dev     | `com.posthog.code.mobile.dev`     | `com.posthog.mobile.dev`     | `posthog-dev`     | `group.com.posthog.code.mobile.dev`     | `icon-dev.png`, amber DEV band             |
| `preview`     | `preview`     | PostHog Preview | `com.posthog.code.mobile.preview` | `com.posthog.mobile.preview` | `posthog-preview` | `group.com.posthog.code.mobile.preview` | `icon-preview.png`, purple PREVIEW band    |
| `production`  | `production`  | PostHog         | `com.posthog.code.mobile`         | `com.posthog.mobile`         | `posthog`         | `group.com.posthog.code.mobile`         | `app.icon` on iOS 26, `icon.png` elsewhere |

- The widget extension's bundle id is the app's id plus `.HedgehogWidget`, for example `com.posthog.code.mobile.dev.HedgehogWidget`.
- The production profile also sets `EXPO_PUBLIC_SIGNUP_LINK=0`, so store builds hide "Create an account".
- In the app, `src/lib/environment.ts` reads the variant from the bundle id, so an update cannot change it.
  A Metro bundle always counts as development.
- Development and preview builds show an environment ribbon on the sign-in screen and in Settings, and a Settings Environment group.
  They accept HTTP on `localhost`, `127.0.0.1` and `[::1]`, and prefill the local dev OAuth client id. Store builds do none of this.
  Android's release network policy allows those exact loopback hosts only in development and preview variants; production release binaries deny cleartext. Local debug builds retain Expo's cleartext allowance for Metro on the local network, including with the store identity. A native rebuild is needed to change either policy. See [Auth](AUTH.md#redirect-uris) for port forwarding.
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

   Do not add `APP_VARIANT` or `EXPO_PUBLIC_SIGNUP_LINK` here. `eas.json` and the hosted publisher set them.

9. Create separate non-first-party public OAuth applications in US and EU for `posthog-dev://callback` and `posthog-preview://callback`. Set their IDs as `EXPO_PUBLIC_OAUTH_US_CLIENT_ID` and `EXPO_PUBLIC_OAUTH_EU_CLIENT_ID` in both EAS internal environments. Production first-party applications must keep only `posthog://callback`; remove internal callback URIs if already added. See [AUTH.md](AUTH.md#redirect-uris).
10. Complete the protected environments and separate token setup in [One-time hosted release setup](#one-time-hosted-release-setup). The desktop mobile workflows' shared `EXPO_TOKEN` is not used by these workflows.

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
   GitHub Actions with profile `development` and platform `ios`.
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

Start **Mobile Build** in GitHub Actions with profile `preview` and the platforms to test.
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

Add a `native` release request to the app PR as described above. Once it merges and the hosted checks pass,
`Mobile Release` builds both platforms and waits for submission to TestFlight and the Play internal track.
Use the receipt's exact build IDs to follow progress in EAS and the stores.

After the iOS upload, App Store Connect processes the build for 5 to 30 minutes before it shows in TestFlight.

## Release to the stores

1. Test the TestFlight build and the Play internal build.
2. In App Store Connect, add the build to a new version, write the release notes, and submit it for review.
3. In the Play Console, promote the internal release to production.
4. Keep the released version while shipping compatible OTA fixes. Raise `version` in the PR for the next native release, so that request establishes a new runtime.

## Before you share a build

Complete the [mobile app release checks](../../../docs/internal/mobile-release-checks.md), including the demo walkthrough and real-account checks on each platform being shared. Hosted checks validate code and release policy; they do not verify store credentials, real sign-in, push delivery or physical-device behavior.
