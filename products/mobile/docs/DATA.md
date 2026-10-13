# Inbox and report data

How the inbox and the report screen get their data in live mode, and how the adapters in `src/model/adapters/` turn API responses into the view models in `src/model/types.ts`.
Demo mode never reaches any of this: every hook keeps its demo branch.

## Endpoints

All paths are project scoped (`/api/projects/{project_id}/...`) and go through `apiJson` in `src/api/client.ts`.
Fetchers live in `src/api/today.ts`, `src/api/reports.ts` and `src/api/query.ts`, typed by hand with only the fields the app reads.
Each interface names the serializer it mirrors.

| Use | Request | Serializer | Scope |
| --- | --- | --- | --- |
| Inbox list | `GET today/briefing/?timezone=<IANA>` | `BriefingSerializer` (today) | `today:read` |
| Inbox fallback | `GET signals/reports/?scope=for_me&status=ready,pending_input,failed&sort=priority&limit=50` | `SignalReportListSerializer` | `task:read` |
| Read states of the list | `POST signals/reports/read_state/` `{report_ids}` (100 ids per call) | `ReportReadStateResponseSerializer` | `task:read` |
| Report | `GET signals/reports/{id}/` | `SignalReportSerializer` | `task:read` |
| Work log | `GET signals/reports/{id}/artefacts/?limit=100` (newest first) | `SignalReportArtefactSerializer` | `task:read` |
| Signals | `GET signals/reports/{id}/signals/` | `ReportSignalsResponseSerializer` | `task:read` |
| Today page | `GET today/reports/{id}/page/` | `ReportPageSerializer` | `today:read` + `task:read` |
| Current task | `GET tasks/{task_id}/` (`getTask` in `src/api/tasks.ts`) | `TaskSerializer` | `task:read` |
| Mark read | `POST signals/reports/read_state/` `{report_ids: [id], read: true}` | same | `task:read` |
| Signal snooze | `POST signals/reports/{id}/state/` `{state: 'potential', snooze_for: 5}` | `SignalReportSerializer` | `task:write` |
| Set reviewers | `PUT signals/reports/{id}/reviewers/` `{content: [{user_uuid} or {github_login}]}` | `SignalReportSuggestedReviewersArtefactSerializer` | `task:write` |
| Set priority | `POST signals/reports/{id}/artefacts/` `{artefact_type: 'priority_judgment', content: {priority, explanation}}` | `SignalReportArtefactLogCreateSerializer`, content `PriorityAssessment` | `task:write` |
| Reviewer search | `GET signals/reports/available_reviewers/?query=` | `{uuid: {name, email}}` | `task:read` |
| Metric and chart data | `POST query/` `{query: <TrendsQuery>, client_query_id, refresh: 'blocking'}` | `TrendsQueryResponse` | `query:read` |
| Running query | `GET query/{query_id}/` | `QueryStatusResponse` | `query:read` |

Query keys (`reportKeys` in `src/api/reports.ts`) carry the host and project id, so a project switch never shows another project's cache.
`useProjectScope()` reads both from the auth store and returns null until the session is signed in.

## The Today fallback

`useInboxItems()` asks for the briefing first.
It uses the signals reports list instead when:

- the briefing request fails before any briefing loaded, including a 404 (flag off, no AI data processing approval, no AI credits) or a 403 (the token lacks `today:read`), which are not retried;
- the briefing has no report items yet and is not `ready` (`collecting` on the first open of the day, or `failed`).

The list holds the reports that name the user as a reviewer and are ready, waiting for input or failed, highest priority first.
It does not use `view=needs_decision`, because that view drops a report once it has an implementation PR, and the reviewer of that PR still needs the report.
`scope=for_me` matches the user in the report's current reviewer set, so a report the user claimed without being a reviewer is not in the list.

While the briefing is `collecting` or `writing`, the hook polls it every 5 seconds for at most 132 polls, like the web.
A failed poll keeps the briefing that is already on screen.
The Today page on the report screen follows the same rule: a 404 or 403 means no page, and the evidence comes from the signals.

Pull to refresh refetches the briefing (or the fallback list) and the read states.
It never calls `today/briefing/refresh/`, which writes a new briefing with the language model.

## Inbox rows

`inboxFromBriefing(briefing)`:

- keeps items in the `report` group with a `report:<uuid>` key and a live `report`; dashboards, tickets and deleted reports are dropped;
- sorts by `rank`; `id` is the item key, `reportId` the uuid;
- `sourceProduct` is `source_product` (unknown values become `other`), else the Today `source` (`support` is `conversations`, `self_driving` is `signals_scout`);
- `state`, `reason` and `rank` come from the item; `updatedAt` from `report.updated_at`;
- `needsInput` is `reason === 'waiting_for_you'`, which the server gives for `pending_input` reports that name the user;
- no `agent`: the briefing does not say who claimed a report.

