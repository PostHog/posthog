# Testing

## Checks

```sh
cd products/mobile
pnpm check:expo
pnpm typecheck
pnpm lint
pnpm test
```

`pnpm check:expo` compares dependencies with the installed Expo SDK's bundled compatibility metadata, rather than newer remote patch metadata.
`pnpm typecheck` includes this compatibility check automatically.
CI runs typecheck, lint, and tests; see [CI.md](CI.md).

## Authenticated local checks

Run the setup in [README.md](../README.md#sign-in-to-the-local-backend) first.
Until the backend changes merge, the commands below run from the paired `codex/mobile-dev-environment` checkout; the mobile development build runs from `codex/mobile-app`.
The backend needs migrated Postgres, object storage, and the normal local services.
Use the same development environment and `SITE_URL` as the running backend.

```sh
python manage.py setup_local_dev --json
python manage.py check_local_dev --json
```

The first command creates the usual test account only when absent, keeps an existing account and project, registers local OAuth callbacks, and inserts repeatable personal Inbox and Chat examples.
It does not reset the database or start a real agent.
Keep the returned project and object IDs for your native checks.
An existing account with a custom password is preserved and needs its existing sign-in details.
For another existing account, seed with `python manage.py seed_local_inbox_data --team-id <project-id> --user-id <user-id> --json`.

The second command checks the default test account over HTTP: password login, normal CSRF-protected consent, PKCE code exchange for the registered `posthog-dev://callback`, bearer-authenticated account/project/Inbox/Chat reads, refresh, and revocation.
Use `--callback posthog://callback` or `--callback posthog-preview://callback` to check another registered mobile scheme.
It prints a safe summary and revokes the temporary OAuth session.
It does not exercise the native browser sheet, device callback delivery, app storage, or screen rendering.

On an iOS simulator or Android emulator with a development build:

1. Leave demo mode and sign out. Choose **Self-hosted** with the local backend URL and prefilled local Client ID.
2. Sign in as `test@posthog.com` with `12345678`, approve access, and verify the browser returns to the app through its variant's callback scheme.
3. Confirm the account and project match the setup output. Open the ready and pending-input Inbox reports, their details, and the completed Chat. The stored user and assistant messages should load without starting a task run.
4. Open Views, Errors, and Replay. Confirm saved views and errors load for the same project. A playable replay needs the real recording step below.
5. Switch to another project available to the account, then back. Each Inbox, Chat, and saved view list must belong to the selected project. If the account only has one project, create another in the local web app before this check.
6. Background and reopen the app. Verify the account and project remain selected. Sign out and verify returning to the app requires sign-in again.

Use the backend HTTP check to exercise refresh and revocation without waiting for a native access token to expire.
Only record a native sign-in pass after running the device steps.

### Capture real local session recordings

Replay needs actual browser snapshots as well as analytics events.
Install the Hedgebox dummy package dependencies first, then run `pnpm exec playwright install chromium` from `tools/hedgebox-dummy` if the browser is missing.
In the paired backend checkout, run the Hedgebox dummy with the project token shown in that selected project's settings:

```sh
cd tools/hedgebox-dummy
NEXT_PUBLIC_POSTHOG_KEY=<selected-project-token> \
NEXT_PUBLIC_POSTHOG_HOST=http://localhost:8010 \
pnpm exec next dev --port 3000
```

In another terminal at that backend checkout's root, run:

```sh
NEXT_PUBLIC_POSTHOG_KEY=<selected-project-token> \
NEXT_PUBLIC_POSTHOG_HOST=http://localhost:8010 \
node products/demo/scripts/capture_sessions.cjs --app-url http://localhost:3000 --sessions 3
```

The collector checks the SDK uses the selected token and local host, interacts with the dummy, and waits for real snapshot requests to be accepted.
Its `snapshots_accepted_pending_ingestion` result means capture succeeded; it does not prove replay is playable yet.
Keep ingestion, ClickHouse, and replay storage running, wait for the returned session IDs to appear in the local web app, then play one there and in the mobile Replay screen.
If a session is missing, inspect local capture, ingestion, and replay storage logs before recording a playback pass.
The dummy's normal development shortcut can choose the latest project; the explicit command above keeps the SDK on the account's selected project.

## Chat navigation and header

On iOS and Android, open an existing chat and start a new chat. Both must fill the screen without a
sheet grabber or drag-down dismissal. Header Back and platform Back return to the previous page;
a direct link falls back to the configured default page. Scroll a long thread under the title-free
blurred header and focus the composer to check the keyboard and safe-area spacing.

New chat and the ellipsis share the Inbox's pill control. Open the menu, copy the link, and confirm
it targets the current project and chat. Archive a saved chat and confirm it disappears from Chats
only after success. Fail each action and retry; repeated taps must not start duplicate requests.
An unsaved chat has no link or task to archive, so its ellipsis is disabled.

## Chat drafts and rich replies

Use a native development build that includes `react-native-webview`.

1. Type a draft in an existing chat, a new chat and a report discussion. Close and reopen each,
   then restart the app. Each composer should restore its own text and report attachments.
2. Send a draft successfully, then reopen the chat. The sent text should be gone. Fail a send
   and verify the draft returns; switching chats before that request ends must not copy it
   into another chat. Sign out and verify drafts are gone after signing back in.
3. Render an inline insight tag, a block insight tag and a block SQL tag. Verify links open the
   current host and project, and Show all expands SQL without opening the browser. Test a
   missing insight and an account without `insight:read` too.
4. Render a complete Mermaid flowchart and a wide diagram. Verify the diagram height and
   horizontal scrolling. Incomplete fences, invalid diagrams and remote-image nodes should
   stay as code. The web preview intentionally shows Mermaid source.
5. Delay or fail read-state lookups. Rows must not show unread dots from missing or stale
   responses. Read a report elsewhere and wait for the foreground inbox refresh. Opening a
   report that fails to load must not mark it read.

## Report refresh checks

Open a report, scroll down, background the app, then return. The report and scroll position must stay
visible while a small spinner beside Previous/Next shows the refresh, then fades away without moving
the navigation controls. Repeat with an unavailable Today page or signals endpoint, and with a failed
background request. A first load without cached data still shows the full loading state.

## Notification checks

Run `pnpm test --watchman=false --runInBand src/features/notifications` for foreground delivery sequences
and cold-start tap routing. The tests exercise the installed notification handler as well as the policy:
viewed reports, cached task associations, active/expired snoozes, repeated terminal events, distinct questions,
project/account boundaries and a tap received before sign-in.

On a development build with notifications enabled:

1. Keep a report open and deliver a push for that report (then one for its cached task). Neither should show
   a foreground banner or notification-list entry. Deliver a push for a different report: it should appear.
2. Leave the report and deliver two completion pushes with different OS identifiers but the same project,
   task, run and `notificationKind: completed`. Only the first should appear. A new run should still appear.
3. Time-snooze a report and deliver a report push while elsewhere in the foreground. It should stay quiet.
   After expiry, the snooze reminder should appear. Repeat using a task already associated in the cache.
4. Deliver two distinct `awaiting` notifications for one run: neither should be lost to a run-wide cooldown.
5. Tap a notification while signed out, sign in, and verify that its report opens once.
   For chats, open a conversation, enter a draft, background the app and tap a push for that chat.
   Verify the draft and scroll position stay intact. Repeat with a chat just started in the composer.
   Tap a push for a different chat and verify its history loads; one Close must return to the screen
   underneath. Also tap New chat, then tap a push for the conversation you just left; it must reopen.
6. Repeat a delivery with the app backgrounded or terminated. App-side filtering does **not** provide the same
   guarantees there; server consolidation and synchronized snoozes remain follow-ups in [GAPS.md](GAPS.md).

## Demo walkthrough on the iOS simulator

`.argent/flows/demo-smoke.yaml` drives the demo end to end with [Argent](https://docs.expo.dev/agents/argent/), a device automation CLI from Software Mansion.
The flow needs no account, because every build shows **Try the demo** on the sign-in screen.
The flow:

1. taps **Try the demo** on the sign-in screen,
2. opens "Report load time", opens and closes the hand-off sheet,
3. resolves the report as fixed outside PostHog and checks that its inbox row is gone,
4. opens "3,721 errors", taps **Needs your answer**, picks an answer in the decision sheet, then taps Undo, reopens the question and closes its sheet,
5. opens Chat from the action pill, sends a question and waits for the demo reply,
6. goes back, opens Chats, opens the session "Fix the flaky checkout test", and checks its title and reply,
7. opens "Add dark mode to settings" and waits for its decision card,
8. goes Home and taps **Exit demo** in Settings.

It starts and ends on the sign-in screen with demo mode off, so you can run it again right away.
Actions use the app's `testID`s, except the hand-off sheet drag, which starts on its "Choose an agent" header.

### Set up once

1. Install the pinned Argent version: `npm install -g @swmansion/argent@0.30.1`.
2. Install ffmpeg if you want screen recordings: `brew install ffmpeg`.
3. Install Xcode with an iOS simulator runtime, and CocoaPods.

### Run the flow

```sh
cd products/mobile
pnpm ios --port 8181        # builds the dev client, boots a simulator, starts Metro
```

Prepare the development build:

1. On a fresh install, the dev client shows its developer menu once. Tap **Continue** and close it.
2. Open the developer menu (Device, Shake in the Simulator menu, or ⌃⌘Z) and turn off:
   - **Tools button**. The floating gear covers the inbox More button.
   - **Fast refresh**. When files change, its "Refreshing..." banner covers the Back and Close buttons.
3. Demo mode must be off. If the app opens on the inbox, open Settings and tap **Exit demo**.

Then run the flow from `products/mobile`, because Argent looks for `.argent/flows` in the current directory:

```sh
argent flow run demo-smoke --platform ios
```

A pass prints one line per step and exits with code 0. Locally, `demo-smoke` took about 49 seconds and
`views-smoke` about 80 seconds on Xcode 27.1 / iOS 27.0. A fresh native compile took about 8 minutes,
with simulator setup adding more time.
If more than one simulator is booted, add `--device <udid>` (see `xcrun simctl list devices booted`).

Two `idle` steps can warn that a small part of the screen was still changing, such as the text caret.
The step after each one waits for a stable element, so these warnings are expected.

### Demo flows before you merge

CI does not run the simulator flows. Run `demo-smoke` and `views-smoke` locally before you merge a change to a screen,
navigation, the demo fixtures, or a flow. The `/running-mobile-demo-flows` skill in `.agents/skills/` walks an agent
through the same steps and the result files.

The scripts below build a bundled Release app with no Metro connection. Argent reads the native view hierarchy,
so the flows do not need a development build or its overlays.

The build disables analytics and over-the-air updates. The script creates a temporary iPhone 17 Pro simulator,
installs the app again before each flow, and deletes the simulator on success, failure, or interruption.
Only demo fixtures are used; no PostHog account, API key, Expo token, or Apple signing credentials are needed.
Both flows run even when the first fails. JSON reports, failed-step screenshots, and build logs land in the
artifact directory you pass.

Install the app dependencies, CocoaPods, and Xcode 26.6 with the iOS 26.5 runtime,
then run from `products/mobile`. A dedicated Argent install keeps the runner separate from an editor's server:

```sh
DO_NOT_TRACK=1 npm install --prefix /tmp/mobile-argent-tools --no-audit --no-fund @swmansion/argent@0.30.1
export PATH="/tmp/mobile-argent-tools/node_modules/.bin:$PATH"
bash scripts/ci-argent-build.sh /tmp/mobile-argent-build /tmp/mobile-argent-artifacts
bash scripts/ci-argent.sh \
    /tmp/mobile-argent-build/Build/Products/Release-iphonesimulator/PostHog.app \
    /tmp/mobile-argent-artifacts
```

The build regenerates the ignored `ios/` project, so run it in a disposable checkout if you have manual native edits.
To select another installed simulator runtime, set
`ARGENT_IOS_RUNTIME` to its identifier from `xcrun simctl list runtimes`, for example
`com.apple.CoreSimulator.SimRuntime.iOS-27-0`. Simulator-only builds do not sign or publish anything.
Argent's [e2e reference](https://docs.swmansion.com/argent/docs/reference/e2e-yaml/) documents the native
selectors and the `--output` reports. The older `argent flow` command remains an alias for `argent e2e`.

### Record a video

```sh
argent run screen-recording-start --udid <udid> --timeLimitSeconds 120
argent flow run demo-smoke --platform ios --device <udid>
argent run screen-recording-stop --udid <udid>
```

`screen-recording-stop` prints the path of the mp4.
Argent writes it under `.argent/recordings/` in the directory where its tool server started, which can be the repo root. Move the file out before you commit.

For a still image, run `xcrun simctl io booted screenshot <file>.png`.

### Use Argent from an agent session

Run `argent init` once from the repo root. It registers Argent's MCP server and skills for coding agents.
Do not run `argent init --local`: it edits `package.json`.

An agent can then:

- replay the flow with the `flow-execute` tool (`name: demo-smoke`, `project_root`: the absolute path of `products/mobile`),
- find elements with `describe` or `debugger-component-tree`, and tap them with `gesture-tap`,
- read console output with `debugger-log-registry`.

Without the MCP server, the same tools work from a shell: `argent tools`, `argent tools describe <tool>` and `argent run <tool> --args '{...}'`.

To change the flow, record the new steps live with `flow-start-recording`, `flow-add-step` and `flow-finish-recording`, then edit the YAML.
Argent's `argent-create-flow` skill describes the rules. Replay the whole flow before you commit it.

### Troubleshooting

- **"There was a problem loading the project" with an address like `http://10.x.x.x:8181`.**
  The dev client tried the Mac's network address. Open the local address instead:

  ```sh
  xcrun simctl openurl booted "exp+posthog://expo-development-client/?url=http%3A%2F%2Flocalhost%3A8181"
  ```

- **The app closes at launch, and the log says "UIScene life cycle is required".**
  The `ios/` folder was generated before `plugins/withIosSceneLifecycle.js` existed. Run `npx expo prebuild --platform ios --clean`, then `pnpm ios` again.
- **A `visible` check passes while a sheet covers the screen.**
  The screen under a sheet stays in the accessibility tree. Check that the sheet is `hidden` first, as the flow does.
- **iOS asks "Open in PostHog?"** after `xcrun simctl openurl`. Tap Open. The question does not come every time.
