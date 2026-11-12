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

For inbox pagination, check that an invalid next-page response keeps the loaded reports visible and shows the retry footer.
Retry after the server returns a valid page and confirm that the remaining reports load.

## Sign-in region menu

On both an iOS simulator and an Android emulator:

1. Open the data region menu and select European Union. The menu must close and the field must show European Union.
2. Reopen the menu and switch back to United States. Repeat to check that the menu remains usable.
3. Tap outside the menu. It must close without changing the region. On Android, Back must do the same.
4. After dismissal, open the self-hosted form and return to PostHog Cloud. The selected cloud region must remain unchanged.
5. Tap Try the demo and check that the app opens its configured default page.

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

## Duo and resizable windows

Use Xcode 27.1 or newer with an iPhone Duo runtime. Capture matching native before-and-after screens on iOS and Android; simulators and emulators qualify, as described in `../AGENTS.md`.

1. Open a report unfolded, scroll it, open Resolve and enter a note. Fold, unfold, rotate and
   enter Split View on either side. Include a half-open pose with an active fold. Verify the report, scroll position and note remain, and sheets stay within one safe pane. In a short horizontal pane, open Model, scroll to its last option, and use Reset. When a fold leaves panes too small for an inbox/report pair, verify that the single report stays on one side.
2. Change filters in the expanded inbox pane and select another report. Verify its highlight,
   data and actions. A confirmation sheet must block the inbox and navigation behind its scrim.
3. Tap Home from a report and switch Chats and Views through horizontal navigation and the rail.
   Check pinned Errors and Sessions slots, larger text and shorter windows too. On Duo with a vertical system rail, verify the original icons and Chat action occupy native tabs and toolbars, without tab labels or a second app rail. On a regular iPhone and on Android, verify the original floating pill and Chat button. Opening a sheet must block the header and navigation behind its scrim. Rotate back to horizontal bars from a report, Chat, and each tab; verify that no native header remains above the custom controls. Pin and unpin Errors or Sessions from Views and use Undo after the tab host remounts.
4. Enter a chat draft, queue a message and open Model. Resize with a streaming reply and the
   keyboard visible. Keep the conversation, draft and queue without a duplicate send or stream.
5. Scroll Views to a later chart pin, expand and collapse the window, and verify the same pin
   stays near the top. Check menus, chart and number pins, and full-screen insights.
6. Check empty and error states, long titles, and asymmetric safe areas on both sides. No
   control should overlap system UI, clip, or require a particular fold pose.

### Repeatable screenshot comparisons

Use `.argent/flows/screenshot-capture.yaml` to capture Inbox, Report, Handoff, Chat with the keyboard,
and Views from repository demo data. It launches the production app identity on either platform:
`com.posthog.code.mobile` on iOS and `com.posthog.mobile` on Android. It leaves Views open.
`.argent/flows/screenshot-landscape.yaml` continues from there on iOS and captures the same surfaces after rotation.
These flows collect review images; they do not perform pixel-diff assertions or replace the smoke flows.

Keep the base captures, then repeat on the same virtual devices after each layout revision.
Record the source commit, model, OS, pixel dimensions, orientation, posture, theme, and text size beside each set.
Use separate artifact directories such as `before/iphone-portrait` and `after/duo-inner-landscape`.
Do not compare portrait-locked base screens with landscape screenshots as though the orientations match.

| Virtual device                                           | Capture matrix                                | Reference native pixels                        |
| -------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------- |
| Ordinary iPhone, initially iPhone 17 Pro / iOS 27.0      | Portrait and landscape                        | 1206×2622 and 2622×1206                        |
| Android, initially Pixel 9 / Android 16 API 36 at 420dpi | Portrait and landscape                        | 1080×2424 and 2424×1080                        |
| iPhone Duo / iOS 27.1                                    | Closed cover, inner portrait, inner landscape | Cover 1398×2034; inner 2007×2853 and 2853×2007 |

#### Build and prepare

