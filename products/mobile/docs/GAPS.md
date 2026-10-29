# Gaps

Known gaps and behavior that stays on the device.

## Product

- **Dark mode.** Light theme only (`userInterfaceStyle: 'light'`). Tokens are not split by scheme yet.
- **Dismiss and resolve from the inbox list.** Resolve and dismiss live on the report screen's action pill and the row's context menu; there is no bulk action.
- **Approve PR.** The PR card only opens the PR. Approving happens on GitHub.
- **External hand-off is a prepared prompt.** Claude Code and Codex get a deep link with the prompt, and copy is the fallback. There is no Cursor row, and the app never checks that the agent has the PostHog MCP connected.
- **Time-based snooze is local.** "In an hour", "Tomorrow", "Next week", "In a month" and
  "Custom…" hide the report on this device only. Other devices and the web app still show it.
  "Until more signals arrive" is the only server-side snooze.
- **Hidden navigation.** Teams, Notifications and Give feedback are not in v1.
  The project switcher chevron does nothing yet. The nav pill's Products slot leaves the app for the
  web product library, and is dimmed in demo mode because there is no project to open.
- **Agent progress UI.** The prototype's "Step N of M" segments are not shown; the run API has a
  free-text stage only.
- **Impact avatars.** The prototype data has avatar stacks on Impact facts that its template never
  draws; the app does not draw them either.
- **Chat** has no expanded composer; Expand is dimmed.

## Platform

- **Android text wrapping** is greedy, so a headline can end on a single word. iOS and web avoid it.
- **Hover states** only show on web.
- **`expo-localization` is unused.** Only the Today briefing request used it, for the timezone. Removing it needs a native rebuild.

## Verification limits

- No live PostHog was reachable while building. Every live path is covered by unit tests on
  fixtures shaped from the serializers and by browser runs against intercepted responses.
  The first real sign-in, hand-off, stream and chat need a device and an account.
- The web render check cannot show the iOS keyboard that some reference screenshots include.

## Chat

- **The suggested prompts stay visible behind the organization AI notice.** When the organization has not allowed AI processing, the empty state's prompt chips still render above the notice, and a tap on one has no composer to fill.
- **Legacy conversations are not listed.** The Chats list shows task sessions only.
  LangGraph chats made before the move stay in the web app's legacy view and `/ai?chat=<id>` links.
- **No message queueing while the agent works.** Stop replaces Send until the turn ends.
  The web queues messages typed meanwhile and joins them into one `user_message` after `turn_complete`.
- **No PostHog Desktop access pre-check.** A refused user learns it from the 403 on the first send.
  `GET /api/code/invites/check-access/` evaluates the server-side current team, which can differ from the app's project,
  and the project-scoped `desktop/access/` needs `llm_gateway:read`, which the app does not request.
- **Context items are re-sent with every message** while a chip stays attached. The web sends a report item once per task resume chain.
- **Report discussion limit.** A chat with exactly one attached report is an Inbox discussion task and counts toward the report's task limit.
  At the limit, `POST tasks/` or `run/` answers 429 `signal_report_task_cap`; the app shows the server copy and takes the message back. Attach a second report, or none, to chat without the limit.
- **One-report chats show as "Report" in Chats.** The `basic=true` list carries `origin_product` but not `signal_report_task_relationship`,
  so a discussion started on mobile gets the Report label and branch icon of a Create PR hand-off.
- **A push for a chat opens the Inbox.** Task push routing (`src/features/notifications/notificationRouting.ts`) opens the task's report, and a `posthog_ai` task has none, so it falls back to the Inbox instead of the chat sheet.
- **A replayed mode change does not replace a mode the app set.** Only a live `current_mode_update` does. If the agent changed mode while the stream was replaying after a lost cursor, the Mode chip keeps the app's mode until the agent reports one live.
- **No harness switch on a live run.** A chat started on Claude Code stays on it, and one on Codex stays on Codex. Start a new chat to switch.
- **`set_config_option` result shape is unverified.** The app treats a 2xx without a JSON-RPC `error` as applied.
  The agent server source is not in this repo; its built dist answers `{ configOptions }`.
