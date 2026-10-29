# Inbox and report data

How the inbox and the report screen get their data in live mode, and how the adapters in `src/model/adapters/` turn API responses into the view models in `src/model/types.ts`.
Demo mode never reaches any of this: every hook keeps its demo branch.

## Endpoints

All paths are project scoped (`/api/projects/{project_id}/...`) and go through `apiJson` in `src/api/client.ts`.
Fetchers live in `src/api/today.ts`, `src/api/reports.ts` and `src/api/query.ts`, typed by hand with only the fields the app reads.
Each interface names the serializer it mirrors.

| Use                     | Request                                                                                                         | Serializer                                                              | Scope                      |
| ----------------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------- |
| Inbox list              | `GET signals/reports/?view=for_you&sort=priority&limit=20&offset=<n>`                                           | Paginated `SignalReportListSerializer`                                  | `task:read`                |
| Read states of the list | `POST signals/reports/read_state/` `{report_ids}` (one call per page)                                           | `ReportReadStateResponseSerializer`                                     | `task:read`                |
| Report                  | `GET signals/reports/{id}/`                                                                                     | `SignalReportSerializer`                                                | `task:read`                |
| Work log                | `GET signals/reports/{id}/artefacts/?limit=100` (newest first)                                                  | `SignalReportArtefactSerializer`                                        | `task:read`                |
| Signals                 | `GET signals/reports/{id}/signals/`                                                                             | `ReportSignalsResponseSerializer`                                       | `task:read`                |
| Today page              | `GET today/reports/{id}/page/`                                                                                  | `ReportPageSerializer`                                                  | `today:read` + `task:read` |
| Current task            | `GET tasks/{task_id}/` (`getTask` in `src/api/tasks.ts`)                                                        | `TaskSerializer`                                                        | `task:read`                |
| Mark read               | `POST signals/reports/read_state/` `{report_ids: [id], read: true}`                                             | same                                                                    | `task:read`                |
| Signal snooze           | `POST signals/reports/{id}/state/` `{state: 'potential', snooze_for: 5}`                                        | `SignalReportSerializer`                                                | `task:write`               |
| Set reviewers           | `PUT signals/reports/{id}/reviewers/` `{content: [{user_uuid} or {github_login}]}`                              | `SignalReportSuggestedReviewersArtefactSerializer`                      | `task:write`               |
| Set priority            | `POST signals/reports/{id}/artefacts/` `{artefact_type: 'priority_judgment', content: {priority, explanation}}` | `SignalReportArtefactLogCreateSerializer`, content `PriorityAssessment` | `task:write`               |
| Reviewer search         | `GET signals/reports/available_reviewers/?query=`                                                               | `{uuid: {name, email}}`                                                 | `task:read`                |
| Metric and chart data   | `POST query/` `{query: <TrendsQuery>, client_query_id, refresh: 'blocking'}`                                    | `TrendsQueryResponse`                                                   | `query:read`               |
| Running query           | `GET query/{query_id}/`                                                                                         | `QueryStatusResponse`                                                   | `query:read`               |

Query keys (`reportKeys` in `src/api/reports.ts`) carry the host and project id, so a project switch never shows another project's cache.
`useProjectScope()` reads both from the auth store and returns null until the session is signed in.

## The inbox list

`useInboxItems()` reads `signals/reports/?view=for_you&sort=priority` one page of 20 reports at a time, with `useInfiniteQuery`.
The `for_you` view holds only the open, actionable reports that wait for the user's input, that the user claimed, or that name the user as a reviewer. It excludes unowned P0 reports.
The priority sort matches the Today briefing: priority first, then status, then most recently updated.

The list asks for the next page when the user scrolls within half a screen of its end, and while the response has a `next` link.
Each page orders the reports again, so a report that moved can come back on a later page; `reportsFromPages()` keeps its first place.
A next page that fails shows "Couldn't load more reports." and "Try again" under the list.
`mobile_inbox_page_requested` carries the page number of each next-page request.
`mobile_inbox_error_shown` carries `during` (`load` for the full-screen error, `next_page` for the footer) and, for `load`, `kind` (`scope`, `auth`, `forbidden`, `not_found`, `server`, `network`, `unknown`).
`mobile_inbox_empty_shown` is sent each time the list shows "Nothing needs you right now".

**Filter and sort.**
`useInboxItems({ filters })` filters and sorts on the device over the reports returned by the `for_you` view.
`applyInboxFilters()` (`src/features/inbox/filters.ts`) keeps the reports created inside the window and the reports with any source in the selected groups, then sorts.
Source groups follow the mobile source vocabulary in `src/model/sources.ts`: `error` holds every error source, `support` every feedback source, `session_replay` also holds `replay_vision`, and `report` holds `signals_scout`, `signals_check`, unknown sources and reports with no source.
`recommended` keeps the server ranking. `model_score` sorts by `ranking.scores.pr_merged`, highest first, with unscored reports last; the server sends `ranking` to staff only, and the option shows only behind the `mobile-inbox-model-score-sort` flag.
While any filter or sort is not the default, the hook requests the next page until the server sends no `next`, so a sort covers the whole set and a filter does not hide matches on pages not yet loaded. The footer spinner shows until the last page arrives. A failed page stops this until "Try again".
The choice persists on the device (`inboxFiltersStore.ts`). `matchedCount` and `totalCount` tell "No reports match these filters" from an empty inbox.
`mobile_inbox_filters_opened` is sent when the sheet opens. `mobile_inbox_sort_changed` carries `sort`, `mobile_inbox_created_window_changed` carries `window`, and `mobile_inbox_source_filter_changed` carries `source`, `selected` and `count` (the selected groups after the change). `mobile_inbox_filters_cleared` is sent for "Clear" and "Clear filters", and `mobile_inbox_filtered_empty_shown` each time the list shows "No reports match these filters".

