# Over-the-air updates

EAS Update ships JavaScript and asset changes to installed builds without a store release.
Native changes still need a new build, see [RELEASING.md](RELEASING.md).

Shared OTA publishing is pending a repository workflow. This guide covers update behavior,
compatibility and validation for that release path.

## How a device gets an update

- `expo-updates` checks `https://u.expo.dev/4eb57b2f-79f6-4ab0-ae2c-bbd82af2cef9` each time the app starts.
- The app also checks on return to the foreground and approximately every 15 minutes while open. Checks are at least 15 minutes apart,
  including the native startup check, and cannot overlap. Failed checks or downloads retry at a later check.
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
Each channel points at the EAS branch with the same name.

| Profile | Channel | Branch |
| --- | --- | --- |
| `development` | `development` | `development` |
| `preview` | `preview` | `preview` |
| `production` | `production` | `production` |

A publishing workflow must use the same EAS environment and public configuration as builds on its
channel. The `env` block in `eas.json` applies only to builds, so updates also need the matching
`APP_VARIANT` and `EXPO_PUBLIC_SIGNUP_LINK=0` for production.

## Runtime version

`app.config.ts` sets `runtimeVersion.policy` to `appVersion`, so the runtime version equals `version` (now `1.3.0`).
An update reaches only the builds with the same runtime version.

The policy does not detect native changes. You must raise `version` when a change needs native code, for example:

- a new or upgraded package with native code (most `expo-*` and `react-native-*` packages),
- a new or changed config plugin, or a change to `ios`, `android` or `plugins` in `app.config.ts`,
- an Expo SDK upgrade.

Then make new builds. If you publish such a change as an update to the old runtime version, the app can crash on start.
Confirm native compatibility before publishing an update to an existing runtime version.

## Validate an update

Test a JavaScript-only change on a compatible preview build before promoting the same commit to
production through the shared publishing workflow once it is available.

1. Open the app on an Inbox, Chats or Views tab with no keyboard open. Once the update has downloaded,
   background the app for at least five minutes and return. Settings in an internal build shows the new
   update ID. Checks are throttled to once per 15 minutes, so an immediate return may not fetch it yet.
2. Return to an open chat and confirm the draft survives and the reload is deferred.
3. Launch offline and confirm the app opens normally. Builds still using the previous startup-only flow
   need one cold start to download an update and a later cold start to apply it.

## Rollback requirements

The shared publishing workflow needs a way to restore the last good update or the JavaScript embedded
in the native build. A rollback follows the same download and safe-return policy as an update.
A cold start can also apply a staged rollback.

## See what a device runs

Settings shows the app version in every build.
Development and preview builds also show an Environment group: the build variant, the update channel, the update (the first 8 characters of `Updates.updateId` and the time of `Updates.createdAt`, or "Built in" when the app runs the JavaScript inside the build), and the API host kind.
Store builds do not show the channel or update.
The app's own analytics events carry `app_variant`, `update_channel`, `api_host_kind`, `data_mode` (`demo` or `live`, null until the demo flag loads) and `project_id` (null when signed out) as super properties.
On the EAS project page, the Updates tab lists each update group with its runtime version, platforms and commit message.
