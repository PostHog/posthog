# Over-the-air updates

EAS Update ships JavaScript and asset changes to installed builds without a store release.
Native changes still need a new build, see [RELEASING.md](RELEASING.md).

Production OTA updates use a release request merged to `master` and approval from a required `mobile-production` environment reviewer. See [Releasing](RELEASING.md#request-a-hosted-release) for request creation, prerequisites and recovery.

## How a device gets an update

- `expo-updates` checks `https://u.expo.dev/4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9` each time the app starts.
- The app also checks on return to the foreground and approximately every 15 minutes while open. Checks are at least 15 minutes apart,
  including the native startup check, and cannot overlap. Failed checks or downloads retry at a later check.
- Production builds verify each update signature using the public certificate embedded in the native binary before applying it. Unsigned updates or updates signed by another key are rejected. Local production config disables OTA until its certificate is provisioned; hosted releases require it. See [OTA signing setup](RELEASING.md#ota-signing-setup-and-rotation).
- Available updates download silently without blocking startup. Downloads wait for the native startup procedure to finish.
- A downloaded update applies automatically when the app returns after at least five minutes in the background, provided
  it is on an Inbox, Chats or Views tab, the keyboard is closed, and no API request, notification navigation or TanStack
  mutation is pending. A one-second grace period lets navigation settle before checking these conditions. There is a brief reload;
  the user does not need to force-close the app.
- Returning to an open chat, report, settings page or other form defers the reload until a later eligible return.
  This keeps active chat sessions and unsaved input intact. Saved chat drafts remain on the device across reloads.
- Downloads that finish during a session wait for that later return, or the next cold start, before applying.
- Development builds load JavaScript from Metro and ignore updates.

This behavior uses the existing native update library and can itself ship as an OTA. Builds that have not received it
still use the previous startup-only flow: one cold start downloads it and a later cold start runs it.

## Channels

Each build profile in `eas.json` sets a channel, and the build listens to that channel for life.
Channels are managed by EAS. Production updates are promoted by the hosted release workflow.

| Profile       | Channel       | Distribution                       |
| ------------- | ------------- | ---------------------------------- |
| `development` | `development` | Metro; OTA is not used.            |
| `preview`     | `preview`     | Internal builds from Mobile Build. |
| `production`  | `production`  | Hosted `ota` release requests.     |

TestFlight and public-store builds share the production channel. An OTA can reach both when their runtime versions match; TestFlight is not a separate OTA audience.

The workflow loads the EAS production environment and explicitly sets `APP_VARIANT=production` and `EXPO_PUBLIC_SIGNUP_LINK=0`. The `env` block of an EAS build profile applies only to builds, so OTA publication sets the same values itself.

Do not run `pnpm update`. That is pnpm's own command, and it upgrades dependencies.

## Runtime version

`app.config.ts` sets `runtimeVersion.policy` to `appVersion`, so the runtime version equals `version` (now `1.4.0`).
An update reaches only the builds with the same runtime version.

The device's `appVersion` policy does not detect native changes. The hosted release workflow additionally compares Expo native fingerprints for both platforms against the last successful native release. You must raise `version` and request a native release when a change needs native code, for example:

- a new or upgraded package with native code (most `expo-*` and `react-native-*` packages),
- a new or changed config plugin, or a change to `ios`, `android` or `plugins` in `app.config.ts`,
- an Expo SDK upgrade.

An incompatible OTA request fails before publication. The first hosted release must be native to establish this compatibility baseline; the implementation PR contains no request and publishes nothing.

## Validate an update

Complete the [mobile app release checks](../../../docs/internal/mobile-release-checks.md). A preview build can verify behavior before merge, but it has a separate identity and channel. Hosted staging uses the production identity on an unlinked branch; it does not deliver the candidate to preview builds or provide a second manual tester gate after staging. The protected environment approval happens before staging.

1. Keep `version` unchanged for a JavaScript/assets-only fix. Find the preceding completed request in the latest mobile release receipt.
2. Prepare a request locally; this command only writes a file:

   ```sh
   cd products/mobile
   pnpm release:request ota --id fix-chat-layout --previous <completed-request-id> --notes "Fix the chat layout"
   ```

3. Include the request and fix in a PR. On merge to `master`, Mobile Release runs the required checks, waits for the required deployment review, verifies native compatibility, stages the update on an unlinked EAS branch, and promotes that exact group to production. Local `update:production` and `update:preview` commands no longer publish.
4. Verify the completed receipt and device behavior. Open the app on an Inbox, Chats or Views tab with no keyboard open. Once a check has downloaded the update,
   background the app for at least five minutes and return. Settings in an internal build shows the new update id.
   Checks are throttled to once per 15 minutes, so a return immediately after publishing may not fetch it yet.
   Also verify that returning to an open chat preserves the draft and defers the reload, and that an offline launch
   opens normally. To test the first OTA that adds this behavior, use the previous two-cold-start flow once.

The workflow publishes to the full compatible production audience. Staged percentage rollouts are not exposed by the request schema yet.

## Roll back

For a normal rollback, revert the faulty JavaScript change in a new PR and add an `ota` request following the last completed release. Do not edit an old request or move the production pointer manually. The same tests and compatibility checks apply.

If publication stopped after claiming a request, follow the reconciliation procedure in [RELEASING.md](RELEASING.md) before requesting another release. Do not rerun a local EAS publish command to work around the receipt.

A rollback follows the same download and safe-return policy as an update. A cold start can also apply a staged rollback.

## See what a device runs

Settings shows the app version in every build.
Development and preview builds also show an Environment group: the build variant, the update channel, the update (the first 8 characters of `Updates.updateId` and the time of `Updates.createdAt`, or "Built in" when the app runs the JavaScript inside the build), and the API host kind.
Store builds do not show the channel or update.
The app's own analytics events carry `app_variant`, `update_channel`, `api_host_kind`, `data_mode` (`demo` or `live`, null until the demo flag loads) and `project_id` (null when signed out) as super properties.
On the EAS project page, the Updates tab lists each update group with its runtime version, platforms and commit message.
