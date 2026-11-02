# Architecture

## Directory map

```text
products/mobile/
  app/                    Expo Router routes. Thin: read params, mount a screen.
    _layout.tsx           Providers (gesture handler, safe area, keyboard, TanStack Query), auth gate,
                          push registration, notification routing, analytics, error boundary
    +native-intent.tsx    Drops the Android OAuth callback deep link so it never opens a screen, and opens a web
                          link to one issue or recording at /errors/<id> or /replay/<id> (webLinkTarget)
    index.tsx             Redirect to /inbox (demo mode or signed in) or /sign-in
    sign-in.tsx           -> src/auth/SignInScreen
    (tabs)/               Inbox and Chats share one tab navigator, so the bottom bar stays put when the tab changes
      _layout.tsx         -> src/features/tabs/TabsLayout
      inbox.tsx           -> src/features/inbox/InboxScreen
      chats.tsx           -> src/features/chats/ChatsScreen
      errors.tsx          -> src/features/errors/ErrorsListScreen chrome="tab" (a slot only while pinned)
      replay.tsx          -> src/features/replay/ReplayListScreen chrome="tab" (a slot only while pinned)
    report/[id]/index.tsx -> src/features/report/ReportScreen (`/report/<id>`, as deep links and notifications open it)
    report/[id]/details.tsx -> src/features/report/details/ReportDetailsScreen (the full report)
    errors/index.tsx      -> src/features/errors/ErrorsListScreen chrome="stack" (pushed from the Views Browse row)
    errors/[id].tsx       -> src/features/errors/IssueScreen (`/errors/<id>`, `from` names the source for analytics)
    replay/index.tsx      -> src/features/replay/ReplayListScreen chrome="stack" (pushed from the Views Browse row)
    replay/[sessionId].tsx -> src/features/replay/SessionScreen (`/replay/<id>?t=<seconds>&source=<entry>`)
    chat.tsx              -> src/features/chat/ChatSheet (transparent modal, draws its own sheet;
                          no params starts a new chat, `taskId` and `runId` open one, `reportId` attaches a report)
    settings.tsx          -> src/features/settings/SettingsScreen
  src/
    api/                  client.ts (fetch wrapper: base URL, bearer, refresh on 401, mobile header),
                          sse.ts (event-stream parser and reader), queryClient.ts, and one typed
                          module per backend domain: users, reports, today, tasks,
                          pushTokens. Each module declares the response fields it reads and names
                          the serializer it mirrors.
                          errorTracking.ts holds the error tracking reads and writes ([API.md](API.md#error-tracking)).
                          recordings.ts and replayVision.ts hold the session replay reads and Summarize
                          ([API.md](API.md#session-replay)).
    auth/                 oauth.ts (PKCE flow, refresh, revoke), tokens.ts (secure store),
                          account.ts (@me and projects), regions.ts (hosts and client ids),
                          authStore.ts (zustand), useViewer, SignInScreen
    model/                types.ts (the view-model contract), sources.ts, agent.ts, queryStates.ts,
                          adapters/ (Today and signals responses -> view models)
    demo/                 briefings.ts (raw prototype data), fixtures.ts (view models), derive.ts,
                          demoMode.ts (zustand store), hooks.ts (demo query hooks),
                          sessionThreads.ts (demo session run logs)
    features/
      tabs/               TabsLayout (Inbox, Chats and Views tab navigator), BottomBar and TabsHeader (each
                          rendered once), tabHeaderStore (each tab's header state), NavMenu (the More menu),
                          navPinStore (Errors and Sessions pinned to the nav pill, a device preference),
                          navPinRoutes (openNavTarget: the tab when pinned, a pushed screen when not),
                          navPinActions (pin change with toast and Undo), NavPinMenu (the Views row menu)
      inbox/              InboxScreen, InboxRow, InboxListFooter, hooks,
                          prefetchPlan (prefetch window and queue), usePrefetchReports
      report/             ReportScreen, TopChrome, Headline, HeadlineTitle, ReportMeta, ReportByline, TextLinkRow,
                          Evidence*, ReplayRow, Facts, Activity,
                          hooks, queries (query options shared by the screen and the inbox prefetch)
        metrics/          ObservationCard, ImpactMetrics, ReportCharts, OpenInsightLink, query and value hooks
        details/          ReportDetailsScreen (the full report) and its sections, ReportMarkdown, chartRefs
                          (markdown-it plugin), openDetailsLink
      handoff/            ActionBar and its cards, HandoffSheet, actionBarState, kickoff, prompt,
                          runStream (reducer), toolPolicy, permissionRequest, commands, useTaskRun,
                          useReportWithLiveRun, handoffStore, hooks
      snooze/             SnoozeSheet, CustomSnoozePicker (.web.tsx for web), snoozeTimes,
                          snoozeStore, snoozeEntries, reminders, hooks
      verdict/            VerdictSheet (Resolve and Dismiss), verdictCopy, hooks; reasons in model/verdictReasons
      reviewers/          AssigneeSheet, hooks
      priority/           PrioritySheet, hooks
      chat/               ChatSheet, Composer, ContextChip, MentionPopover, ChatEmptyState, ChatOptionsSheet,
                          chatRunOptions (model and mode), ChatMarkdown, ChatErrorBubble, ChatProgressLine,
                          UserBubble, contextPrompt, chatErrors, webLinks (reply links),
                          objectContext and ObjectContextChip (an issue or recording as chat context)
        session/          useSession (create, follow, send, resume, stop, answer), sessionRun (request bodies
                          and the set_config_option plan), sessionReducer, sessionDisplay, SessionThread and its
                          rows, SessionDecisionPanel
      errors/             ErrorsListScreen, IssueListRow, IssueScreen, IssueSections, IssueActionBar, IssueAssigneeSheet,
                          SuppressSheet, IssueBadges, AssigneeAvatar,
                          hooks (react-query reads, optimistic status and assign), issueModel (pure adapters: rows,
                          badges, frames, sessions, breakdowns, web links, empty copy), analytics
      replay/             ReplayListScreen, SessionListRow, SessionScreen, SessionChrome (Back, Open full replay, More),
                          SummaryCard, ChapterList, FrameSheet, FrameImage (signed frame URLs),
                          SessionTimelineSection, SessionSkeleton, hooks (recording, timeline, summary flow with
                          Summarize and polling, frames, list), sessionAdapters (pure: person labels, timeline,
                          summary, list rows), replayModel (view types), replayLinks (web URLs, `t`), replayAnalytics
      views/              The Views tab and its screens, see VIEWS.md
        screen/           Shared screen chrome: ViewChrome, ViewScreenFrame, ViewTitle, HeaderMenu (the More menu
                          of a pushed screen: a view, an issue, a session), ViewMoreSheet, ViewErrorState, ViewSkeleton
      chats/              ChatsScreen, ChatRow, ChatRowMenu (long-press Archive),
                          chatGroups (day labels, grouping, search), sessionStatus, hooks
      notifications/      pushSupport, pushStore, pushRegistration, usePushRegistration,
                          notificationRouting, taskLookup, useNotificationRouting
      settings/           SettingsScreen, ProjectSwitcher, PushStatusGroup, SignOutSection, appInfo,
                          EnvironmentGroup (internal builds), LegalGroup, SettingsLinkRow, SettingsRadioRow,
                          DefaultPageGroup, defaultPageStore (the tab the app opens on)
    lib/                  analytics, posthogClient, dates, errors, haptics, markdownIt (the shared safe parser),
                          deepLinkKind (link kind for analytics, webLinkTarget for issue and recording links),
                          richText, useAsyncAction, useNow,
                          environment (build variant, host kind, update id), appVariants (+ .json), legalLinks
    ui/                   tokens.ts, primitives (SearchField, StateView, ...), icons/
  plugins/                Expo config plugins (withIosSceneLifecycle: UIScene life cycle for Xcode 27)
  .argent/flows/          Argent flows that drive the app on a simulator (see TESTING.md)
  assets/                 app icon (shared with PostHog Desktop), adaptive icon, splash, favicon, badged dev and
                          preview icons
  scripts/                eas-build.sh, make_variant_icons.py
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
The footer reads independent execution, attention and PR state from the pure
`actionBarStateFor(report, local)` in `features/handoff/actionBarState.ts`. The focused report
polls lightweight report/artefact/task snapshots in the foreground; stream changes trigger
throttled invalidations without refetching on message chunks.
The full report reads `useReport(id)` without polling. It shares the report screen's cache,
so it renders at once and refreshes once when it opens.

Mutations go through `useAsyncAction`, which exposes a `pending` flag and drops a second call
while one is in flight. Buttons read the flag to disable and show progress.
Hand-off and decision actions resolve on failure and surface the error through
`useHandoffNotice`, so the footer shows one line instead of an alert.

## Live data sources

| Need               | Source                                                                                                                           | Fallback                                                                                  |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Inbox rows         | `GET signals/reports/?view=for_you&sort=priority&limit=20&offset=` one page at a time                                            | Loads more while the response has a `next` link                                           |
| Report page        | `GET signals/reports/{id}/`, `/signals/`, `/artefacts/`, `GET today/reports/{id}/page/`                                          | Signals only when the Today page is unavailable                                           |
| Selected PR checks | `GET signals/reports/{id}/pr_checks/?pull_request_id={canonicalPrId}`                                                            | No id or failed/missing checks stay unavailable; focused foreground polling at 30 seconds |
| Current run        | `GET tasks/{taskId}/` then `GET .../runs/{runId}/stream/` (SSE)                                                                  | Bounded reconnects and focused foreground task polling, including later resumes           |
| New chat           | `POST tasks/` then `POST tasks/{id}/run/` (`mode: interactive`)                                                                  | A refused run deletes the new task                                                        |
| Follow-up          | `POST tasks/{id}/runs/{run}/command/` (`set_config_option` for changed options, then `user_message`)                             | `POST tasks/{id}/run/` with `resume_from_run_id` when the run ended                       |
| Chats list         | `GET tasks/?created_by={user id}&ordering=-last_activity_at&basic=true&limit=30`                                                 | A 403 or 404 means no sessions                                                            |
| Chat thread        | `GET tasks/{id}/` then `GET tasks/{id}/runs/{run}/logs/` for an ended run, or `GET tasks/{id}/runs/{run}/stream/` for a live one | A failed load shows Try again; demo sessions come from `src/demo/sessionThreads.ts`       |
| Reviewers          | `GET signals/reports/available_reviewers/`, `PUT signals/reports/{id}/reviewers/`                                                | none                                                                                      |
| Priority           | `POST signals/reports/{id}/artefacts/` (`priority_judgment`)                                                                     | none                                                                                      |
| Snooze             | `POST signals/reports/{id}/state/` for "until more signals"; on-device store for times                                           | none                                                                                      |
| Read state         | `POST signals/reports/read_state/`                                                                                               | none                                                                                      |
| Push               | `POST /api/users/@me/push_tokens/`                                                                                               | unavailable on web and Expo Go                                                            |

Details per domain: [DATA.md](DATA.md), [HANDOFF.md](HANDOFF.md), [CHAT.md](CHAT.md),
[AUTH.md](AUTH.md), [PUSH.md](PUSH.md).

## Hook surface

| Hook                                                                     | File                                        | Returns                                                                                                                                                                                                                                                                      |
| ------------------------------------------------------------------------ | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `useInboxItems()`                                                        | `features/inbox/hooks.ts`                   | `InboxQueryState`: `QueryState<InboxItem[]>` plus `hasMore`, `isLoadingMore`, `loadMoreFailed`, `loadMore`                                                                                                                                                                   |
| `useMarkReadAction(id)`, `useMarkReadOnOpen(id)`                         | `features/inbox/hooks.ts`                   | `AsyncAction<[]>`, `void`                                                                                                                                                                                                                                                    |
| `usePrefetchReports(items)`                                              | `features/inbox/usePrefetchReports.ts`      | `{ onViewableItemsChanged, viewabilityConfig }` for the inbox `FlatList`                                                                                                                                                                                                     |
| `useReport(id)`                                                          | `features/report/hooks.ts`                  | `QueryState<ReportView>`                                                                                                                                                                                                                                                     |
| `useReportWithLiveRun(id)`                                               | `features/handoff/useReportWithLiveRun.ts`  | `QueryState<ReportView>` with the live run merged in                                                                                                                                                                                                                         |
| `useReportActions(id)`                                                   | `features/report/hooks.ts`                  | `ReportActions` (`handOff`, `answerDecision`, `undoDecision`, `snooze`, `setReviewers`, `setPriority`, `markRead`, `pending`)                                                                                                                                                |
| `useReportNeighbors(inbox, id)`                                          | `features/report/hooks.ts`                  | `{ previousId, nextId }`, wrapping only when every page is loaded; loads the next page on the last loaded report                                                                                                                                                             |
| `useMetricSeries(data)`, `useMetricAggregate(data)`                      | `features/report/metrics/hooks.ts`          | `QueryState<MetricSeries>`, `QueryState<number>` from the query endpoint or fixture data                                                                                                                                                                                     |
| `useMetricValue(metric)`                                                 | `features/report/metrics/useMetricValue.ts` | `MetricValueState`: the live value, else the snapshot with its measured time                                                                                                                                                                                                 |
| `useChartPoints(data, fallback?)`                                        | `features/report/metrics/useChartPoints.ts` | `{ points, isLoading, isError }` for `MetricChart`, from live buckets or the snapshot series                                                                                                                                                                                 |
| `useHandoffActions(id)`, `useDecisionAnswer(id)`, `useHandoffNotice(id)` | `features/handoff/hooks.ts`                 | actions, the device-side answer, the footer error line                                                                                                                                                                                                                       |
| `usePullRequestChecks(reportId?, pullRequestId?, enabled?)`              | `features/handoff/usePullRequestChecks.ts`  | status, local `observedAt`, `isRefreshing`                                                                                                                                                                                                                                   |
| `useTaskRun(reportId, target, enabled, onRefresh?, onTaskSnapshot?)`     | `features/handoff/useTaskRun.ts`            | `void`; follows the current run into the report store, with scoped connection state                                                                                                                                                                                          |
| `useSnoozeAction(id)`, `useSnoozeEntries()`                              | `features/snooze/hooks.ts`                  | `AsyncAction<[SnoozeChoice]>`, active snoozes                                                                                                                                                                                                                                |
| `useAvailableReviewers(query)`                                           | `features/reviewers/hooks.ts`               | `QueryState<Person[]>`                                                                                                                                                                                                                                                       |
| `useSetReviewersAction(id)`                                              | `features/reviewers/hooks.ts`               | `AsyncAction<[string[]]>` (full replace)                                                                                                                                                                                                                                     |
| `useSetPriorityAction(id)`                                               | `features/priority/hooks.ts`                | `AsyncAction<[ReportPriority]>`                                                                                                                                                                                                                                              |
| `useSession({ taskId?, runId? })`                                        | `features/chat/session/useSession.ts`       | `Session`: `taskId`, `runId`, `title`, `items`, `invocations`, `phase`, `history`, `decision`, `runConfig`, `notice`, `unsentText`, `isSending`, `isStopping`, `start(text, context, options?)`, `send(text, context, options?)`, `stop`, `answer`, `reset`, `reloadHistory` |
| `useChatList()`                                                          | `features/chats/hooks.ts`                   | `QueryState<ChatListItem[]>`                                                                                                                                                                                                                                                 |
| `useArchiveChat()`                                                       | `features/chats/hooks.ts`                   | `ChatArchiveActions` (`archive`, `restore`), both optimistic on the cached list                                                                                                                                                                                              |
| `usePushRegistration()`, `useNotificationRouting()`                      | `features/notifications/`                   | registers the device, routes taps                                                                                                                                                                                                                                            |
| `useViewer()`                                                            | `auth/useViewer.ts`                         | `{ name, projectName }`                                                                                                                                                                                                                                                      |

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
  hooks. The app's shared screen chrome is the exception: `src/features/views/screen/*`, `ViewsToast` and
  `ViewsReauthState` may be imported by other features. Fixtures reach screens only through hooks. Screens import the `useDemoMode` store
  directly only to turn demo mode on or off.
- `src/demo` imports `src/model` and nothing from `features`.
