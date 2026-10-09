# Architecture

## Directory map

```text
products/mobile/
  app/                    Expo Router routes. Thin: read params, mount a screen.
    _layout.tsx           Providers (gesture handler, safe area, keyboard, TanStack Query), auth gate,
                          push registration, notification routing, analytics, error boundary
    +native-intent.tsx    Drops the Android OAuth callback deep link so it never opens a screen
    index.tsx             Redirect to /inbox (demo mode or signed in) or /sign-in
    sign-in.tsx           -> src/auth/SignInScreen
    inbox.tsx             -> src/features/inbox/InboxScreen
    report/[id].tsx       -> src/features/report/ReportScreen
    chat.tsx              -> src/features/chat/ChatSheet (transparent modal, draws its own sheet)
    settings.tsx          -> src/features/settings/SettingsScreen
  src/
    api/                  client.ts (fetch wrapper: base URL, bearer, refresh on 401, mobile header),
                          sse.ts (event-stream parser and reader), queryClient.ts, and one typed
                          module per backend domain: users, reports, today, tasks, conversations,
                          pushTokens. Each module declares the response fields it reads and names
                          the serializer it mirrors.
    auth/                 oauth.ts (PKCE flow, refresh, revoke), tokens.ts (secure store),
                          account.ts (@me and projects), regions.ts (hosts and client ids),
                          authStore.ts (zustand), useViewer, SignInScreen
    model/                types.ts (the view-model contract), sources.ts, agent.ts, queryStates.ts,
                          adapters/ (Today and signals responses -> view models)
    demo/                 briefings.ts (raw prototype data), fixtures.ts (view models), derive.ts,
                          demoMode.ts (zustand store), hooks.ts (demo query hooks)
    features/
      inbox/              InboxScreen, InboxRow, InboxHeader, BottomBar, NavMenu, hooks
      report/             ReportScreen, TopChrome, Headline, Evidence*, ReplayRow, Facts, Activity, hooks
      handoff/            ActionBar and its cards, HandoffSheet, actionBarState, kickoff, prompt,
                          runStream (reducer), toolPolicy, permissionRequest, commands, useTaskRun,
                          useReportWithLiveRun, handoffStore, hooks
      snooze/             SnoozeSheet, CustomSnoozePicker (.web.tsx for web), snoozeTimes,
                          snoozeStore, snoozeEntries, reminders, hooks
      reviewers/          AssigneeSheet, hooks
      chat/               ChatSheet, Composer, MentionPopover, Thread, ChatEmptyState, ChatMarkdown,
                          conversation (reducer), contextPrompt, chatErrors, webLinks, hooks
      notifications/      pushSupport, pushStore, pushRegistration, usePushRegistration,
                          notificationRouting, taskLookup, useNotificationRouting
      settings/           SettingsScreen, ProjectSwitcher, PushStatusGroup, SignOutSection, appInfo
    lib/                  analytics, posthogClient, dates, errors, haptics, richText, useAsyncAction, useNow
    ui/                   tokens.ts, primitives, icons/
  plugins/                Expo config plugins (withIosSceneLifecycle: UIScene life cycle for Xcode 27)
  .argent/flows/          Argent flows that drive the app on a simulator (see TESTING.md)
  assets/                 placeholder icon, adaptive icon, splash, favicon
  scripts/                generate-placeholder-assets.mjs, eas-build.sh
```

## Data flow

```text
route (app/) -> feature screen -> feature hooks -> useDataMode()
                                                   ├─ 'loading' -> loading QueryState
                                                   ├─ 'demo'    -> src/demo (fixtures + useDemoMode store)
                                                   └─ 'live'    -> src/api fetchers + TanStack Query
                                                                   -> src/model/adapters -> view models
```

Screens render only the types in `src/model/types.ts`.
Every data hook returns `QueryState<T>`, which TanStack Query's `UseQueryResult<T>` satisfies.
`useDataMode()` waits for the persisted demo flag to load, so a cold start never flashes an error.

The report screen reads `useReportWithLiveRun(id)`, which takes `useReport(id)` and overlays the
live task run (status, stage, pending question, PR URL) and the hand-off prompt.
The footer state comes from the pure `actionBarStateFor(report, local)` in
`features/handoff/actionBarState.ts`.

Mutations go through `useAsyncAction`, which exposes a `pending` flag and drops a second call
while one is in flight. Buttons read the flag to disable and show progress.
Hand-off and decision actions resolve on failure and surface the error through
`useHandoffNotice`, so the footer shows one line instead of an alert.

## Live data sources