Read states are fetched once per page, so a new page does not ask again for the pages above it.

Pull to refresh is the only manual refresh. It keeps only the first page and refetches it and the read states.
Refetching every loaded page would rank the whole list once per page.
`mobile_inbox_refreshed` carries `trigger`: `pull` or `retry` (the error screen's "Try again").
A change made on the report screen (resolve, dismiss, reviewers, priority, hand-off) refetches every loaded page in the background.

## Inbox rows

`inboxFromReports(reports)`:

- `needsInput` is `status === 'pending_input'`; `agent` is the PostHog badge when `assignee.kind` is `task` or `agent`;
- `state` is `done` for resolved, `dismissed` for suppressed or deleted, else `open`;
- `sourceProduct` is the first source that is not `signals_scout` or `signals_check`, else the first;
- `sources` and `createdAt` carry `source_products` and `created_at` for the filters, and `modelScore` is `ranking.scores.pr_merged`, or null.

Accent: `resolved` when the report is resolved, suppressed or deleted; `alert` when any source is an error source or any source is not feedback; `opportunity` when every source is feedback (support tickets, feedback boards, app reviews) or the report is scout-only.

The hook then sets `read` from the read-state map and applies local snoozes (below).

## Report view

`useReport(id)` runs the report, work log, Today page and signals requests in parallel, then `GET tasks/{id}/` once it knows the task.
The screen waits for the report and the work log, for the Today page to answer, and for the signals only when there is no page.
The task fills in when it arrives.
A failed background refetch keeps the cached report on screen.

**Prefetch and refresh.**
The inbox prefetches the report detail, work log and Today page of the first 40 rows (the first two pages, as they load), and of the rows that scroll into view plus 5 ahead.
These are the requests the report screen waits for before its first render; the task and the metric queries load after it opens.
It also prefetches the signals of a report when the Today page answers 404 or 403, because the signals are the evidence then.
It works on two reports at a time and skips done and dismissed rows.
It uses a 5 minute stale time, so a refresh or a scroll does not fetch a report again within 5 minutes of its prefetch.
A report the cache dropped while the app was idle is fetched again when its row comes into view.
The screen and the prefetcher share the query factories in `src/features/report/queries.ts`, so they read and write the same cache entries.
The report screen renders the cached copy at once and refetches it on every open, and on Prev/Next.
A failed background refetch keeps the cached copy.
`mobile_report_opened` carries `from_cache`, true when the report detail was in the cache when the screen opened.
It also carries `from`, read from the route's `from` param: `inbox` (a row tap), `push` (a notification), `adjacent` (Prev/Next) or `deep_link` (no param or an unknown one).
`mobile_report_load_failed` is sent when the screen shows "Couldn't load this report", with `report_id` and `kind` as for the inbox error, or with `kind: invalid_id` and no id for "Couldn't find this report".
`mobile_report_read` is sent once when the report body unmounts (Back or Prev/Next), with `report_id`, `dwell_s` (whole seconds the screen had focus with the app in the foreground) and `scrolled_to_end` (the deepest scroll came within 160 px of the content end, or the content fit on screen).
`mobile_report_replay_opened` carries `report_id` and `replay_count` when "See the moment" opens the session screen (the recording on the web in demo mode).

**Full report.** "Read the full report" under the lede opens `/report/{id}/details` when the report has a summary or at least one signal.
The screen reads `useReport(id)`, so it shares the report screen's cache and does not poll.
The signals can arrive after the first render when a Today page exists, because the report screen does not wait for them then; the Signals section appears when they land.
`mobile_report_details_opened` is sent once per open, with `report_id`, `has_summary` and `signal_count`.
`mobile_report_details_link_opened` carries `report_id` and `target`: `web` (Open in PostHog), `replay` (a signal's Watch session) or `link` (a link in the summary or a signal).
`mobile_report_details_read` has the same properties as `mobile_report_read` and is sent when the full report unmounts.
The report screen's dwell time pauses while the full report is on top, because that screen loses focus.

`reportView(...)` rules:

- **Headline.** The title, split when it starts with a number token (`3,721`, `+2.3s`, `0 of 860`, `$184k`, `12%`). When the title has no number, the first sentence of the Today `lead` is used if it starts with one and is at most 120 characters. Otherwise the whole title is `rest`.
- **Lede.** The Today `impact_sentence`, else `summary_lead`, else the first sentence of the summary, as plain text. A lede that starts with the headline sentence loses that sentence.
- **Accent and source.** As for inbox rows, from `source_products` and `status`.
- **Evidence from the Today page.** The first error signal is a `trace`: `error` is its `headline`, frames come from the quiet `preview.block` lines (`file.ts:12  fn`), at most 4, and `footer` is its `meta` when set. Feedback signals become up to 3 `quotes` (`lead`, attributed "{source} · {meta}"). The first signal with a `recording` is the `replay`: meta "at {offset} · {headline}", url `{host}/project/{id}/replay/{session_id}?t={seek_seconds}`, count the larger of the recordings on the page and the distinct `session_id`s in the signals.
- **Evidence from signals** (no page). The first error signal is a `trace` with its first line and the frames of its fenced stack (`fn in path line N`, closest to the error first). Feedback signals become quotes ("Ticket #N" when `extra.ticket_number` is set). The first signal with `extra.session_id` is the `replay`, without a seek time.
- **Signals.** Every signal from the signals endpoint, newest first as the API returns them, also when the Today page supplies the evidence. Each has its source (unknown sources map to `other`), the trimmed `content`, `timestamp`, the `extra.session_id` with its replay URL (`{host}/project/{id}/replay/{session_id}`, no seek time), and `extra.ticket_number` when it is a number. The full report shows them all, untruncated.
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

- **Sheets.** `mobile_report_sheet_opened` carries `sheet` (`handoff`, `resolve`, `dismiss`, `assignee`, `priority`, `decision`, `pull_request_picker`), `from` (`action_bar`, `chip` for the owner and priority chips, `inbox_menu`) and `report_id`. `mobile_report_sheet_dismissed` carries the same properties and is sent only when the sheet closes without its completion: a successful resolve, dismiss, priority or reviewer save, a hand-off attempt, an external agent opened or a prompt copied, a picked pull request, or an answer sent. The completion events below carry `report_id`.
- **Outcomes.** `mobile_report_resolved` and `mobile_report_dismissed` carry `reason` and `has_note`, never the note. `mobile_report_priority_changed` carries `priority`. `mobile_reviewers_changed` carries `count`. `mobile_inbox_report_menu_action` stays the record of which row menu choice was picked; sheets opened from it also send `mobile_report_sheet_opened` with `from: inbox_menu`.
- **Read state.** Only a fresh, successful server response of `false` marks a row unread. Pending, missing and failed lookups stay quiet. The inbox refreshes read state every 30 seconds while focused in the foreground, and when it becomes active again. Rows show an unread dot; the menu counts unread reports in the loaded pages.
- **Mark read.** `useMarkReadOnOpen` posts `read: true` after the report loads, including on Prev/Next. Separate reports can post concurrently. The cached state updates at once; a failed write restores that report's previous state without replacing other reports' updates. In-flight lookups cannot overwrite a pending read, and account or project changes invalidate the pending operation.
  `mobile_report_marked_read` and `mobile_report_marked_unread` are sent after the server accepts the write, with `trigger`: `open` for this automatic mark, `manual` for a swipe or a row menu choice.
- **Reviewers.** The sheet sends the full list of uuids. Reviewers that exist only as a GitHub login on the newest artefact are sent back as `{github_login}`, because the PUT replaces the whole list. The PUT takes at most 10 entries, so the sheet stops adding people when the selection plus the GitHub-only reviewers reaches 10. The hook waits for the work log to refetch so the sheet closes on the new list. A failed save keeps the sheet open with the error.
- **Reviewer search.** Debounced by 250 ms, cached for 5 minutes, and the previous results stay on screen while the next search loads.

## Snooze

Two kinds, both remembered in `useSnoozeStore` (zustand, persisted in AsyncStorage as `posthog-mobile-snoozes`), keyed by `{host}|{project id}|{report id}`:

- **Until more signals arrive** posts `state: potential` with `snooze_for: 5`. The server hides the report from the inbox list until its `signal_count` reaches `signals_at_run`. The device stores the threshold and labels the row "Snoozed until more signals" until the list refetches without the report, the row's signal count reaches the threshold, or 14 days pass.
- **Time snoozes** stay on the device. The row reads "Snoozed until 3:31 PM", "Snoozed until tomorrow" or "Snoozed until Oct 16", computed against the current time, and the entry ends by itself at its time. A local notification is scheduled for that time (`expo-notifications`, title the report title, body "Snoozed report is back", data `{type: 'report', report_id, project_id}`). The reminder is scheduled only when notifications are already allowed; the app does not ask for permission here, and without it the snooze still works. Web schedules no reminder.

Snoozed rows stay in the list, muted, in their place. Rows that are done or dismissed keep their state.
Opening a report ends its time snooze and cancels the reminder. A new snooze on the same report replaces the old one and its reminder.

Limits:

- Time snoozes do not sync. Another device or the web app still shows the report as open.
- Reinstalling the app or clearing its storage forgets every snooze. Scheduled reminders survive only as long as the OS keeps them.
- Signing out, or a session that expires, clears every snooze on the device and cancels the reminders.