- **In-progress reopen relies on the server backlog.** A live run is followed without a cursor and without reading `logs/`,
  which shows the whole thread only on thin-tail runs. The web reads `logs/` and reconciles on every connect.
- **Approvals, forms, charts and notebooks** the agent links show as links to the web app.
- **Files from history show by name only.** A picked image draws from the file on the device.
  A file in a stored thread has no local copy, and the app neither downloads it nor draws a thumbnail.
  `runs/{r}/artifacts/{id}/download/` answers with a 302 to a presigned S3 URL, and the app's bearer header must not follow the redirect to S3.
  `runs/{r}/artifacts/presign/` would avoid the redirect, but it needs the `storage_path` from the run's manifest, which the app does not read.
- **Sessions in the chat sheet.**
  - No artifacts or diff view. Only the PR card shows what the agent changed.
  - No undo of an answer.
  - Stop needs a started agent. Before the stream shows it generating, the sheet says the agent hasn't started yet.
  - The connection loop in `useSession.ts` is a copy of `useTaskRun`'s `followRun`. A fix to one needs the same fix in the other.

## Inbox and report data

- **`today:read` scope.** The Today page needs `today:read`. Without it in the OAuth request, the page returns 403 and the report screen always uses signal evidence.
- **Inbox API compatibility.** The inbox needs a server that supports `view=for_you` on the reports list.
- **Inbox paging.** Each page orders the list again. A report that moves down while the user scrolls can be skipped until the next refresh.
- **A change on the report screen refetches every loaded page.** Resolve, dismiss, reviewers, priority and hand-off invalidate the inbox list, and the list then refetches each loaded page in turn.
- **The signal snooze store is nearly redundant.** The server excludes a report snoozed until more signals from the `for_you` view, so the device entry only labels the row until the list refetches. The store and its labels could go.
- **Time snoozes do not sync** to other devices or the web, and are lost when the app's storage is cleared.
- **Inbox rows** carry no progress label.
- **Evidence** maps error, feedback and recording signals only. Scout findings, GitHub and analytics signals add no evidence block.
- **Work log** shows one page of 100 artefacts. Older entries of a very long log are not shown.
- **PR details.** The PR view has the URL, number, state and review decision. Checks for the selected canonical PR are fetched through `pr_checks/`, with the client fetch time. Title, diff size and the agent's note remain unavailable in the report API. A PR URL without a canonical id cannot fetch checks.
- **Read-state counts cover loaded reports only.** The menu does not fetch every page to compute a global unread total. Read state refreshes every 30 seconds while the inbox is active.

## Auth and push