| Need | Source | Fallback |
| --- | --- | --- |
| Inbox rows | `GET today/briefing/?timezone=` | `GET signals/reports/?scope=for_me&status=ready,pending_input,failed&sort=priority` when Today returns 403 or 404 |
| Report page | `GET signals/reports/{id}/`, `/signals/`, `/artefacts/`, `GET today/reports/{id}/page/` | Signals only when the Today page is unavailable |
| Current run | `GET tasks/{taskId}/` then `GET .../runs/{runId}/stream/` (SSE) | Polling the run on stream errors |
| Chat | `POST conversations/` (SSE) | none |
| Reviewers | `GET signals/reports/available_reviewers/`, `PUT signals/reports/{id}/reviewers/` | none |
| Snooze | `POST signals/reports/{id}/state/` for "until more signals"; on-device store for times | none |
| Read state | `POST signals/reports/read_state/` | none |
| Push | `POST /api/users/@me/push_tokens/` | unavailable on web and Expo Go |

Details per domain: [DATA.md](DATA.md), [HANDOFF.md](HANDOFF.md), [CHAT.md](CHAT.md),
[AUTH.md](AUTH.md), [PUSH.md](PUSH.md).

## Hook surface

| Hook | File | Returns |
| --- | --- | --- |
| `useInboxItems()` | `features/inbox/hooks.ts` | `QueryState<InboxItem[]>` |
| `useMarkReadAction(id)`, `useMarkReadOnOpen(id)` | `features/inbox/hooks.ts` | `AsyncAction<[]>`, `void` |
| `useReport(id)` | `features/report/hooks.ts` | `QueryState<ReportView>` |
| `useReportWithLiveRun(id)` | `features/handoff/useReportWithLiveRun.ts` | `QueryState<ReportView>` with the live run merged in |
| `useReportActions(id)` | `features/report/hooks.ts` | `ReportActions` (`handOff`, `answerDecision`, `undoDecision`, `snooze`, `setReviewers`, `markRead`, `pending`) |
| `useReportNeighbors(items, id)` | `features/report/hooks.ts` | `{ previousId, nextId }`, wrapping |
| `useHandoffActions(id)`, `useDecisionAnswer(id)`, `useHandoffNotice(id)` | `features/handoff/hooks.ts` | actions, the device-side answer, the footer error line |
| `useTaskRun(taskId, runId)` | `features/handoff/useTaskRun.ts` | live run state from the stream |
| `useSnoozeAction(id)`, `useSnoozeEntries()` | `features/snooze/hooks.ts` | `AsyncAction<[SnoozeChoice]>`, active snoozes |
| `useAvailableReviewers(query)` | `features/reviewers/hooks.ts` | `QueryState<Person[]>` |
| `useSetReviewersAction(id)` | `features/reviewers/hooks.ts` | `AsyncAction<[string[]]>` (full replace) |
| `useConversation()` | `features/chat/hooks.ts` | `{ messages, phase, error, title, conversationId, send(text, context), retry, stop, reset }` |
| `usePushRegistration()`, `useNotificationRouting()` | `features/notifications/` | registers the device, routes taps |
| `useViewer()` | `auth/useViewer.ts` | `{ name, projectName }` |

## Stores

- `useAuthStore` (`src/auth/authStore.ts`, zustand, non-secret state persisted with AsyncStorage,
  tokens in the secure store): `status`, `signedIn`, `region`, `host`, `clientId`, `method`,
  `user`, `organizations`, `projects`, `projectId`, `projectName`, `signedOutReason`;
  actions `restore`, `signIn`, `signInWithPersonalApiKey` (dev builds), `selectProject`,
  `reloadAccount`, `signOut`. It installs the auth provider that `src/api/client.ts` uses for
  the base URL, bearer token and refresh.
- `useDemoMode` (`src/demo/demoMode.ts`, persists only `enabled`): in-memory demo state for
  hand-offs, decisions, snoozes, read flags, reviewers and the activity log.
- `useSnoozeStore` (`src/features/snooze/snoozeStore.ts`, persisted): time and signal-count
  snoozes keyed by host, project and report, with expiry.
- `useHandoffStore` (`src/features/handoff/handoffStore.ts`): the task and run a hand-off
  started on this device, pending answers and the footer notice.
- `usePushStore` (`src/features/notifications/pushStore.ts`, persisted): permission state and
  the registered token.

## Module boundaries

- `app/` imports screens only.
- `src/ui` holds generic primitives and imports nothing from `features`, `demo`, `auth` or `api`.
  It imports the `Accent` type from `src/model`.
- `src/model/types.ts` imports nothing. `src/model/adapters` imports the API types in `src/api`
  and helpers in `src/lib`, and nothing from `features`.
- `src/api` imports nothing from `features`, `demo` or `auth` (the auth provider is injected).
- `src/features/*` may import `src/model`, `src/ui`, `src/lib`, `src/api` and other features'
  hooks. Fixtures reach screens only through hooks. Screens import the `useDemoMode` store
  directly only to turn demo mode on or off.
- `src/demo` imports `src/model` and nothing from `features`.
