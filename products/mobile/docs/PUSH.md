# Push notifications

Code: `src/features/notifications/`, `src/api/pushTokens.ts`. The root layout installs both hooks.

## Token lifecycle

| When | What happens |
| --- | --- |
| App start | `configureNotifications()` sets the foreground handler (banner and list, no sound, no badge) and creates the Android channel `default`. |
| After sign in | `usePushRegistration()` asks for permission once (`prompted` is persisted), gets the Expo push token with the EAS project id, and `POST /api/users/@me/push_tokens/` `{ token, platform: 'ios' \| 'android' }`. |
| Every later launch | Registers again without asking. The server upserts on (user, token), so this only refreshes `last_seen_at`. |
| OS rotates the token | `addPushTokenListener` unregisters the old token before registering the new one. A failed delete keeps the old token for retry. |
| App returns to the foreground | Rereads the permission and retries registration after an error, a missing token or a session change. |
| Settings, "Enable notifications" or "Try again" | Asks when the system allows it, retries a failed registration, or opens system settings when permission is blocked. |
| Sign out or account switch | Waits for in-flight registration, then sends `POST /api/users/@me/push_tokens/unregister/` `{ token }` before changing credentials. A failed delete keeps the session and offers a retry. |

The server keeps at most 20 tokens per user and evicts the oldest. Both endpoints need `user:write`.
The app saves a newly issued token before its registration POST, because a lost response does not prove the server rejected it. Registration and unregistration requests have bounded deadlines. A failed storage read lets the launch gate settle with default push state.

Push is unavailable, and the app skips it without errors, on the web, in simulators and emulators, and in Expo Go.
Settings shows which one applies.

## Credentials

The app sends no push itself. The server posts to the Expo push service, which delivers through APNs on iOS and FCM on Android.
EAS keeps the delivery credentials, and the Android build also needs the Firebase app config.
Someone with access to the Apple Developer team, the Firebase project and the `posthog` Expo organization does each step once.

| Variant | iOS bundle id | Android package |
| --- | --- | --- |
| Store (`production`) | `com.posthog.code.mobile` | `com.posthog.code.mobile` |
| `preview` | `com.posthog.code.mobile.preview` | `com.posthog.code.mobile.preview` |
| `development` | `com.posthog.code.mobile.dev` | `com.posthog.code.mobile.dev` |

**iOS: APNs key.**

1. In the Apple Developer account, create an APNs authentication key (`.p8`), or reuse the team's existing one. One key serves every bundle id in the team.
2. Run `eas credentials`, choose iOS and each build profile, then Push Notifications, and add or select that key.
   EAS stores the key per bundle id, so repeat it for the preview and development bundle ids.

**Android: Firebase.**

1. In a Firebase project, add an Android app for each package in the table that should get pushes.
   Download `google-services.json`. One file lists every Android app in the project.
2. Upload that file to each EAS environment as a file variable. The Android build reads its path from `GOOGLE_SERVICES_JSON` (see `app.config.ts`):

   ```sh
   eas env:create --environment production --name GOOGLE_SERVICES_JSON --type file --value ./google-services.json --visibility sensitive
   eas env:create --environment preview --name GOOGLE_SERVICES_JSON --type file --value ./google-services.json --visibility sensitive
   eas env:create --environment development --name GOOGLE_SERVICES_JSON --type file --value ./google-services.json --visibility sensitive
   ```

3. In the Firebase console, open Project settings, Service accounts, and generate a private key (a JSON file).
   Run `eas credentials`, choose Android and each package, then Google Service Account, and upload the key for push notifications (FCM V1).
4. For a local Android build, copy the file to `products/mobile/google-services.json`. git and `.easignore` both ignore it.

Without `google-services.json` the Android build still succeeds, but the app gets no push token and Settings shows "Couldn't turn on".

## Payloads

Server pushes are sent by `posthog/tasks/push_notifications.send_user_push` through the Expo push API.
Both senders are gated by the `posthog-code-mobile-push` feature flag, evaluated per user.