`inboxFromReports(list)`:

- `needsInput` is `status === 'pending_input'`; `agent` is the PostHog badge when `assignee.kind` is `task` or `agent`;
- `state` is `done` for resolved, `dismissed` for suppressed or deleted, else `open`;
- `sourceProduct` is the first source that is not `signals_scout` or `signals_check`, else the first.

Accent for both: `resolved` when the report is resolved, suppressed or deleted (or the Today item is done or dismissed); `alert` when any source is an error source or any source is not feedback; `opportunity` when every source is feedback (support tickets, feedback boards, app reviews) or the report is scout-only.

The hook then sets `read` from the read-state map and applies local snoozes (below).

## Report view

`useReport(id)` runs the report, work log, Today page and signals requests in parallel, then `GET tasks/{id}/` once it knows the task.
The screen waits for the report and the work log, for the Today page to answer, and for the signals only when there is no page.
The task fills in when it arrives.
A failed background refetch keeps the cached report on screen.

**Prefetch and refresh.**
The inbox prefetches the report detail, work log and Today page of the first 10 rows, and of the rows that scroll into view plus 5 ahead.
It also prefetches the signals of a report when the Today page answers 404 or 403, because the signals are the evidence then.
It works on two reports at a time and skips done and dismissed rows.
It uses a 5 minute stale time, so a refresh or a scroll does not fetch a report again within 5 minutes of its prefetch.
A report the cache dropped while the app was idle is fetched again when its row comes into view.
The screen and the prefetcher share the query factories in `src/features/report/queries.ts`, so they read and write the same cache entries.
The report screen renders the cached copy at once and refetches it on every open, and on Prev/Next.
A failed background refetch keeps the cached copy.
`mobile_report_opened` carries `from_cache`, true when the report detail was in the cache when the screen opened.

`reportView(...)` rules:

- **Headline.** The title, split when it starts with a number token (`3,721`, `+2.3s`, `0 of 860`, `$184k`, `12%`). When the title has no number, the first sentence of the Today `lead` is used if it starts with one and is at most 120 characters. Otherwise the whole title is `rest`.
- **Lede.** The Today `impact_sentence`, else `summary_lead`, else the first sentence of the summary, as plain text. A lede that starts with the headline sentence loses that sentence.
- **Accent and source.** As for inbox rows, from `source_products` and `status`.
- **Evidence from the Today page.** The first error signal is a `trace`: `error` is its `headline`, frames come from the quiet `preview.block` lines (`file.ts:12  fn`), at most 4, and `footer` is its `meta` when set. Feedback signals become up to 3 `quotes` (`lead`, attributed "{source} · {meta}"). The first signal with a `recording` is the `replay`: meta "at {offset} · {headline}", url `{host}/project/{id}/replay/{session_id}?t={seek_seconds}`, count the larger of the recordings on the page and the distinct `session_id`s in the signals.
- **Evidence from signals** (no page). The first error signal is a `trace` with its first line and the frames of its fenced stack (`fn in path line N`, closest to the error first). Feedback signals become quotes ("Ticket #N" when `extra.ticket_number` is set). The first signal with `extra.session_id` is the `replay`, without a seek time.
- **Since.** `created_at` as activity time ("Mon 7:21 AM", "Today 9:04 AM", "Just now"). The byline under the headline reads it as "Since …".
- **Owner.** `{ kind: 'user', name }` for a user claim; `{ kind: 'agent', name }` with "PostHog" for a task or system claim, or the MCP client ("Claude Code") for an external agent claim; `{ kind: 'none' }` when unclaimed. The owner chip under the byline shows it.
- **Facts**, the rows the byline and chips do not show. The adapter emits only Impact, dropped when it has no source: the primary metric's value and title ("612 affected users", or "612 users" with the title under it when the metric has its own unit) and its caption; else the first Today impact number.
  The byline takes the source from `sourceProduct` and `sourceLabel`, so the facts carry no Source row.