- **No OAuth sign in on the web.** The web build offers the demo, and a personal API key in dev builds.
- **Web release builds keep tokens in memory**, so a reload signs out.
- **Expo Go cannot sign in or get push.** Its redirect URI and push token belong to Expo Go. Use a development build.
- **An expired session cannot always unregister push.** User-initiated sign out and account switch keep credentials and offer a retry if device unregistration fails. A session that has already expired may lose the credentials needed to remove its server-side token row.
- **Legacy task pushes carry no project id.** Current pushes carry `projectId`; older payloads still need up to 8 project lookups when tapped. Foreground report/snooze suppression needs an explicit project and a cached task-to-report association.
- **Local dev app is not first-party.** On a local stack the consent screen shows and access tokens last 1 hour.
- **No proactive refresh timer.** The app refreshes at launch when the token is nearly expired and on any 401, not on a schedule.
- **Project switcher lists environments as projects** when a project has more than one environment (team), because it lists teams.
- **Production OAuth apps may not allow the Errors and Sessions scopes yet.** `error_tracking:read`, `error_tracking:write`, `session_recording:read`, `replay_scanner:read` and `replay_scanner:write` need a human to add them to the US and EU mobile applications' ceiling in Django admin. Until then the server drops them and both screens show "isn't available yet".
- **Web links do not open the app.** `app.config.ts` declares no iOS associated domains and no Android intent filters, so an `https://` issue or recording link opens the browser. `webLinkTarget()` maps such links once a universal link reaches the app (from a custom-scheme link or a future associated domain). `webLinkTarget()` ignores the link's project id, so a link to another project opens in the current one and its request can fail.
- **Shared screen chrome lives in Views.** Errors and Sessions import `features/views/screen/*`, `ViewsToast` and `ViewsReauthState`. Move them to `src/ui/` (or one shared module) in a follow-up, so features import only other features' hooks again.
- **Only one list can be pinned.** Errors and Sessions share the one user slot in the nav pill (see [DECISIONS.md](DECISIONS.md#navigation-pins)).
- **Views' sign-in state hides Browse.** While Views lacks its own scopes, the Browse group is hidden, so Errors and Sessions are reachable only through a pin.
- **Production OAuth apps may not allow `today:read` yet.** The server drops scopes outside the app's ceiling without an error, so the report screen would always use signal evidence. Check the US and EU mobile apps in Django admin (see [AUTH.md](AUTH.md#server-side-ceiling)).

## Notification follow-ups

The app-side policy lives in `src/features/notifications/foregroundNotifications.ts` and
`notificationPresentation.ts`. It only controls notifications handled while the app is active.
The following need shared server policy or additional product work:

- **One outcome per requested operation.** Combine task-turn, terminal completion and PR-ready events.
  Prefer “PR ready to review” when a PR is the outcome; keep internal investigation, summarization and retries
  silent. A later user request or new decision can notify again. Keep shared activity-feed updates independent
  of mobile push suppression, and preserve desktop/web notification behavior.
- **Durable event identity and delivery.** Include operation, turn/decision/PR and recipient identifiers.
  Replace timer-only deduplication with durable per-recipient decisions and a transaction-safe delivery queue.
  Handle callback replay, rollback, queue failure and partial delivery without duplicated or missing alerts.
  Mobile cannot safely collapse different turn/question/PR events based only on their run or report.
- **Background snooze and presence.** Synchronize mute/snooze state and apply it to every mobile push producer.
  Local foreground filtering cannot stop lock-screen pushes while the app is backgrounded or closed.
  Validate the registration/device identity needed for presence beacons before adding them.
- **Stale outcomes and reminders.** Recheck cancelled/superseded work, resolved reports and recipient relevance
  before sending. Cancel snooze reminders when a report is resolved elsewhere. Avoid a confirmation push for
  the user's own cancellation.
- **Notification destinations and controls.** Carry the exact decision, run, message or PR to open; add
  category preferences and per-report mutes. Keep important new requests for input distinct.
- **Delivery diagnosis.** Carry a common notification event ID through send decisions and opens, track
  suppression reasons, and distinguish Expo acceptance from actual delivery. Add appropriate expiry/grouping
  metadata and reconcile stale device registrations.

## Hand-off and task runs

- **No following in the background.** The run streams only while its report is open and the app is in the foreground. A tool approval that arrives otherwise waits until a client connects.
- **Undo is best effort.** It aborts the answer in flight; a request the server already received still reaches the agent.
- **No resume of an ended run from the report screen.** A reply there to a run whose workflow ended asks the user to hand off again. The chat sheet starts a resume run (`resume_from_run_id`) instead; see CHAT.md.
- **No feedback on hand-off.** The web's Create PR takes optional feedback; the phone sends the prompt without it.
- **Inbox rows do not know about live questions.** The yellow "needs input" badge comes from the report data; the live pending request is only known while the report is open.
- **No server presence ping.** The app suppresses foreground notifications for the report on screen locally, but does not call `POST tasks/{id}/presence/`. The server still sends them and cannot use mobile presence to suppress other devices.
- **No repository choice.** Report tasks get their repository from the report or the server's cascade; `POST tasks/` answers 400 to a client-set `repository`. A wrong repository needs the web.
- **No branch list.** `integrations/`, `github_repos/` and `github_branches/` need `integration:read`, which the mobile OAuth app does not request, so the Branch page is a text field with no suggestions and the app cannot check that the branch exists before the run starts.
- **Picked options are lost when the task starts its own run.** When `POST tasks/` answers with a `latest_run`, the app skips `POST tasks/{id}/run/`, so the picked model, mode and branch never reach the server. `mobile_report_handed_off` still records them.
- **No mid-run model or mode change.** `POST tasks/{id}/runs/{run}/command/` with `set_config_option` (`model`, `effort`, `mode`) is not wired; options apply only when the run starts.
- **Plan mode default is ignored.** The web starts in Plan when `task_defaults.start_in_plan_mode` is set (behind a flag); the app always starts in Auto.
- **Live-only footer variants were not rendered.** The stopped-run card, the error line, the reply card and the URL-only PR line need a signed-in session; the web build cannot sign in, so only the demo states were checked in a browser.

## Delivery

- **Store and Expo accounts.** Builds, submissions, credentials, EAS environment variables and device registration need a person with access to the `posthog` Expo organization, App Store Connect and the Play Console. See [RELEASING.md](RELEASING.md#one-time-setup).
- **No EAS build has run yet.** The `.easignore` archive could not be inspected without an Expo login (`eas build:inspect` needs one).
- **Internal variants need portal setup before their first build.** The dev and preview bundle ids, widget ids, App Groups, push credentials and OAuth redirect URIs do not exist until someone registers them. See [RELEASING.md](RELEASING.md#one-time-setup).
- **Per-variant widget stores were not run on a device.** Both Swift readers derive the App Group from their bundle id. Only the generated entitlements and a Swift typecheck were checked.
- **Shared OTA publishing is pending.** A repository workflow is needed before OTA updates are part of the shared release process.
- **Chat composer under the keyboard (iOS).** On iPhone 17 with iOS 27, the composer's bottom row (Add a report, Send) sits about 30pt behind the keyboard, so Send cannot be tapped while typing. The return key still sends. See the `KeyboardAvoidingView` in `src/features/chat/ChatSheet.tsx`.
- **Sheets do not hide the screen under them from VoiceOver.** The report's controls stay in the accessibility tree under the hand-off, snooze and chat sheets.
- **Dev build overlays.** The Expo dev client's tools button covers the inbox More button, and its fast refresh banner covers Back and Close. Release builds do not have them. [TESTING.md](TESTING.md) says how to turn them off.
- **Android was not run.** Only the iOS simulator was checked.

## Agent state backend backlog

The frontend handles known PRs, execution uncertainty, focused foreground refresh, connection
failures and task-chat continuation. The following require backend work and are not implemented
by the mobile footer change:

- **Normalized CI snapshots.** Persist check summaries consistently for legacy and babysit
  execution paths and expose a consistent snapshot through the report PR API. The existing
  `pr_checks` endpoint already fetches selected-PR checks on demand; it does not provide the
  persisted head/freshness contract. Each PR needs its own head SHA,
  observed timestamp and check state. Missing, stale and pending results must remain distinct;
  a PR URL or successful tool step does not prove checks passed.
- **Execution versus monitoring.** Expose typed execution and monitoring state separately, with
  the current task/run identity, latest observation time, next scheduled check and stop capability.
  A claim, an idle turn or a completed run cannot establish whether PR monitoring continues.
- **Stream catchup boundary.** Emit a typed catchup-complete event with the current run identity
  and a snapshot/stream watermark after both durable and Redis history have drained. The
  frontend can batch durable replay and a quiet Redis tail, but without this boundary it cannot
  distinguish arbitrarily slow Redis history from new live events immediately.
- **Authoritative outstanding input.** Expose the current request snapshot, version and request
  id, plus resolution events with matching ids/version. Replayed log entries alone cannot prove
  a question still needs an answer, especially after another client answered.
- **External agent state.** Optionally accept MCP progress, structured outstanding input and
  heartbeat timestamps. Any input shown in the app needs a real answer channel and clear
  capabilities; identifying the MCP client or retaining its claim does not establish liveness.
- **Server permission policy.** Move automatic permission decisions out of viewer stream effects
  into the server's execution policy, preserving the existing decision rules. This is separate
  work so opening a report is not what enables unattended execution. The frontend policy has
  not been broadened here.

## Errors

- **No push for a new or spiking issue.** Error tracking alerts reach Slack and webhooks only. Backend ask: a mobile
  push destination for `ErrorTrackingAlert` (or a HogFunction that calls `send_user_push`) with the issue id, so a tap
  opens `/errors/{id}`. Today an issue reaches the phone through an Inbox report or a link.
- **Assign covers the viewer only.** Listing teammates and roles needs `organization_member:read` (and the roles list),
  which the app does not request. Another person's assignment shows as "A teammate" or "A role" without a name.
- **No Reopened badge.** No read the app can make says an issue came back after a resolve. Backend ask: a
  `reopened_at` (or last status change) on the issue resource.
- **No full stack, code context or source maps.** The trace card shows up to three in-app frames as text. Exception
  chains, code lines, variables and symbol-set problems stay on the web.
- **No search, severity, release or library filters**, no sort other than users, and no resolved or suppressed lists.
- **New and Spiking filter loaded pages.** Load more checks another 15 issues. An empty partial page is not a
  project-wide empty result. Mine filters on the server, and also loads 15 issues per page.
- **Sample sessions open at the start.** The session screen gets no `t`, because the exception's offset into the
  recording needs the recording's start time, which the issue reads do not return.
- **No merge, split, or external issue links** (Linear, GitHub, Jira).
- **Not checked against a live project.** The request and response shapes come from the serializers in this
  repository and the tests; the first real run needs an account whose sign-in includes `error_tracking:read` and
  `error_tracking:write`.

## Session replay

- **No player.** The phone shows the summary, chapter frames and the event timeline. Watching the recording is
  "Open full replay", the web player in the browser. No inspector, console or network panes.
- **No clip video.** Replay Vision renders an MP4 with idle time cut, but playing it needs `expo-video`, a native
  module the app does not ship. Adding it needs a new native build, not an over-the-air update.
- **No push when a summary is ready.** The screen polls for two minutes while it is open. Backend ask: a hook on scan
  completion that sends a mobile push with the session id, so a tap opens `/replay/{sessionId}`.
- **Frames need two requests.** The thumbnail endpoint answers with a redirect to a signed URL, so each frame costs an
  API call before the image loads, and the signed URL expires (the app keeps it for 4 minutes). The web build cannot
  read a manual redirect, so frames show the empty tile there.
- **Opening a session does not mark it viewed** on the web, because that needs `session_recording:write`.
- **No filters and a fixed window.** The list covers the last 7 days, 10 newest recordings per page, with up to 5
  optional recommendations below the recordings. No search, collections or playlists.
- **Clicks in the timeline are a sample.** At most 20 clicks of a session show, spread over its length. The page view
  and click query reads the first 300 events, so a long session loses its later pages and clicks; the count then
  reads "301+ events". Errors and rage clicks have their own query and always show (up to 100).
- **Rows from the feed may lack a length.** A feed pick outside the loaded recording pages has no duration or click
  count, because the feed carries the observation, not the recording.
- **The full report's "Watch session" opens at the start.** A signal carries the session id but no offset into it.
- **Not checked against a live project.** The shapes come from the serializers in this repository and the tests; the
  first real run needs a sign-in with `session_recording:read`, `replay_scanner:read` and `replay_scanner:write`.
