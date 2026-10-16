# Decisions

Choices the build contract left open, with the reason for each.

## Toolchain and versions

- **Expo SDK patch level.** `expo ~57.0.8` resolved to 57.0.26, the newest release older than
  7 days. Its `bundledNativeModules.json` expects React Native 0.86.3, Reanimated 4.5.1 and
  Worklets 0.10.1, so those are pinned instead of desktop's 0.86.0 / 4.5.0 / 0.10.0.
  `react-native-gesture-handler` follows Expo's `~2.32.0`, not 3.x.
- **React 19.2.6** matches desktop and sits in `expo.install.exclude` with `react-dom` and
  `typescript`, the same way desktop does it.
- **Release age.** `pnpm-workspace.yaml` sets `minimumReleaseAge: 10080` (7 days), the same as
  the repo root. This is why `posthog-react-native` is `^4.78.0` (desktop's `^4.80.0` is newer
  than 7 days) and why `expo-doctor` still lists patch releases from 2026-10-06. Bump them with
  `npx expo install --fix` once they are a week old.
- **Extra packages.** `@react-native-community/datetimepicker` (Expo's 9.1.0) for "Custom…"
  snooze; `@react-native/jest-preset` and `@react-native/metro-config` 0.86.3 to settle peer
  dependencies; `jest` 29 and `@types/jest` for `jest-expo` 57.
- **No `metro.config.js`.** This directory is the workspace root, so Expo's default config
  resolves everything. No monorepo watch folders are needed.
- **pnpm workspace.** `packages: ['.']` makes this a single-package workspace so pnpm never walks
  up to the repo root, which excludes `products/mobile`.
- **Typed routes off.** They need `expo start` to generate types before `tsc` passes. Expo removed
  the generated-type entries from `tsconfig.json#include` on first start for the same reason.
- **EAS** uses Node 24.13.0, the repo's version.
- **Charts.** `victory-native` 42.0.1 on `@shopify/react-native-skia` 2.6.2, the Skia version Expo SDK 57 pins.
  It is the only candidate with line and bar charts and scrubbing on the UI thread (`useChartPressState`).
  The runner-up, `react-native-gifted-charts`, was rejected because it scrubs on the JS thread.
  Skia's install script links its prebuilt binaries, so `pnpm-workspace.yaml` allows it in `onlyBuiltDependencies`.
  On web, `pnpm web` copies CanvasKit to `public/`, and only screens with a chart load it, lazily.
  Tick labels are React Native `Text`, so the app ships no font file for Skia.

## Architecture

- **Hooks per feature.** `useReportActions` composes `useHandoffActions`, `useSnoozeAction`,
  `useSetReviewersAction` and `useMarkReadAction`, so each data source lives in one `hooks.ts`.
- **Live branches return error states** for reads instead of throwing during render, so a missing
  piece shows the error screen with Try again. Actions throw `NotImplementedError`.
- **`useDataMode()`** waits for the persisted demo flag, so a cold start shows loading, never an error.
- **Overlays on the report screen are components, not routes.** The chat sheet is a route
  (`presentation: 'transparentModal'`, no stack animation) that draws its own scrim and 94% sheet,
  so it looks the same on iOS, Android and web.
- **Inbox and Chats are tabs** (`app/(tabs)/`, `Tabs` from `expo-router/js-tabs` with a custom `tabBar`), so the
  bottom bar renders once and stays put when the tab changes. `backBehavior="firstRoute"`: Android back from Chats
  returns to Inbox, and back from Inbox leaves the app.
- **Menus and sheets draw through `OverlayPortal`.** The tab navigator draws its bar after the scenes, so an overlay
  inside a tab scene would draw under the bar. `FloatingCard` and `BottomSheet` render into the `OverlayHost` in
  `TabsLayout`, above the bar. Screens outside the tabs have no host, so their overlays render in place.
- **Animations** use Reanimated shared values through `usePresence`, not `@gorhom/bottom-sheet`
  (one fewer dependency) and not Reanimated layout animations (custom ones are unreliable on web).
- **Prev/Next** uses `router.setParams`, so switching reports does not push a screen. It wraps
  through the whole inbox list, like the prototype's `nextAny`.
- **Refresh in demo mode** resets every demo change and re-anchors fixture times, with a 450ms
  refreshing state. Pull to refresh does the same.
- **Error boundary.** `app/_layout.tsx` exports a branded boundary with Try again.

## Visual

- **Status bar** is `dark` (dark content on the light background). The contract's "light status
  bar" read as "the light theme".
- **CSS box sizing.** Sizes follow what the prototype renders, not the raw CSS numbers. See
  [DESIGN.md](DESIGN.md#reading-handoff-values).
- **Web preview insets.** The web build uses the prototype's 54pt status bar and 34pt home
  indicator as insets, so it previews like a phone.
- **Floating chrome blurs what scrolls under it.** The inbox header, bottom tab bar, report top chrome and Settings chrome sit on
  `BlurEdge` (`expo-blur` masked by the `FadeEdge` gradient through `@react-native-masked-view/masked-view`)
  under a 72% background tint, so rows soften and dissolve under the chrome instead of vanishing behind
  a solid block. Android uses the experimental `dimezisBlurView` method; without it the view is only a
  tint. The web build has no masked view, so it masks the blur with CSS `mask-image`.
  Top chrome fades down into the content; the bottom tab bar fades up, with the same blur intensity and tint.
- **Shadows.** Native uses `shadow*` + `elevation`; web uses the exact CSS `boxShadow`, because
  react-native-web renders `shadowRadius` as a blur half the handoff's size.
- **Text wrapping.** `lineBreakStrategyIOS="standard"` on iOS and CSS `text-wrap: pretty` on web
  match the prototype's wrapping of headlines, ledes, questions, PR titles and quotes.
- **Focus ring.** Web text fields drop the browser outline; the field container is the affordance.
- **Disabled chat tools.** Expand renders at 40% opacity because it does nothing yet.
- **Nav pill** shows the handoff's three slots as Home, Chat and Products. The app has no Spaces or
  Views, so the chat-bubbles slot opens the chat sheet and the grid slot opens the web app's product
  library (`/project/{id}/library`, the web rail's Products pane), which has no product screen in the app.
- **Bottom padding floor.** `bottomOffset()` never returns less than 16pt. The handoff's bottom paddings include the
  34pt home indicator, so on a device with a home button (inset 0) several came out between 0 and 14pt.

## Content and behavior

- **Sources.** Error → `error_tracking`, GitHub → `github`, pganalyze → `pganalyze`,
  Product Analytics → `analytics`, Report → `signals_scout`. Dashboards has no source product, so
  the model adds `dashboard` (Today's `dashboard` group) and `other` (unknown values).
  Default labels are sentence case ("Product analytics"); fixtures keep the prototype's
  "Product Analytics".
- **Fixture people.** "Chris Volzer" is "Alex Kim" and "CV" is "AK". "Chris" in trace footers and
  in "Asking Chris in the thread" is a teammate in the story, so it stays.
- **Fixture times** are computed from the moment demo mode starts. A weekday such as "Mon 7:21 AM"
  is the most recent Monday one to seven days back, so the timeline prints the prototype's text.
- **Fixture 3** (report load time) starts `unclaimed` so its footer is idle, as in the reference
  screenshot, even though its owner chip says Claude Code.
- **One agent.** New demo activity says "PostHog". Historic fixture entries keep Codex and Claude
  Code verbatim. All agent marks are `ph`.
- **Inbox rows** show `{source} • {time}` only, like the prototype template. A snoozed row shows
  "Snoozed until …" in place of the time (README). `progressLabel` and `agent` stay in the model
  for later.
- **Hand-off sheet** keeps the selected-row styling for its single PostHog row. Its meta line reads
  "PostHog agent · opens a PR in your repo", which says what handing off does, because the app offers one agent.
- **Refresh replaces the prototype's Reset.** The inbox header button refetches the inbox. In demo mode it also resets
  the demo, which is what Reset did, so one button covers both modes.
- **Decided card meta** comes from the answer: the prototype's text rules in demo mode, the run's
  `stage` from the run.
- **PR card.** "Review PR" calls `Linking.openURL`, which opens the GitHub app when installed,
  where the user is signed in. An in-app browser would not share that session. Only `https://` URLs open
  (`safeHttpsUrl` in `src/lib/urls.ts`), because the URL comes from the run's output.
- **Assignee sheet** is multi-select because reviewers are a list. A dark "Done" pill appears next
  to Close once the selection changes; Close and the scrim discard changes. The activity entry
  reads "changed assignee to **A, B**", or "removed the assignee".
- **Snooze sheet** adds "Until more signals arrive" with "Hide until 5 more signals" under the label
  (too long for the right column). Day presets wake at 9:00 AM local time; "In a month" is 30 days,
  as in the prototype. "Custom…" shows wheels inside the sheet on iOS, the date and then time
  dialogs on Android, and a typed `YYYY-MM-DD HH:MM` field on web.
- **Mention popover** eyebrow reads "ADD A REPORT", not "ADD A BRIEFING", to match "add a report as
  context" in the chat subtitle.
- **Chat** keeps the "New chat" title after the first message. The demo answers with a canned
  reply after 600ms.
- **Mark read** runs when a report opens and again on Prev/Next. Read state is not styled.
- **Settings** shows the version to everyone. Internal builds (dev, preview, or any Metro session) add an
  Environment group: build variant, update channel, update id and time from `expo-updates`, and the API host kind.
  Store builds show nothing about environments unless the session's host is not PostHog Cloud.

## Verification

- `hogli product:lint --all` (the CI gate) only lints product directories with `__init__.py`, so it
  skips `products/mobile`, the same as `products/desktop`. Running `hogli product:lint mobile`
  by name reports a missing `__init__.py`, a missing tach entry and Python test files inside
  `node_modules`, exactly as `hogli product:lint desktop` does. The fix belongs in the linter.

## Chat

- **One runtime: tasks.** Every chat is a task with interactive runs, as on the web's side panel.
  The tasks endpoints accept `task:read` and `task:write`, so the LangGraph path below is gone from the app,
  and the bullets about `conversations/`, its context block, reattach and reconnect describe the removed path.
  [CHAT.md](CHAT.md) has the current behavior.
- **LangGraph endpoint (superseded).** Chat posts to `conversations/`, the LangGraph runtime. The sandbox runtime
  opens through `conversations/:id/open/`, which declares no OAuth scopes, so an app token gets 403.
  `frontend/src/scenes/max/AGENTS.md` freezes the LangGraph path; the app only consumes it.
  Move to the sandbox runtime once its endpoints accept `conversation:write`.
- **Context is text in `content`.** `MaxUIContext` has no report key and rejects unknown keys, so the
  app sends the Today page's `<posthog_context>` block, ported with the two kickoff constants verbatim.
  Each report's summary is inlined (first 1500 characters) because this agent has no report tools.
- **Several reports.** One bullet group per report under a plural heading. The action framing and
  `REPORT_DISCUSSION_STATE_INSTRUCTIONS` go out only when every attached report can be acted on.
  At most 5 reports attach, to keep the prompt small.
- **Global chat sends the inbox.** With no report attached, up to 20 inbox rows go in a
  `#### Context from my PostHog inbox` block, so "What needs me today?" has something to answer from.
- **Context on every message** while a chip stays attached, because the chip says it is attached.
- **Files upload at send time**, as on the web. A new chat has no task until it sends, and staged files expire, so an upload at pick time would need a task the person may never use.
- **Text stays required with files.** The web never sends files alone, and the echo pairs the bubble by its text.
- **Picked files stay in memory.** The draft store keeps text and report ids only. A file URI points into the picker's cache, which the system can clear, so a restored draft could point at nothing.
- **The Attach menu is a bottom sheet**, as the Model and Mode pages are. The keyboard drops before it opens and moves the composer, so a menu anchored to the button would open where the button was.
- **A new chat never claims a warm run.** The create sends no `branch`, so the server cold-creates the task, and the files always stage on it for `run/`.
  The web uploads to a warm run before the create; the app has no warm run to upload to.
- **A resume uploads the files again.** Ids from a run-scoped upload are valid only on that run, so a 409 on `user_message` stages the files against the task for the new run.
- **`send(text, context)`** instead of `send(text, reportIds)`. Each context chip loads its report with
  `useReport`, so the sheet holds the views and builds the context. ARCHITECTURE.md's hook table still
  says `reportIds`.
- **Suggested prompts fill the composer**, as in the prototype, instead of sending at once as the web
  inbox does. The server's `suggested_prompts` replace the defaults only for one attached report the
  agent may act on, matching the web.
- **Header title** shows the title the server generates, replacing the earlier "keeps New chat" choice.
  A compose button in the right slot starts a new chat once the thread has messages.
- **Stop replaces Send** while a reply streams. A 409 after Stop takes the new bubble back,
  reattaches to show the end of the stopped turn, then sends the message.
- **Reconnect only after the stream opened.** Before that the server may not have the message, so
  the error entry offers Try again instead of resending on its own.
- **Markdown** uses `react-native-markdown-display` with `html: false`. Images are dropped, relative
  links open on the signed-in host, and a trailing list marker is hidden while a snapshot streams.
- **Demo replies stream** through the same reducer (a tool step, snapshots, the final message), so
  Stop, the progress line and markdown all show in demo mode.
- **Sessions use the tasks API.** The sandbox conversation endpoint (`conversations/:id/open/`) declares
  no OAuth scopes, so an app token gets 403 there. The tasks endpoints accept `task:read` and `task:write`,
  which the app already has for the hand-off, and the web's `TaskRunChat` reads the same runs.
- **Logs for an ended run, the stream for a live one.** An ended run has nothing left to stream, so one
  `logs/` request reads the whole log without holding a connection open. A live run's stream replays the stored log
  before the new frames, so one connection gives both the history and the live turn without a gap between them.
- **A successor run rebuilds the thread.** The first replayed frame of a resume run starts the thread
  again, because the server replays the whole resume chain. Appending would draw every earlier turn twice.
- **Answers echo as a user bubble.** The agent never echoes a `permission_response`, so without a local
  bubble the thread would show no trace of what the person picked.
- **One sheet, two modes.** The sheet mounts `useConversation` and `useSession` and switches with a
  `mode` state, so the header, composer, @-mentions and drag dismissal stay one implementation.

## Inbox and report data

See [DATA.md](DATA.md) for the endpoint map and every adapter rule.

- **Hand-written API types.** `src/api/today.ts` and `src/api/reports.ts` declare only the fields the adapters read, each naming its serializer. Adapters in `src/model/adapters/` do all mapping, so a response change touches one adapter.
- **Model boundary.** `src/model/adapters/` imports API types (type-only) from `src/api`, date formatting from `src/lib/dates` and the record guards from `src/lib/records`. The rest of `src/model` still imports only `src/ui/icons`.
- **The hand-off prompt is not built by the adapter.** `reportView()` returns the view without `prompt`, because the prompt text lives in `features/handoff/prompt.ts` and adapters import nothing from features. `useReport` adds it from the report's `webUrl`.
- **The inbox is the whole ranked list, not the briefing.** It pages through `signals/reports/for_you/`, which ranks reports the way the Today briefing does, so the order matches the web while the list holds every report for the user, not the briefing's top five.
  It needs no Today: the list is a signals endpoint, so a Today outage or a token without `today:read` does not change it.
- **Only the user's reports.** The list passes `include_unowned=false`, so a P0 that nobody owns does not lead it. That report belongs to the project.
- **Pages of 20**, the most `for_you/` returns in one call. The next page loads when the user scrolls within half a screen of the end.
- **A refresh keeps only the first page.** Refetching every loaded page would rank the whole list once per page.
- **Prev/Next wrap only over the whole list.** While more pages exist, Next on the last loaded report waits for the next page instead of going back to the top.
- **Report screen waits** for the report, work log and Today page, and for signals only when there is no page. The task loads after and fills in; ownership from a claim does not prove that execution is running.
- **Report prefetch is a window with a concurrency cap.** The inbox prefetches the first two pages (40 reports) and the rows near the visible ones, two reports at a time, not the whole list at once.
  Each report is 3 to 4 requests, so a full-list prefetch would load the phone's radio and the server for reports nobody opens.
  It fetches only what the report screen waits for before its first render: the report, the work log, the Today page, and the signals when there is no page.
  The report screen still refetches on every open, because a fresh report matters more than a cache hit.
  The cache only removes the loading screen.
- **Headline number** comes from the title first, then from the Today lead's first sentence (at most 120 characters). A report with neither shows the title with no number.
- **Hot bars** start at the first bar more than 15% of the spread away from the median of the first quarter, and a tail of two or more bars back at the baseline is cold. It matches the prototype's bars except one edge bar.
- **Owner for an external agent claim** names the MCP client ("Claude Code") instead of "PostHog", because that agent is not the PostHog agent. Task and system claims say "PostHog".
- **Reviewer activity** reads "changed reviewers to", as the server calls them. Pipeline writes read "PostHog suggested **A** as reviewers".
- **GitHub-only reviewers** are sent back unchanged when the sheet saves, because the PUT replaces the whole list and the sheet cannot show them.
- **Signal snoozes are remembered on the device** with the server's `signals_at_run` threshold, so the row reads "Snoozed until more signals" until the list refetches without it.
- **Opening a report ends its time snooze** and cancels the reminder. Prev/Next counts as opening.
- **Snooze reminders never ask for permission.** A time snooze schedules its reminder only when notifications are
  already allowed. Otherwise the snooze applies without a reminder, because later permission prompts come only from
  the Settings button.
- **Snooze and reviewer errors stay in the sheet.** A failed snooze or reviewer change keeps its sheet open with one
  orange line under the title, from the server's `detail` or `error` when it sent one.
- **At most 10 reviewers**, the PUT's `MAX_ENTRIES`, counting the GitHub-only reviewers the sheet cannot show. The sheet
  stops adding at the limit and says why.

## Auth and push

- **Unscoped grant.** The authorize request omits `required_access_level`, so a first-party token covers every organization and the project switcher can list all projects.
  The project list comes from `@me.organization.teams` plus `GET /api/organizations/{id}/` for the other organizations, not from the token's `scoped_teams`.
- **Projects are teams.** The switcher lists team ids, which is what `/api/projects/{id}/` paths take.
  The default project is the last one picked on this device, then the user's current web team, then the first one.
- **Own token exchange.** The code exchange and refresh post JSON with `fetch` instead of `exchangeCodeAsync`, so the app controls error handling and reads the raw response.
- **Refresh failure policy.** 400, 401 and 403 from `/oauth/token` end the session. Network errors and 5xx keep it, so a user is never signed out by being offline.
- **Single-flight refresh.** Concurrent 401s share one refresh. Two parallel refreshes would race the rotation and could trip reuse protection, which revokes the whole token family.
- **Screens wait for the session.** `app/_layout.tsx` renders the stack only after `restore()`; until then the native splash stays up (web shows `BootSplash`). Feature hooks never see a missing token at launch.
  The native splash then also waits for the inbox's first load, data or error, so the logo hands over to a filled inbox with no spinner. Any other first screen releases it on mount. An 8 second cap (`SPLASH_TIMEOUT_MS` in `src/auth/bootGate.ts`) releases it if the load hangs.
- **One redirect to sign in.** `useAuthRedirect()` sends every screen to `/sign-in` when the session ends and demo mode is off, including a refresh failure in the middle of a session.
- **In-place confirmation.** Sign out confirms inside Settings, and inside the inbox menu, instead of `Alert.alert`, which does nothing on react-native-web.
  Both use `SignOutConfirm` and `useSignOutAction`. A demo session without an account leaves the demo with no confirmation.
- **OAuth sign in is native only.** The web build has no registered redirect, so Sign in on the web says to use the apps or the demo. Dev builds can use a personal API key on the web.
- **Sign-out tasks.** `addSignOutTask()` lets the notifications feature unregister its token without the auth store importing a feature.
  `addSessionEndTask()` runs device cleanup on every session end, an expired session too: the snooze feature clears its store and cancels the reminders, and the hand-off feature clears its store.
- **Push prompt.** The app asks for notification permission once, right after the first sign in, never on the sign-in screen. Later prompts come only from the Settings button.
- **Foreground pushes** show a banner without sound or badge only when they need attention outside the report
  currently on screen. Report pushes and task pushes associated through cached task/report data are suppressed
  for the viewed report or an active local time snooze. The handler never fetches data: unknown associations and
  legacy pushes without a project remain visible. Signal snooze labels do not mute pushes because the server
  decides when those reports wake.
- **Foreground duplicate protection** remembers up to 256 event/request keys for 24 hours in memory, scoped to
  the account and project. Repeated terminal outcomes for one run, first-visible report events, message events,
  and the same OS notification are suppressed. Different turns, questions and PR-ready events are preserved:
  their payloads do not yet identify a distinct occurrence reliably. This does not change OS delivery while
  backgrounded or after termination, and the memory resets when the process restarts.
- **Notification taps wait for sign-in.** A cold-start response stays pending until navigation and the account
  are ready. Receiving the same response through both startup and the listener opens it once.
- **Task pushes name their project.** Routing looks the task up in that project only. A push without `projectId` (sent before the server added it) looks in the current project first, then the others, up to 8 lookups, and opens the inbox when none has it.
- **Analytics.** `src/lib/posthogClient.ts` creates the `posthog-react-native` client only when `EXPO_PUBLIC_POSTHOG_KEY` is set (host `EXPO_PUBLIC_POSTHOG_HOST`, default `https://us.i.posthog.com`). It identifies by `distinct_id` after sign in and on restore, and resets on sign out. `track()` stays the only capture call site, with `trackScreen()` for `$screen` and `captureError()` for `$exception` beside it in `src/lib/analytics.ts`. Code that can run before `initAnalytics()` (`app/+native-intent.tsx`) uses `trackWhenReady()`, which holds up to five events until the client exists. `useScreenTracking()` in the root layout sends one `$screen` per route, named by the route pattern without groups (`inbox`, `report/[id]`), with `report_id` on reports. `RouteErrorBoundary` sends `mobile_screen_error_shown` (`screen`, `error_name`) and one `captureError()` per error, and `mobile_screen_error_retried`. The root layout sends `mobile_splash_hidden` with `reason` (`first_screen`, `timeout` or `not_held`) and `wait_ms` once per cold start.

## Hand-off and task runs

- **The prompt reads the report fresh.** `handOff` only has the report id (it is composed into `useReportActions`), so the kickoff fetches `GET signals/reports/{id}/` for the title and summary. It is the same data the web prompt uses, and it avoids a side channel from the screen to the action.
- **One run follows per report screen.** The current claim's task wins over local starts and historical artefacts. A user or external claim suppresses historical execution. The run is `GET tasks/{id}/`'s `latest_run`, because an artefact's run id can be stale.
- **Live state lives in a zustand store** (`handoffStore.ts`), keyed by report, so the answer action can read the pending request and mark it handled while the stream keeps writing. Screens subscribe with an equality check (`sameVisibleEntry`) so message chunks do not re-render the screen many times a second.
- **The overlay hook is `useReportWithLiveRun` in its own file**, not in `handoff/hooks.ts`, because `report/hooks.ts` imports `useHandoffActions` from there and the overlay imports `useReport` from `report/hooks.ts`.
- **The tool policy is a faithful port** of the web's, including full-auto routing and "never answer a replayed request for the user". If allowing fails, the request becomes a decision.
- **Replayed requests show as decisions.** On first connect the durable log replays. A request still unresolved at the end is something the agent waits on, so the card shows it, like the web.
- **Another client's answer clears a live card** when the asked-about tool call completes or fails, or the turn or run ends, because resolution frames only appear in the replay.
- **A completed turn is idle, not an input request.** Only a structured outstanding question, plan or permission produces the Needs your answer row and decision sheet. Continue the implementation in its task chat; report discussion remains a separate conversation.
- **Several questions in one request show one at a time.** Earlier picks stay on the device and all answers go out together, because the agent expects one reply with every answer.
- **Typed text never approves.** A typed reply to a permission or plan goes with the option that takes text, else a reject option. Only a question's typed answer uses `option_0`, as the web does.
- **Plan approval offers the web's two modes**, "Approve the plan" (`auto`) and "Approve in full auto" (`bypassPermissions`), with the web's mode descriptions shortened.
- **The decided card outlives delivery.** After the agent confirms an answer the card stays, without Undo, until the run shows new activity (a tool call, a step, a message). Undo is offered only while the answer is in flight.
- **Errors show in the footer.** Hand-off and answer actions resolve and put one orange line above the cards, because every caller fires them without awaiting. This differs from the `ReportActions` doc comment ("rejects with an Error").
- **Execution, attention and PR state are independent.** Known PRs stay available through working, idle, unknown, failed and canceled execution. Claims do not imply execution; reconnecting and unavailable streams do not imply the run stopped. PR URL discovery does not imply review readiness, and missing CI stays unknown.
- **Tool titles read as progress.** Paths become file names and Read, Edit, Write, Find, Fetch and Search become "Reading", "Editing" and so on, to match the design's "Reading ChartLegend.tsx".
- **PR cards preserve known state.** Draft, open, merged, closed and unknown PRs remain discoverable. Several PRs use a compact selector. A URL from `output.pr_url` starts unknown until the report confirms its state; absent diff stats or CI are not invented.
- **Foreground freshness.** Only the focused report polls detail, artefacts and task every 15 seconds. Foreground return refreshes them, and meaningful PR/status/turn stream changes refresh them at most once per two seconds. Cached PRs remain visible during loading. Today pages and signals are outside that interval.
- **Stream cursors stay in memory per run**, so coming back to a report resumes after the last event instead of replaying the log.
- **Abort errors are plain `Error`s named `AbortError`** (`src/lib/abort.ts`), used by `sleep` and `readSse`. Expo installs `DOMException` and `TextDecoder` on native, so this and the `TextDecoder` check in `readSse` only matter in a runtime without Expo's globals.

## Delivery

- **EAS uploads only `products/mobile`.** `scripts/eas-build.sh` sets `EAS_NO_VCS=1` and an absolute `EAS_PROJECT_ROOT`. With git, EAS archives the whole repository and installs the root pnpm workspace, which excludes this app. eas-cli 24 still asks git for the root when only `EAS_NO_VCS` is set, so both variables are needed. `.easignore` replaces `.gitignore` for the archive and keeps local `ios/` and `android/` folders out, so EAS always runs prebuild.
- **Each build profile names its EAS environment** (`development`, `preview`, `production`), and the update scripts pass the same `--environment`. Expo SDK 55 and later require `--environment` for `eas update`, and it keeps `EXPO_PUBLIC_*` values equal between a build and its updates.
- **`pnpm` is pinned in `eas.json`** (`10.29.3`, the `packageManager` version), next to `node`.
- **No `update` script.** `pnpm update` runs pnpm's own dependency upgrade, so the scripts are `update:preview` and `update:production`, each tied to its channel.
- **Submissions only from production builds on `master`.** Preview builds use ad hoc signing, which App Store Connect does not take, so TestFlight gets production builds. The Mobile Build workflow uses `--auto-submit` with `--no-wait`, so EAS submits the build it just made, not the previous one.
- **eas-cli 24.8.0 is pinned in CI** instead of `latest`, so a new release does not change a release build without a review.
- **Mobile CI reads Node from `.node-version` and pnpm from this `package.json`**, not from the repo root, so CI, EAS and local runs use the same versions. The check is not required, so it can use trigger paths.
- **iOS 27 SDK scene life cycle.** Apps built with Xcode 27 do not launch without the UIScene life cycle, and the Expo SDK 57 template predates it. `plugins/withIosSceneLifecycle.js` applies the SDK 58 template's change (scene manifest, `SceneDelegate` on `ExpoAppSceneDelegate`, an AppDelegate that provides the React Native factory). It fails the prebuild if the template changes shape. Remove it when the app moves to SDK 58.
- **`EXPO_PUBLIC_DEMO_MODE=1` sets the first value of the demo flag.** The saved value wins after that, so leaving demo mode in Settings sticks.
- **The demo walkthrough is an Argent flow** (`.argent/flows/demo-smoke.yaml`) that ends by tapping Exit demo, so it can run twice in a row. It uses `testID`s except for the hand-off scrim, which it taps by its "Close" label.

## Hedgehog widget

- **The hedgehog lives in a home-screen widget, not in the app.** `modules/hedgehog-widget/README.md` holds the contract. Widgets cannot run JavaScript or animate on their own, so `src/features/hedgehog/choreography.ts` plans a seeded script for the day and the app hands it to the widget once per UTC day through the local Expo module (App Group on iOS, SharedPreferences on Android).
- **iOS uses two-second keyframes; Android plays a closed animation loop.** iOS saves the scheduled timeline and resumes it across taps and refreshes. Each hop or flip completes in one animation, and every saved entry rests upright on the ground so delayed updates cannot strand it mid-flip. Walking uses uninterrupted two-second position animations, isolated from button content changes; reversing does not insert a stationary beat. Android keeps one loop per placed widget, interpolates the standard script at 30 ms intervals, and reuses stable frame views on Android 12+, preserving the visible frame across updates. Older versions restore the tapped frame index on character changes.
- **`@bacons/apple-targets` owns the widget extension target** (`targets/HedgehogWidget/`), so the target survives `expo prebuild`. Its pod is named `PostHogHedgehogWidget`, because the appex already owns the Swift module name `HedgehogWidget`.
- **The widget target needs iOS 17**, for `Button(intent:)` and animated entry transitions, so iOS 16 users see no widget. The app's own minimum is unchanged.
- **A tap on the hog cycles its character and keeps it selected.** Selection persists per iOS widget family or Android widget ID, independently of daily choreography. Taps change the artwork without interrupting the route; background taps open the app. Both widgets bundle the grass layer of PostHog’s Keyboard Garden wallpaper. Dialogue is hidden, including in legacy scripts.
- **Sprites are committed PNGs** cut from the `@posthog/hedgehog-mode` atlas by `scripts/extract_hedgehog_sprites.py` at 2x nearest-neighbour. Android also gets mirrored `_l` copies, because `RemoteViews` cannot flip an `ImageView`.
- **`.gitignore` anchors `/ios/` and `/android/`**, so the module's native folders are tracked and only the prebuild output at the root is ignored.