Use bundled Release builds with analytics and OTA updates disabled, so screenshots show the selected checkout.
For iOS, use `scripts/ci-argent-build.sh` below. For Android, generate the native project in a disposable checkout
with `CI=1 EXPO_NO_DOTENV=1 APP_VARIANT=production pnpm exec expo prebuild --platform android --no-install`.
Set `expo.modules.updates.ENABLED` to `false` in the generated `android/app/src/main/AndroidManifest.xml` before building.
With JDK 17, Android SDK/build tools 36 and the generated project's NDK installed, run:

```sh
cd android
CI=1 EXPO_NO_DOTENV=1 EXPO_NO_TELEMETRY=1 DO_NOT_TRACK=1 APP_VARIANT=production \
EXPO_PUBLIC_POSTHOG_KEY='' EXPO_PUBLIC_POSTHOG_HOST='' \
./gradlew assembleRelease -PreactNativeArchitectures=arm64-v8a --max-workers=2 --console=plain
```

The APK is `android/app/build/outputs/apk/release/app-release.apk`. Use the emulator's architecture if it differs.
Reinstall the selected build on a dedicated test device before each run to reset demo state; the flow expects **Try the demo**.
Select explicit device IDs from `xcrun simctl list devices` or `adb devices`. Never reset a person's device or account for these captures.
Use light appearance and the default text size for matching pairs; record accessibility variants separately.

#### Capture and keep the PNGs

From `products/mobile`, with the pinned private Argent install on PATH:

```sh
capture_device='<explicit simulator UDID>'
capture_dir='/tmp/mobile-screenshots/after/iphone-portrait'
mkdir -p "$capture_dir"
argent run rotate --udid "$capture_device" --orientation Portrait
argent e2e run screenshot-capture --platform ios --device "$capture_device" \
    --output "$capture_dir" --json > "$capture_dir/report.json"
```

For Android, use its serial and `--platform android`. For Duo, select the posture before the portrait run:
`argent run fold --udid "$capture_device" --posture closed` for the cover, or `--posture open` for the inner screen.
An open posture initially turns the UI landscape, so rotate to Portrait again before `screenshot-capture`.
For iOS landscape, run `screenshot-landscape` immediately after a successful portrait run, with a separate output directory.
Its explicit `rotation: LandscapeLeft` makes the exported iOS framebuffer upright.

Successful tool screenshots live in temporary Argent storage, even when `--output` is supplied.
Copy them out before stopping the server. This exports stable names from either flow's JSON report:

```sh
python3 - "$capture_dir/report.json" "$capture_dir" <<'PY'
import json
import shutil
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
if not report['ok']:
    raise SystemExit('Capture failed; inspect the report before using its screenshots.')
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
for step in report['steps']:
    if step['kind'] == 'echo':
        name = step['message'].lower()
    if step.get('tool') == 'screenshot':
        shutil.copyfile(step['result']['image']['hostPath'], output / f'{name}.png')
PY
```

Inspect every PNG, including the fully settled keyboard. Use an invented unsent draft if keyboard suggestions expose clipboard contents.
Preserve raw images and label matching pairs **before** and **after**. The PR composites resize each portrait capture to 600px wide,
place the pair on a neutral canvas with padding, and label the model and surface. Compare the native PNGs when checking small details.
For a bezel view, capture the actual Device Hub window and crop surrounding controls while retaining about 60px of padding.
Keep that framed presentation separate from the raw app screenshots.
Upload reviewed images using `hogli pr:upload-image --print-markdown <files...>`; acknowledge its public-upload warning with `--yes`.
Insert the resulting pinned image URLs into the existing PR description without removing earlier evidence.

#### Capture tooling workarounds

- Keep Argent 0.30.1 in a private install and expose the Android SDK and `adb` on PATH before starting its server.
  If an emulator is visible to `adb` but absent from Argent, launch that dedicated AVD with `-grpc-use-token`.
  Keep connection tokens out of screenshots, logs attached to the PR, and source control.
- A native-devtools launch failure can need one restart of that private server. Retry the capture, then use direct device inspection
  if it still cannot connect. Do not restart another task's server or report a skipped capture as a pass.
  `argent run describe --udid "$capture_device"` can still read the iOS accessibility tree when selector flows cannot run.
  Navigate with its current element coordinates and `gesture-tap`, then capture each state with `argent run screenshot`.
