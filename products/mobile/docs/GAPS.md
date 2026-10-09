# Gaps

Known gaps and behavior that stays on the device.

## Product

- **Dark mode.** Light theme only (`userInterfaceStyle: 'light'`). Tokens are not split by scheme yet.
- **Dismiss and resolve.** The app cannot dismiss or resolve a report. Done reports come from the server.
- **Approve PR.** The PR card only opens the PR. Approving happens on GitHub.
- **Own-agent hand-off.** Only the PostHog agent. No Codex, Claude Code or Cursor rows.
- **Time-based snooze is local.** "In an hour", "Tomorrow", "Next week", "In a month" and
  "Custom…" hide the report on this device only. Other devices and the web app still show it.
  "Until more signals arrive" is the only server-side snooze.
- **Hidden navigation.** Spaces, Views, Teams, Notifications and Give feedback are not in v1.
  The project switcher chevron does nothing yet.
- **Agent progress UI.** The prototype's "Step N of M" segments are not shown; the run API has a
  free-text stage only.
- **Read state** is recorded but not styled.
- **Impact avatars.** The prototype data has avatar stacks on Impact facts that its template never
  draws; the app does not draw them either.
- **Chat** has no attachments or expanded composer; Attach and Expand are dimmed.

## Platform

- **Android text wrapping** is greedy, so a headline can end on a single word. iOS and web avoid it.
- **Final assets.** Icon, adaptive icon, splash and favicon are generated placeholders.
- **Hover states** only show on web.

## Verification limits

- No live PostHog was reachable while building. Every live path is covered by unit tests on
  fixtures shaped from the serializers and by browser runs against intercepted responses.
  The first real sign-in, hand-off, stream and chat need a device and an account.
- The web render check cannot show the iOS keyboard that some reference screenshots include.

## Chat

- **No AI consent notice.** The web client checks `organization.is_ai_data_processing_approved`
  before chat; the server does not. The auth store does not keep that flag from `/api/users/@me/`,
  so the app shows no notice. Add the flag to the auth store, then a one-line notice in the sheet.
- **Instructions name tools the agent lacks.** `REPORT_DISCUSSION_STATE_INSTRUCTIONS` and
  `NO_CHECKOUT_INSTRUCTIONS` refer to inbox MCP tools and a sandbox checkout. The LangGraph agent has
  neither unless the team installed the PostHog MCP server from the MCP store. They stay verbatim for
  parity with the web until chat moves to the sandbox runtime.
- **No server cancel.** Stop only stops reading; the run finishes on the server.
- **No history.** Closing the sheet drops the conversation. There is no list of past chats.
- **Approvals, forms, charts and notebooks** show as a link to the web app.
- **Reconnect in the first seconds.** `GET conversations/:id/` returns 404 until the server titles the
  conversation, so a reply that finished while the app was offline in that window cannot be loaded.
- **Markdown now renders** in replies; the Product line above about plain text predates it.
  Attach and Expand stay disabled.

## Inbox and report data

- **`today:read` scope.** The briefing and the Today page need `today:read`. Without it in the OAuth request, both return 403 and the app always uses the reports list and signal evidence.
- **Time snoozes do not sync** to other devices or the web, and are lost when the app's storage is cleared.
- **Web-made signal snoozes** are not labeled in the Today list, because briefing items carry no report status.
- **Briefing rows** carry no agent badge and no progress label.
- **Evidence** maps error, feedback and recording signals only. Scout findings, GitHub and analytics signals add no evidence block.
- **Work log** shows one page of 100 artefacts. Older entries of a very long log are not shown.
- **PR details.** The PR view has the URL, number, state and review decision. Title, diff size, checks and the agent's note need `pr_checks/` or the run output, which the hand-off feature may add.
- **Read state** of the list is refetched with the list. A report read on another device shows as unread until then.

## Auth and push

- **No OAuth sign in on the web.** The web build offers the demo, and a personal API key in dev builds.
- **Web release builds keep tokens in memory**, so a reload signs out.
- **Expo Go cannot sign in or get push.** Its redirect URI and push token belong to Expo Go. Use a development build.
- **Offline sign out leaves the push token registered.** If unregistering fails, the server keeps sending that user's pushes to the device. The app cannot retry later because it no longer has a token for that user.
- **Task pushes carry no project id.** Routing searches at most 8 projects and falls back to the inbox. A `project_id` in the task push payload would remove the search.
- **Local dev app is not first-party.** On a local stack the consent screen shows and access tokens last 1 hour.
- **No proactive refresh timer.** The app refreshes at launch when the token is nearly expired and on any 401, not on a schedule.
- **Project switcher lists environments as projects** when a project has more than one environment (team), because it lists teams.
- **Production OAuth apps may not allow `today:read` yet.** The server drops scopes outside the app's ceiling without an error, so the inbox would always use the signals fallback. Check the US and EU mobile apps in Django admin (see [AUTH.md](AUTH.md#server-side-ceiling)).

## Hand-off and task runs

- **No following in the background.** The run streams only while its report is open and the app is in the foreground. A tool approval that arrives otherwise waits until a client connects.
- **Undo is best effort.** It aborts the answer in flight; a request the server already received still reaches the agent.
- **No resume of an ended run.** A reply to a run whose workflow ended asks the user to hand off again instead of starting a resume run (`resume_from_run_id`).
- **No feedback on hand-off.** The web's Create PR takes optional feedback; the phone sends the prompt without it.
- **Inbox rows do not know about live questions.** The yellow "needs input" badge comes from the report data; the live pending request is only known while the report is open.
- **No presence ping.** The app does not call `POST tasks/{id}/presence/`, so task pushes still arrive while the user watches the run.
- **Model is fixed.** Hand-offs always send `claude` / `claude-opus-5-5` / `high`, which overrides a user's or project's default model (the web sends these only when no default exists).
- **Live-only footer variants were not rendered.** The stopped-run card, the error line, the reply card and the URL-only PR line need a signed-in session; the web build cannot sign in, so only the demo states were checked in a browser.

## Delivery

- **Store and Expo accounts.** Builds, submissions, credentials, EAS environment variables and device registration need a person with access to the `posthog` Expo organization, App Store Connect and the Play Console. See [RELEASING.md](RELEASING.md#one-time-setup).
- **Version 1.0.0 may be taken.** The old app shipped `1.0.0`. If App Store Connect has released it, raise `version` before the first production build.
- **No EAS build has run yet.** The `.easignore` archive could not be inspected without an Expo login (`eas build:inspect` needs one).
- **Settings does not show the update id.** It shows the version and channel only, so you cannot tell which over-the-air update a device runs. `Updates.updateId` and `Updates.createdAt` from `expo-updates` would answer it.
- **OTA publishing is manual.** No workflow runs `eas update`.
- **Chat composer under the keyboard (iOS).** On iPhone 17 with iOS 27, the composer's bottom row (Add a report, Send) sits about 30pt behind the keyboard, so Send cannot be tapped while typing. The return key still sends. See the `KeyboardAvoidingView` in `src/features/chat/ChatSheet.tsx`.
- **Sheets do not hide the screen under them from VoiceOver.** The report's controls stay in the accessibility tree under the hand-off, snooze and chat sheets.
- **Dev build overlays.** The Expo dev client's tools button covers the inbox More button, and its fast refresh banner covers Back and Close. Release builds do not have them. [TESTING.md](TESTING.md) says how to turn them off.
- **Android was not run.** Only the iOS simulator was checked.