**Inbox** (`products/signals/backend/inbox_push_notifications.py`):

```json
{ "type": "report", "report_id": "<uuid>", "project_id": 2, "notificationKind": "report_visible" }
```

`notificationKind` is `report_visible` (a new report for its suggested reviewers) or `pull_request_ready`.

**Tasks** (`products/tasks/backend/push_dispatcher.py`):

```json
{ "taskId": "<uuid>", "taskRunId": "<uuid>", "projectId": 2, "notificationKind": "awaiting" }
```

Kinds: `completed`, `failed`, `cancelled`, `awaiting`, `turn_completed`, `thread_message` (with `messageId`, no run), `handoff` (no run).
`projectId` is the task's team id. Pushes from servers that predate it have no project id.

**Snooze reminders** are local notifications. They should use the inbox shape with `notificationKind: 'snooze_reminder'`, so the same routing opens the report.

## Routing

`useNotificationRouting()` handles taps that start the app (`getLastNotificationResponse`) and taps while it runs (`addNotificationResponseReceivedListener`).
It waits until the navigator is mounted and the session has loaded, and handles each notification id once.
The pure resolver is `resolveNotificationRoute()` in `notificationRouting.ts`.

| Payload | Route |
| --- | --- |
| `type: 'report'`, project is current or absent | `/report/{report_id}` |
| `type: 'report'`, another project the user has | switch project, then `/report/{report_id}` |
| `type: 'report'`, a project the user does not have | `/inbox` |
| `taskId` with `projectId` | `GET /api/projects/{projectId}/tasks/{taskId}/` only, or `/inbox` when the user does not have that project. `signal_report` set: switch project if needed, then `/report/{signal_report}`. Otherwise `/inbox`. |
| `taskId` without `projectId` | The same lookup in the current project, then the others (at most 8 lookups). |
| anything else | nothing |

A tap turns demo mode off, because a push is about live data.
Every tap captures `mobile_push_opened` with `kind` (the payload's `notificationKind`, else `report`, `task` or `unknown`).
A push that arrives while the app is open captures `mobile_push_received` with `kind` and `shown` (false when the user is on that report or snoozed it).
A permission prompt captures `mobile_push_permission_resolved` with `permission`, `can_ask_again` and `trigger` (`auto` for the first signed-in run, `settings` for the Enable button).
Registration captures `mobile_push_registration_finished` with `ok` and `trigger`, plus `reason` (`token_unavailable`, `network`, `api_error` or `unknown`) on failure. A success counts only a new registration, not the silent one on every launch.
The Settings button captures `mobile_push_enable_pressed` with `action` (`request` or `open_system_settings`).

## Testing

1. Install a development build on a physical device and sign in. Allow notifications.
2. Settings, Notifications, shows "On" and the device token (`ExponentPushToken[…]`).
3. Send a test push with the Expo CLI:

   ```sh
   npx expo push:send --to 'ExponentPushToken[...]' --title 'New report' --body 'Checkout fails on Safari' \
     --data '{"type":"report","report_id":"<report id>","project_id":2}'
   ```

   If your CLI has no `push:send`, post to the Expo push API directly:

   ```sh
   curl -s https://exp.host/--/api/v2/push/send -H 'Content-Type: application/json' \
     -d '{"to":"ExponentPushToken[...]","title":"New report","body":"Checkout fails on Safari","data":{"type":"report","report_id":"<report id>","project_id":2}}'
   ```

4. Tap it with the app killed, in the background and in the foreground (the banner shows). Each opens the report.
5. Repeat with `{"taskId":"<task id>","notificationKind":"awaiting"}` for a task linked to a report, and for one without a report (opens the inbox).
6. For real server pushes, enable `posthog-code-mobile-push` for your user and trigger a task run or a new report.
7. Sign out and check that `POST …/push_tokens/unregister/` ran (server logs or the token row is gone).