- On Android, dismiss Gboard's first-run handwriting prompt. For a dedicated emulator, disable stylus handwriting with
  `adb -s "$capture_device" shell settings put secure stylus_handwriting_enabled 0` and enable its software keyboard with
  `adb -s "$capture_device" shell settings put secure show_ime_with_hard_keyboard 1`.
- Android selector taps after rotation mis-targeted controls in the reference run. Inspect the current screenshot or element tree,
  then use `adb -s "$capture_device" shell input tap <x-pixels> <y-pixels>` and `adb ... exec-out screencap -p` if needed.
  Recalculate coordinates for each device and posture. Do not reuse the old screen's coordinates.
- If the dedicated emulator stops answering shell requests, restart that AVD rather than restarting the shared `adb` server.
- Capture landscape chat with the keyboard open on both platforms. The input, model and mode controls, and Send must remain visible.
  Gboard must keep the app composer visible rather than opening its full-screen editor.
  Scroll the empty-state suggestions, send a demo reply, and rotate with an unsent draft to check that the draft survives.

For a complete layout review, also capture sign-in, Settings and its project picker, inbox filters and row actions,
full report details, handoff options, verdict and decision sheets, saved chats, Views browse and detail screens,
full-screen charts, and the Errors and Sessions lists and details.
When demo mode cannot supply a detail screen, use invented diagnostic fixtures and label those captures separately;
record the provider substitutions and do not claim live data or replay playback coverage.
Capture every distinct screen on the open Duo, then repeat affected screens in portrait and on the closed cover.
Keep matching ordinary-phone screenshots for each changed screen. Record unreachable states as missing coverage.
After returning from chat, rotate a report and check that its footer stays attached to the content with one compose action.

## Chat navigation and header

In a new chat, fail a send with a multi-line error while the keyboard is open. Check that the full notice and Dismiss button stay above the composer without overlapping suggestions.
Tap empty space to dismiss the keyboard, refocus the draft, then drag down in the suggestions area to dismiss it again.
Repeat with larger system text. Suggestions must scroll when they do not fit, and dismissing the notice must preserve the draft.
For an unsaved draft, check that Retry save remains visible and disabled while saving. For a lost connection, check Reconnect and Dismiss.

On iOS and Android, open an existing chat and start a new chat. Both must fill the screen without a
sheet grabber or drag-down dismissal. Header Back and platform Back return to the previous page;
a direct link falls back to the configured default page. Scroll a long thread under the title-free
blurred header and focus the composer to check the keyboard and safe-area spacing.

Saved chats show New chat and the ellipsis in a bordered pill beside the labeled Back chip. Open the menu, copy the link, and confirm
it targets the current project and chat. Archive a saved chat and confirm it disappears from Chats
only after success. Fail each action and retry; repeated taps must not start duplicate requests.
An unsaved chat shows only Back, aligned with Settings, until the first message creates a task.
Open New chat several times and check that the page finishes sliding in before the keyboard rises from the bottom.
Repeat with the AI access check delayed so the composer mounts after the transition, and check the compact landscape layout.

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

## Resolve and dismiss sheets

On Android and iOS, open Resolve and Dismiss for a report with a long title.
Repeat in portrait and landscape, including a larger text size.
Include an Android 17 emulator with a Pixel 9 display profile (1080 × 2424 at 420 dpi).
Scroll through every reason and the optional note. The list must use the available space without clipped rows.
Select a reason, focus the note, type, and hide the keyboard. The confirm button must stay visible above the keyboard and return to the bottom after it closes.
Repeat after you open and close the chat keyboard. The sheet must not reserve space for a keyboard that is hidden.
Confirm the verdict and check that the report leaves the inbox. Close and reopen a sheet to check that its reason and note reset.

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

### Android notification taps after process death

