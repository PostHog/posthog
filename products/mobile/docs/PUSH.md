# Push notifications

Code: `src/features/notifications/`, `src/api/pushTokens.ts`. The root layout installs both hooks.

## Token lifecycle

| When                                            | What happens                                                                                                                                                                                                    |
| ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| App start                                       | `configureNotifications()` sets the foreground handler (banner and list, no sound, no badge) and creates the Android channel `default`.                                                                         |
| After sign in                                   | `usePushRegistration()` asks for permission once (`prompted` is persisted), gets the Expo push token with the EAS project id, and `POST /api/users/@me/push_tokens/` `{ token, platform: 'ios' \| 'android' }`. |
| Every later launch                              | Registers again without asking. The server upserts on (user, token), so this only refreshes `last_seen_at`.                                                                                                     |
| OS rotates the token                            | `addPushTokenListener` unregisters the old token before registering the new one. A failed delete keeps the old token for retry.                                                                                 |
| App returns to the foreground                   | Rereads the permission and retries registration after an error, a missing token or a session change.                                                                                                            |
| Settings, "Enable notifications" or "Try again" | Asks when the system allows it, retries a failed registration, or opens system settings when permission is blocked.                                                                                             |
| Sign out or account switch                      | Waits for in-flight registration, then sends `POST /api/users/@me/push_tokens/unregister/` `{ token }` before changing credentials. A failed delete keeps the session and offers a retry.                       |

The server keeps at most 20 tokens per user and evicts the oldest. Both endpoints need `user:write`.
A successful registration assigns the token to the current user and removes other users' registrations of that token on the same instance. Concurrent registrations of the same token are serialized, including when no row exists yet.

An expired session cannot authenticate an unregister request. Until the device successfully registers again on that instance, its previous registration can still receive pushes. Registration on another region or self-hosted instance cannot remove registrations on the old host. Explicit sign-out therefore still requires push cleanup before credentials are discarded. Messages already queued for delivery can also arrive after cleanup.

The app saves a newly issued token before its registration POST, because a lost response does not prove the server rejected it. Registration and unregistration requests have bounded deadlines. A failed storage read lets the launch gate settle with default push state.

Push is unavailable, and the app skips it without errors, on the web, in simulators and emulators, and in Expo Go.
Settings shows which one applies.

## Credentials

The app sends no push itself. The server posts to the Expo push service, which delivers through APNs on iOS and FCM on Android.
EAS keeps the delivery credentials, and the Android build also needs the Firebase app config.
Someone with access to the Apple Developer team, the Firebase project and the `posthog` Expo organization does each step once.

| Variant              | iOS bundle id                     | Android package              |
| -------------------- | --------------------------------- | ---------------------------- |
| Store (`production`) | `com.posthog.code.mobile`         | `com.posthog.mobile`         |
| `preview`            | `com.posthog.code.mobile.preview` | `com.posthog.mobile.preview` |
| `development`        | `com.posthog.code.mobile.dev`     | `com.posthog.mobile.dev`     |

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
All server pushes respect the account's push notification preferences. Ordinary chat and task pushes do not require a feature flag. Report pushes also require the existing `posthog-code-mobile-push` feature flag. Settings saves these in `users/@me/` `notification_settings`: `mobile_push_enabled` (master), `mobile_push_tasks_enabled` (mobile chats and tasks), `mobile_push_reports_enabled` (new reports), and `mobile_push_report_updates_enabled` (report updates). All default to enabled. The server checks preferences again before delivery, so disabling a category also stops queued pushes.

Chat and task notifications are eligible for work started in the mobile app, or work you actively continue there. Sending a message, starting or resuming a run, or answering an agent question from mobile enables updates for your account on that task, including chats originally started on the web or Slack. Merely opening a chat, reading its history, or watching its stream does not enable updates. Configuration changes and canceling a run also do not enroll the task.

Continuing a chat on mobile transfers its agent-update notifications to mobile for that user: automated run/chat @mentions, stream recipient targeting, and lifecycle/PR notifications stop targeting the enrolled user on Slack. Artifact and comment DMs remain unchanged because mobile does not yet offer the corresponding comment reader and deep links. Shared Slack thread content and notifications for other participants remain. Slack may still send its own subscribed-thread alerts for shared replies; PostHog cannot turn off those user-managed Slack subscriptions. Web activity, history, and unread state remain available. Report notifications are independent of where their associated work started: new reports and meaningful report updates have separate controls.

**Inbox** (`products/signals/backend/inbox_push_notifications.py`):

```json
{ "type": "report", "report_id": "<uuid>", "project_id": 2, "notificationKind": "report_visible" }
```

`notificationKind` is `report_visible` (a new report for its suggested reviewers), `pull_request_ready`, or `report_completed`, `report_failed`, `report_cancelled`, `report_awaiting`, `report_turn_completed`, `report_pr_merged`, and `report_pr_closed` (with `taskRunId`). Report updates cover meaningful milestones of implementation or research work: needs input, a finished turn, completion, failure, cancellation, or a pull request being merged or closed. They use report links and the report updates preference even when the work began outside mobile. `pull_request_ready` includes `pullRequestId` to deduplicate a single PR without hiding other PRs on the report. A report discussion remains a chat and follows the chat and task updates preference.