- **Observation, supporting metrics and charts.** See [Metrics and charts](#metrics-and-charts).
- **Activity**, oldest first, starting with "PostHog created the report" at `created_at`:
  - `work_claim`: "{name} handed off to **PostHog**" for a task claim when the task's creator is known, else "PostHog claimed the report"; "{actor} claimed the report" for users and agents.
  - `task_run` of type `implementation`: "PostHog started working". Other run types are left out.
  - `pull_request`: "PostHog opened **PR #N**", or "{actor} linked **PR #N**" when a person or agent attached it.
  - `suggested_reviewers`: "{actor} changed reviewers to **A, B**" or "{actor} removed the reviewers"; "PostHog suggested **A, B** as reviewers" for pipeline writes.
  - `dismissal`, `note`, `title_change`, `summary_change`: one sentence each. Every other artefact type is left out.
  - The actor is the `created_by` user, the MCP client name for agent writes, else "PostHog". Agent writes carry `via PostHog MCP`.
- **Work.** `work_state`, the assignee, and the pull request the server calls the implementation PR (else the first). A PR in state `unknown` counts as open, as the server does.
- **Task.** The claim's task when a task owns the report, else the newest `implementation` task run. `runId`, `status` and `stage` come from the task's `latest_run`. The hand-off feature streams it from there.
- **Reviewers.** The newest `suggested_reviewers` artefact, entries with a PostHog user only.
- **Other fields.** `status` and `priority` when they are known values, `summary`, `webUrl` (`reportWebUrl()`: `{host}/project/{id}/inbox/reports/{report_id}`, also used for chat context), `canAct` (the web's `isActionCapableReport`: `ready` or `pending_input`, not already addressed, not `not_actionable`, no pull request), up to 3 `suggestedPrompts`, and the fixed `contextNote`. `useReport` adds `prompt`, the hand-off feature's implementation prompt for `webUrl`.

## Metrics and charts

The report detail carries `metrics` (`ReportMetricSerializer`) and `charts` (`ReportChartSerializer`).
The rules port the web inbox (`products/signals/frontend/inbox/utils/reportMetrics.ts`, `reportChartQuery.ts`, `chartOpenTarget.ts`).

A metric has a saved snapshot (`value`, `value_at`, up to 14 undated `series` points) and a live `query`, an `InsightVizNode` with a `TrendsQuery` source.
`value: null` means no snapshot for this viewer, never zero.
`query` is absent on list responses and null when access rules redact it.

`metricView(metric, scope)` in `src/model/adapters/metric.ts` builds a `MetricView`:

- **Role.** The single `primary` metric becomes `ReportView.observation`. Every other metric is a `supportingMetrics` tile, in the order the report lists them.
- **Chart kind.** `count` is a bar chart. `currency` is a bar chart only when every series has `math: 'sum'`. Everything else is a line, because bars invite the reader to add up a rate.
- **Data.** With a trends query, `data` is `{kind: 'query', seriesQuery, aggregateQuery}`. Both are copies of the `TrendsQuery` source. `seriesQuery` sets `trendsFilter.display` to `ActionsBar` or `ActionsLineGraph`, turns `showPercentStackView` off and drops `hiddenLegendIndexes`. `aggregateQuery` sets `display: 'BoldNumber'`, so the server totals the window: summing buckets would count a returning user once per bucket. Without a query, `data` is `{kind: 'none'}` and the snapshot is all there is.
- **Window label.** From the relative `dateRange.date_from`, as the web words it: `-14d` is "Last 14 days", `-24h` "Last 24 hours", `-1m` "Last month". Anything else is "Current window".
- **Filter count.** The property filters on every series plus the query's own `properties`. Groups count their leaf filters.
- **Interval.** `source.interval` (`hour`, `day`, `week`, `month`), `day` when unset.
- **Open link.** `{host}/project/{id}/insights/new#q=<query>` with the embed flags (`full`, `embedded`, `show*`) removed. A link over 8,000 characters is dropped, because nginx refuses a longer request line.

`reportChartView(chart, scope)` builds a `ReportChartView`.
The app draws a chart only when it is an `InsightVizNode` with a `TrendsQuery` source, one series, no breakdown, and a display that draws buckets over time (`ActionsLineGraph`, `ActionsLineGraphCumulative`, `ActionsAreaGraph`, the three bar displays, or none).
Such a chart gets `data` (its own display kept, the same clean-up as a metric) and a format from `aggregationAxisFormat`.
Any other chart (SQL, saved insight, pie, number, table, breakdown) has no `data` and stays in the list with its title and open link:
`/sql?open_query=` for a `DataVisualizationNode` with a `HogQLQuery` source, `/insights/{shortId}` for a `SavedInsightNode`.

### Running a query

`runQuery(query)` in `src/api/query.ts` posts the `TrendsQuery` to the plain `query/` route.
The server also routes `query/{Kind}/`, which only checks that the path matches the body.
With `refresh: 'blocking'` the server usually answers inline.
When it answers with a `query_status` that is not complete, the app polls `GET query/{id}/` every second for at most 30 seconds, and stops when the request is aborted.

`useMetricSeries(data, enabled?)` and `useMetricAggregate(data, enabled?)` in `src/features/report/metrics/hooks.ts` return a `QueryState`:

- `static` (demo fixtures) succeeds at once with no request; `none` or an undefined `data` succeeds with `data` undefined.
- `query` runs in live mode only. The cache key is the host, the project and the query with its keys sorted. A result stays fresh for 15 minutes, as the web treats a snapshot. A failure is retried once, except a 403 or 404.
- The series is the first result's `days` zipped with its `data`, cut to the shorter list, with `NaN` for a bucket that has no number. The aggregate is the first result's `aggregated_value`. A response with neither succeeds with `data` undefined, and the screen falls back to the snapshot.
- `enabled: false` leaves a query idle: not loading, no data, no error.

The query endpoint needs the `query:read` scope. Without it the request answers 403 and the screen shows the snapshot.

### Showing a metric

`metricValueState` in `src/features/report/metrics/metricValue.ts` picks the value an observation or a tile shows:

- A live aggregate wins, also while it refetches.
- Without one, the snapshot value shows with "Measured {time ago}" from `value_at`. This covers a redacted metric (`data: none`), a query that returned no value, and a query still loading.
- When the live query failed, the snapshot shows with "Couldn't refresh this metric. Showing the latest saved value." A tile says "Couldn't refresh".
- With no snapshot, a loading query shows a spinner, and a settled one shows "Not available". After a failure the observation offers Try again.

`useChartPoints` in `src/features/report/metrics/useChartPoints.ts` feeds the chart:

- Live buckets win. A bucket label without an offset (`2026-10-13`, `2026-10-13 14:00:00`) is read as local wall-clock time, because `Date.parse` reads a bare date as UTC midnight, which is the day before west of UTC.
- Without live buckets, the observation draws the snapshot's undated series. The points are one interval apart and the last one sits at `value_at`, or at the current time when that is unknown.
- While the live query loads, nothing is drawn, so the chart does not draw the snapshot and then redraw.
- With no points at all, the observation leaves the chart out. A drawable chart in the Charts section shows a spinner while it loads, then "No data in this window." or an error line.

## Actions

- **Mark read.** `useMarkReadOnOpen` posts `read: true` each time a report opens and on Prev/Next, one request per report even when the previous one is still in flight. The cached read-state map is set to read first and refetched if the request fails.
- **Reviewers.** The sheet sends the full list of uuids. Reviewers that exist only as a GitHub login on the newest artefact are sent back as `{github_login}`, because the PUT replaces the whole list. The PUT takes at most 10 entries, so the sheet stops adding people when the selection plus the GitHub-only reviewers reaches 10. The hook waits for the work log to refetch so the sheet closes on the new list. A failed save keeps the sheet open with the error.
- **Reviewer search.** Debounced by 250 ms, cached for 5 minutes, and the previous results stay on screen while the next search loads.

## Snooze

Two kinds, both remembered in `useSnoozeStore` (zustand, persisted in AsyncStorage as `posthog-mobile-snoozes`), keyed by `{host}|{project id}|{report id}`:

- **Until more signals arrive** posts `state: potential` with `snooze_for: 5`. The server hides the report from the signals list until its `signal_count` reaches `signals_at_run`. The Today briefing keeps listing it, so the device stores the threshold and labels the row "Snoozed until more signals" until the row's signal count reaches it, or for at most 14 days.
- **Time snoozes** stay on the device. The row reads "Snoozed until 3:31 PM", "Snoozed until tomorrow" or "Snoozed until Oct 16", computed against the current time, and the entry ends by itself at its time. A local notification is scheduled for that time (`expo-notifications`, title the report title, body "Snoozed report is back", data `{type: 'report', report_id, project_id}`). The reminder is scheduled only when notifications are already allowed; the app does not ask for permission here, and without it the snooze still works. Web schedules no reminder.

Snoozed rows stay in the list, muted, in their place. Rows that are done or dismissed keep their state.
Opening a report ends its time snooze and cancels the reminder. A new snooze on the same report replaces the old one and its reminder.

Limits:

- Time snoozes do not sync. Another device or the web app still shows the report as open.
- Reinstalling the app or clearing its storage forgets every snooze. Scheduled reminders survive only as long as the OS keeps them.
- Signing out, or a session that expires, clears every snooze on the device and cancels the reminders.
- A signal snooze made on the web is not labeled in the app's Today list, because the briefing does not carry report status.