Use a rebuilt Android development client. Keep the app's task in Recents when killing its
process; force-stop and removing the task test different startup paths.
Send test pushes as described in [Push notifications](PUSH.md#testing) and tap them in the
system tray. Use different reports in a project the test account can access. To kill the process
without removing the task, substitute the installed variant's package in these commands.

```sh
adb shell input keyevent KEYCODE_HOME
adb shell am kill com.posthog.mobile
adb shell pidof com.posthog.mobile # must print nothing
```

Disconnect the debugger if it keeps the development build alive.

Verify these sequences against both base and proposed builds:

1. Open report A, background the app, and tap a notification for report B with the process alive.
2. Repeat after killing the background process while retaining its task. B must open once.
3. Start a fresh task by tapping a notification for A, navigate to another report, background
   and kill the process, then tap a notification for B. B must open without reopening A.
4. Repeat the notification-launched task sequence but reopen from Recents with no new tap.
   The original notification must not replay.
5. Tap a notification to start a fresh task, then kill its process before JavaScript routes it.
   Reopen from Recents without another tap. The pending target must open once.
   Repeat while signed out, kill and reopen, then sign in. The pending target must still open.
6. Background the app and tap a local snooze reminder, then open a report deep link.
   Both must still reach their targets.
7. While routing is waiting for sign-in, tap a push for A and then a snooze reminder for B.
   Sign in and verify only B opens. Repeat with the tap order reversed and verify only A opens.

Also perform real push delivery checks on physical Android and iOS devices before marking the PR ready.

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
    /tmp/mobile-argent-build/Build/Products/Release-iphonesimulator/PostHogApp.app \
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

## Native replay prototype

Recording is off unless `EXPO_PUBLIC_POSTHOG_REPLAY=1` and an analytics project key are set.
It runs only in internal iOS/Android builds, after demo hydration, while signed out in demo mode.
Leaving demo mode or signing in stops recording, including pending starts. Live and sign-in UI
also has a root `ph-no-capture` mask. Store builds and Expo web cannot start this recorder.

The `@posthog/react-native-plugin` dependency autolinks as a native module. It is not an Expo
config plugin; do not add it to `app.config.ts`'s `plugins` array. Run `pnpm ios` or `pnpm android`
to rebuild with it. An OTA update cannot add native modules. Expo Go cannot record.
Enable **Record user sessions** in the project receiving the app's own usage analytics.
Use a dedicated test project and fixture data for validation.

The SDK configuration masks text, inputs, images and sandboxed iOS views, disables touch
coordinates, and disables recording logs and network telemetry. Native push autocapture and
rage-click capture are also off; the app keeps its existing Expo notification integration. The
iOS Info.plist switch disables the SDK push-open hook before JavaScript starts. Remote project settings still
control whether recording starts. `startSessionRecording()` resolving does not prove recording
is active: the SDK can retry while waiting for remote configuration. Check the received recording.

The workspace patch for `@posthog/react-native-plugin@2.12.7` keeps native automatic recording disabled, including when the React Native SDK initializes replay for a manual start.
Explicit starts still record, but an explicit stop prevents delayed remote configuration, session changes or event triggers from restarting capture.
The patch covers the plugin's JavaScript entry points and leaves its native code unchanged.
Keep this patch until the React Native SDK preserves manual-only recording through native initialization; `src/lib/demoReplay.sdk.test.ts` checks that boundary with the real SDK and verifies that stopping cancels pending retries when configuration arrives later.

On both iOS and Android, before allowing live-data capture:

1. Launch with the replay variable absent and confirm no recording. Repeat in a store build
   with the variable set. Neither may record.
2. In an internal build with the variable set, enter **Try the demo**, navigate for at least
   ten seconds, scroll a report and open a chat. Confirm a native replay arrives in the test project.
3. Inspect snapshots for masked text, passwords, images and system pickers. Test keyboard entry,
   a Mermaid WebView and a Skia chart. Native text masking cannot establish that custom-rendered
   content is masked. Demo fixtures are the only permitted content for this prototype.
4. Leave demo mode while remote configuration is delayed, and sign in. Confirm recording stops,
   never restarts after remote configuration arrives, and the live root stays masked.
5. Background, foreground, terminate and relaunch. Verify SDK session rotation and recordings
   agree. Check the underlying Android API 26+ and iOS 13+ requirements against the app's higher
   deployment targets. Native build success alone does not validate capture or privacy.

See [React Native replay installation](https://posthog.com/docs/session-replay/installation/react-native)
and [privacy controls](https://posthog.com/docs/session-replay/privacy).

## Web/mobile handoff prototype

The shared handoff protocol lives in `shared/handoffProtocol.ts`. Its local TypeScript configuration lets Storybook build it without installing Expo. The browser integration lives in `frontend/src/lib/utils/webMobileHandoff.ts` at the repository root.

This prototype correlates separate sessions. It does not produce one recording spanning web and
native. Identity (`distinct_id`), authentication, analytics sessions (`$session_id`) and the
random `handoff_id` are separate. No identity or session setter is called during a handoff.

The installed React Native SDK 4.84.2 can read and rotate sessions, but cannot bootstrap or set
an existing session ID through its public API. The native replay plugin starts with the React
Native SDK's own session ID. Overriding `$session_id` on a capture would therefore misrepresent
recording continuity. The web SDK supports `bootstrap.sessionID`, but accepting one from an
unsigned deep link would not establish a trusted same-user session. This prototype keeps both
SDKs' session management intact. The handoff opt-in enables `enablePersistSessionIdAcrossRestart`
on native, so returning to native can retain its existing session within the SDK's idle and
maximum-duration limits, even after a process restart. That does not transfer the web session.

For an end-to-end check, run the web app with the `mobile-session-handoff` feature flag enabled,
and an internal native build with `EXPO_PUBLIC_POSTHOG_HANDOFF=1`. Both clients must send to the
same test analytics project to query correlation together. The handoff flag is independent of
recording: a correlation event does not prove that either session has a replay.

1. Sign in to the same PostHog host in the native app. Open an insight, chart detail, view,
   or chat link in the browser. Only HTTPS links inside the signed-in host and current
   `/project/<id>/` are decorated. External links, other regions/projects, OAuth and existing
   fragment links keep their navigation unchanged. The source event carries `handoff_id`.
2. The web app removes the fragment marker before SDK initialization and emits
   `web_session_handoff_received` when its flag is enabled. Match its `handoff_id` to
   `mobile_session_handoff_started`. Compare the events' SDK-assigned `$session_id` values:
   they are distinct, and neither identity has changed because of the link.
3. To exercise web-to-native from a local test page in the running PostHog web app, add a normal
   anchor with `href="posthog-dev://inbox"` (or `posthog-preview://inbox`) using browser developer
   tools. Click it. The page's delegated click handler adds a marker and emits
   `web_session_handoff_started`. Native strips the marker and emits
   `mobile_session_handoff_received`, including on cold start. No new web navigation button
   is shipped by this prototype. Production `posthog://` links are excluded.
4. Return to the original client and confirm its own session continues within SDK timeouts.
   After expiration, confirm its SDK starts a new session. Log out and switch accounts;
   authentication and normal identity reset must remain independent of the handoff.
5. Try disabled flags, an expired marker, duplicate markers and an OAuth callback. They must
   not alter identity, authentication or session state. Existing routing must still work.

Markers contain a random UUID and send time, expire after two minutes, and travel in the
fragment rather than a query or referrer. No token, user ID, source session ID, report title or
message enters the marker. Correlation is unverified diagnostic metadata: never use it for
access control, identity merging, or session adoption. Device clocks must agree; future markers
are rejected. URL fragments can still be observed by local browser scripts and history.

True cross-platform continuation needs a supported React Native session bootstrap/setter,
verified native-recorder synchronization, trusted account/project-bound exchange, and player
validation for mixed web/native recordings. No SDK internals or persisted session storage are
modified here. See [SDK bootstrapping](https://posthog.com/docs/libraries/bootstrapping),
[session semantics](https://posthog.com/docs/data/sessions), and
[React Native bootstrap support request](https://github.com/PostHog/posthog-js/issues/4978).