**Tasks** (`products/tasks/backend/push_dispatcher.py`):

```json
{ "type": "task", "taskId": "<uuid>", "taskRunId": "<uuid>", "projectId": 2, "notificationKind": "awaiting" }
```

The server records the `X-PostHog-Client-Platform: mobile` creation header on the task; subsequent runs do not change its origin. Active continuation from mobile records a separate user-specific notification enrollment rather than rewriting that origin. Tasks created before the server stored the creation marker stay silent until actively continued in mobile; history alone cannot reliably establish mobile origin, and there is no backfill.

Kinds: `completed`, `failed`, `cancelled`, `awaiting`, `turn_completed`, `thread_message` (with `messageId`, no run), `handoff` (no run), `pr_merged`, and `pr_closed` (with `pullRequestUrl`).
`projectId` is the task's team id. Pushes from servers that predate it have no project id.

**Pull request outcomes** come from verified PR close events through `notify_task_pull_request_outcome()`. Ordinary task pushes use title `PostHog` and body `"{task title}" pull request was merged` or `"{task title}" pull request was closed`, with `Untitled task` as the blank-title fallback. Report work uses title `Report update`, the same suffix with the report title (`Untitled report` fallback), and the report updates preference. Both carry `pullRequestUrl` as the stable PR identity. A durable per-recipient, task, PR, and outcome claim prevents retry duplicates independently of Slack announcement history.

**Snooze reminders** are local notifications. They use the inbox shape with `notificationKind: 'snooze_reminder'`, so the same routing opens the report.

## Routing

`useNotificationRouting()` handles taps that start the app (`getLastNotificationResponse`) and taps while it runs (`addNotificationResponseReceivedListener`).
It waits until the navigator is mounted and the session has loaded, and handles each notification id once.
The pure resolver is `resolveNotificationRoute()` in `notificationRouting.ts`.

Chat taps reuse the single chat screen. If the target task is already open in the same account
and project, the tap leaves its session and draft intact. Otherwise it replaces the open chat
with the target conversation. The comparison uses the live session's task, so it also works for
chats started in the composer and after the person taps New chat. Close returns to the screen
underneath without stepping through older chats.

| Payload                                                  | Route                                                                                                                                                                                                                                                        |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `type: 'report'`, project is current or absent           | `/report/{report_id}`                                                                                                                                                                                                                                        |
| `type: 'report'`, another project the user has           | switch project, then `/report/{report_id}`                                                                                                                                                                                                                   |
| `type: 'report'`, a project the user does not have       | `/inbox`                                                                                                                                                                                                                                                     |
| `type: 'task'` with `taskId` and `projectId`             | Validate access with `GET /api/projects/{projectId}/tasks/{taskId}/`, switch project if needed, then `/chat?taskId={taskId}`, including report discussions. Missing tasks or inaccessible projects go to `/inbox`.                                           |
| Legacy `taskId` with `projectId`, without `type: 'task'` | `GET /api/projects/{projectId}/tasks/{taskId}/` only, or `/inbox` when the user does not have that project. `signal_report` set: switch project if needed, then `/report/{signal_report}`. Otherwise switch project if needed, then `/chat?taskId={taskId}`. |
| `taskId` without `projectId`                             | The same lookup in the current project, then the others (at most 8 lookups).                                                                                                                                                                                 |
| anything else                                            | nothing                                                                                                                                                                                                                                                      |

A tap turns demo mode off, because a push is about live data.
A task lookup that finishes after the account changes cannot navigate the new account.
Every tap captures `mobile_push_opened` with `kind` (the payload's `notificationKind`, else `report`, `task` or `unknown`).
A push that arrives while the app is open captures `mobile_push_received` with `kind` and `shown` (false when the user is viewing that task or report, or has time-snoozed the report). Explicit task pushes are suppressed only when that chat is open; viewing its linked report does not hide a discussion reply. Legacy task payloads retain report-association suppression. Foreground delivery never plays sound or sets a badge.

Time snooze reminders are scheduled on the device after an explicit snooze action. They follow system notification permission and are separate from the account's server push categories. A signal-based snooze does not schedule a timed reminder. Repeated delivery of the same notification is suppressed before receipt analytics in the foreground; terminal task and report-work outcomes are also deduplicated by run.
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
5. Repeat with `{"taskId":"<task id>","notificationKind":"awaiting"}` for a task linked to a report, and for one without a report (opens its chat).
6. For real server pushes, trigger a task run started or actively continued in mobile. To test report pushes, also enable `posthog-code-mobile-push` for your user and trigger a new report or report update.
7. Sign out and check that `POST …/push_tokens/unregister/` ran (server logs or the token row is gone).
