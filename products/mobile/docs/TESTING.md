# Testing

## Checks

```sh
cd products/mobile
pnpm typecheck
pnpm lint
pnpm test
```

CI runs the same three checks, see [CI.md](CI.md).

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
Every step uses the app's `testID`s, except the scrim tap, which uses the scrim's "Close" label.

### Set up once

1. Install Argent: `npm install -g @swmansion/argent`.
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

A pass takes about 30 seconds, prints one line per step, and exits with code 0.
If more than one simulator is booted, add `--device <udid>` (see `xcrun simctl list devices booted`).

Two `idle` steps can warn that a small part of the screen was still changing, such as the text caret.
The step after each one waits for a stable element, so these warnings are expected.

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
