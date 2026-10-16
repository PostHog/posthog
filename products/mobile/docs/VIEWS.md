# Views

The Views tab shows the dashboards, insights and web analytics a person checks on the phone.
This file covers the data layer under `src/features/views/`, `src/api/` and `src/model/adapters/`.
Screens render the view models in `src/model/views.ts` and never call the API themselves.

## Requests

| Use | Request | Scope | Module |
| --- | --- | --- | --- |
| Pin list | `GET file_system_shortcut/?limit=100` | `file_system_shortcut:read` (from `:write`) | `src/api/shortcuts.ts` |
| Pin, unpin | `POST file_system_shortcut/`, `DELETE file_system_shortcut/{id}/` | `file_system_shortcut:write` | `src/api/shortcuts.ts` |
| Dashboard | `GET dashboards/{id}/?refresh=force_cache[&filters_override=]` | `dashboard:read` | `src/api/dashboards.ts` |
| Browse and Recent dashboards | `GET dashboards/?ordering=-last_viewed_at&limit=30&offset=`, `limit=10` for Recent, `search=` | `dashboard:read` | `src/api/dashboards.ts` |
| Insight | `GET insights/{id}/?refresh=blocking\|force_blocking\|force_cache[&from_dashboard=][&filters_override=]` | `insight:read` | `src/api/insights.ts` |
| Browse insights | `GET insights/?basic=true&saved=true&order=-last_modified_at&limit=30&offset=`, `search=` | `insight:read` | `src/api/insights.ts` |
| Insight opened | `POST insights/viewed/ {insight_ids}` once per open | `insight:read` | `src/api/insights.ts` |
| Web analytics, compare, people at a point | `POST query/` with `refresh: blocking` or `force_blocking`, never polled | `query:read` | `src/api/webAnalytics.ts`, `src/api/actors.ts`, `src/api/query.ts` |

Cache reads send `refresh=force_cache` explicitly.
The app never sends `async_except_on_cache_miss`, which the insight endpoint turns into a cache-only read.

## Pins

Pins are the web's starred rows (`FileSystemShortcut`, default surface), so a phone pin shows as a star on the web.
`shortcutInputFor()` writes the exact `path`, `type`, `ref` and `href` the web writes, so the server dedupes the row.
Rows for one view (a sibling environment, a rename) collapse into one pin, and unpin deletes all of them.
The Views list owns the pin list reads: on first paint unless read under a minute ago, on focus when 5 minutes old, and on the button or pull when a minute old. Pin buttons and error states on view screens read the cached list, so opening a view sends no pin list request.

Order and display mode stay on the phone, per project, in the `views-pin-prefs:v2` store (AsyncStorage).
The app never writes the server's `order`: `reorder` is closed to OAuth, and a PATCH would move a sibling-environment pin into this environment.
A new pin, made on the web or the phone, goes after the ranked pins.
A complete pin list read forgets the prefs of that project's pins that are gone. Other projects keep theirs, and signing out clears all of them.

Recent merges the last 20 views opened on this phone (`views-recent:v1`, per project) with the dashboards this user viewed on the web.
Insights viewed on the web do not appear: no per-user source is open to OAuth without a new scope.

## Refresh

The app holds itself to the published API rate limits.

- **Automatic reads never force.** On open, screen focus and app foreground, an item reads with `blocking`, which computes only past `cache_target_age`. An item is due when it has no good value, its `cache_target_age` has passed, or its last read is 5 minutes old, and never within a minute of its last read.
- **Dashboards open like the web:** a `force_cache` dashboard read, then `blocking` for each visible tile with no result or a passed `cache_target_age`. A list reports what it shows only after its rows lay out, so until then the first six rows count as visible (`INITIAL_VISIBLE_ROWS`).
- **The button and pull force only what the server allows:** `force_blocking` for each visible item past its `next_allowed_client_refresh` (in server time, from the `Date` header, plus 2 s) and a minute past its last read. The list and each dashboard also allow one forced pass per 5 minutes. Items that may not force re-read from the cache: on the list at most once per 5 minutes per pin, on a single view once a minute. When nothing may be forced, the button shows a check, and a tap shows "You can refresh again in N min." for 3 s. Every accepted tap or pull shows busy feedback for at least 400 ms, even when no request is due, and keeps it until both item and list reads finish. Repeated presses during that refresh do not start another pass. The button respects reduced motion and stays accessible when blocked so the hint can be read.
- **One queue** (`refreshQueue.ts`): 2 requests in flight, one request per freshness key (a second caller joins it), one request per item per minute, a pause per budget family after a 429 or 503 (`Retry-After`, else 30 s), and one retry 5 s after a rate-limited answer. A screen that loses focus drops its queued jobs. Its running reads go on, because the server finishes a started compute anyway: the answer fills the cache, the read keeps its minute, and a screen that comes back joins the read or finds its result. A read that has not answered after 60 seconds is aborted and frees its queue slot. "Try again" on a view with nothing to show (`refresh.retry`), in "Choose tile" and in the Point sheet always sends its read, also inside the minute, but never forces: the dashboard read, or `blocking` for each item without a value. The screen shows its skeleton while that read runs.
- **List reads share the pause** (`listReads.ts`): the pin list, Recent, Browse and search are TanStack queries, not queue jobs. They wait out the family pause, a 429 or 503 from them pauses the family too, and they never retry a 429 or 503.
- **Hard caps** (`src/api/budget.ts`): token buckets at 25% of each published budget, counted in `send()` for every request of the family, including the report metrics. An empty bucket sends nothing.
- **Freshness only from good responses.** A rate-limited insight answer carries `last_refresh: now()` with no result. Freshness and values change only on a response with a result and no error.

The status line shows "Updating…" while a request of the screen runs, "Updated N min ago" from the oldest good `last_refresh` on screen, and "Updated just now" only when that oldest value is under a minute old.

## Date ranges

A range lasts for the session, per view, in memory (`rangeStore.ts`). Range keys, bulk floors and queue groups carry the data scope (`demo`, or the host and project), so a range or a refresh floor from demo mode or another project never applies.
Overrides always send `date_to`, also as null, because the server merges filters by top-level key.
A dashboard's saved range comes from `persisted_filters`, which a read with an override also carries, so "Not saved" and "Reset to saved range" stay right after the saved-range read has left the cache.
SQL tiles without `{filters}` read without the override, because it would only change their cache key.
Compare on dashboards stays off behind `DASHBOARD_COMPARE_SUPPORTED` until US and EU run a build that accepts `compareFilter` in a dashboard override.

## Demo mode

`src/demo/views.ts` returns API-shaped answers, so demo mode runs the same adapters, queue and status line.
Demo numbers start 42 minutes old; a forced demo read makes them current and moves the next allowed force 3 minutes ahead.

## The Views tab

The third slot of the bottom bar opens the Views tab (`app/(tabs)/views.tsx`, `src/features/views/list/ViewsScreen.tsx`).
It replaced the Products slot, which opened the web app's product library. `mobile_products_opened` went with it; the bar now sends `mobile_views_opened` when the tab is selected, with the pin count from the cached pin list.

The screen is one `SectionList`: a search field, Pinned, Recent and Browse.
The screen publishes its header state to the shared tabs header (`useTabHeader('views', …)`, see DESIGN.md, "Tabs header"): the refresh hint from `useViewsList().refresh`, the refresh button's state, and the "Edit pins" row of the More menu.
Loading, the pin list error and the sign-in state are separate screens. The pin list error sends `mobile_views_error_shown` (`screen: list`, `kind: failed`). The sign-in state (`views-reauth`) shows when `useViewsAccess()` is not `ok`. When the last sign-in asked for a Views scope and the server still left it out, it shows "Views isn't available yet" (`views-unavailable`) without a sign-in button, because a new sign-in gets the same grant ([AUTH.md](AUTH.md), "Server-side ceiling").

### Pins

A pin shows in one of three modes, chosen on this phone:

| Mode | Shows | Height | Reads data |
| --- | --- | --- | --- |
| Row | Icon, name, the view type ("Dashboard", "Built-in view" for web analytics, "Notebook · Opens on the web") | 64 pt | No |
| Number | The value, a neutral change pill, the saved range or the tile name, a 14-bucket sparkline | 139 pt | Yes |
| Chart | The value, the change pill, a compact `MetricChart` | 207 pt | Yes |

Each mode has a fixed height, so the list never moves when a value arrives or a chart's canvas replaces its sparkline placeholder.
Chart pins pass `canvasSlot` and sit inside `ChartCanvasBudget`, so at most six Skia canvases are mounted; the list feeds both the budget and the refresh rules from one `onViewableItemsChanged`. The list and each dashboard pass `active={useIsFocused()}`, so a screen under a pushed view or behind another tab gives its canvases back, and a stack holds only the focused screen's canvases.
A tap on a Chart pin's plot pins a tooltip, and a tap on its name or value opens the view.
A tap on the pinned tooltip opens the Point sheet. `ViewsScreen` wraps the list in `ChartSheetsProvider`, and the sheet follows the pin's own cache entry, which reads the saved range.
A Chart pin draws the first current series and its previous period (`pinChartSeries`, built on `snapshotChartSeries`), because the pin has no legend.
Web analytics and pins that open on the web show as rows only (`pinModes`).

A dashboard pin in Number or Chart mode shows one tile.
The subtitle shows the tile's title.
Picking Number or Chart on a dashboard pin without a tile opens "Choose tile" at once, with the first tile that can show that mode chosen.
The sheet lists the dashboard's tiles from the cached dashboard, or one `force_cache` dashboard read when it has none or it is 5 minutes old.
A pin shows one number or one line over time, so a funnel, a pie, a table, a text card, or a trends insight with several series or a breakdown cannot be its tile (`capabilitiesOf`).
The sheet sends `mobile_pin_tile_sheet_opened` (`entry`: `show_as`, `menu` or `removed_tile`; `mode`) and, once per opening, `mobile_pin_tile_sheet_closed` (`entry`, `picked`, `tiles_usable`, `tiles_unusable`; the counts are null when it closed before the tiles loaded). `picked` is false for the automatic first choice. `mobile_pin_tile_chosen` still marks each choice.
The tiles the mode can show come first, in dashboard order. The rest sit under "Can't show as a number" or "Can't show as a chart", disabled, each with its reason ("Has 3 series", "Has a breakdown", "Not a single number", "Not a chart over time", "Text card"; `tileEligibility.ts`). When no tile fits, the header says so.
A pin whose tile is gone (its insight answers 404, or the cached dashboard no longer has the tile) shows as a row with "The chosen tile was removed. Choose another."

### Pin actions

- Long press any pin for its menu: Show as Row, Number or Chart, Choose tile (dashboards), Move up, Move down, Unpin.
- Long press a Recent, Browse or search row for Pin to Views (or Unpin) and Open.
- Every Recent, Browse and search row has a pin button. Tap it to pin or unpin the view; rows have no swipe action.
- "Edit pins" (the More menu's Views section, or Edit next to Pinned) lists the pins with a remove button, a Row, Number and Chart toggle, and a drag handle. Screen readers move a pin with the handle's actions. It sends `mobile_edit_pins_opened` (`from`: `section` or `menu`; `pin_count`) and `mobile_edit_pins_closed` (`reason`: `done` or `no_pins`; `changes`, the number of reorders, moves, mode changes and removals; `duration_s`).

Order and modes go to the device-local prefs through `usePinActions` (`move`, `reorder`, `setDisplayMode`, `chooseTile`). The app never writes the server's `order`.
Pin and unpin show a toast with Undo, from the list, Browse and a view's pin button alike (`ViewsToast` and `useToasts`). The toast draws through the nearest `OverlayHost`, so it sits above the tab bar and any open sheet.
Undo pins the view again as a new row, so it comes back as a Row at the end of the list. An undo sends `mobile_view_pinned` or `mobile_view_unpinned` with `from: undo`.
Pin and unpin of one view run one after another from every screen (`pinView`, `unpinView`): a second tap waits for the first instead of being dropped, the toast shows once the change is saved, and an unpin made while a pin saves deletes the row that pin created.

### Search and Browse

Search shows local matches first (pins as their cards, Recent rows), then dashboards and insights from the server, without the views already shown.
Browse has Dashboards, Insights, Web analytics and Recordings. Recordings opens the project's replay list on the web and shows an external-link icon on its row.
The Dashboards and Insights lists (`app/views/browse/*.tsx`, `src/features/views/browse/BrowseListScreen.tsx`) load 30 rows at a time and search on the server with `useBrowseSearch`.
Their Browse rows send `mobile_browse_list_opened` (`section`: `dashboards` or `insights`; `from`: `browse` or `search`). Each next page that loads sends `mobile_browse_list_paged` (`section`, `pages_loaded`), and a failed first page sends `mobile_views_error_shown` (`screen: browse`).
`mobile_views_searched` (`section`: `views`, `dashboards` or `insights`; `query_length`, `result_count`) goes once per settled query, from the Views list and from each Browse list.

### Routes

| View | Route |
| --- | --- |
| Dashboard | `/views/dashboard/{ref}?from={entry}[&mode={display mode}]` |
| Insight | `/views/insight/{short_id}?from={entry}[&mode={display mode}]` |
| Web analytics | `/views/web-analytics?from={entry}` |
| Full-screen chart | `/views/chart/{short_id}[?key={cache key}]` |
| Browse lists | `/views/browse/dashboards`, `/views/browse/insights` |

`from` is the `ViewEntry` (`pinned`, `recent`, `browse`, `search` or `dashboard`) for `mobile_view_opened`; `mode` is the pin's display mode.
Build links with `src/features/views/viewRoutes.ts` (`viewHref`, `dashboardHref`, `insightHref`, `webAnalyticsHref`, `chartHref`), never by hand.
An insight opened from a tile also carries `fromDashboard` and `insightId`: it reads with `from_dashboard` and shares the dashboard's session range.
Deep links work: `posthog://views/dashboard/demo-dash-kpis`, `posthog://views/insight/demo-ins-dau`, `posthog://views/web-analytics`.

## View screens

The dashboard, insight and web analytics screens (`app/views/dashboard/[id].tsx`, `app/views/insight/[shortId].tsx`, `app/views/web-analytics.tsx`) share one frame:

- `ViewScreenFrame` puts an `OverlayHost` above `ChartSheetsProvider` and `ChartSelectionProvider`. View screens are pushed above the tabs, so they bring their own host for sheets and toasts. The sheets draw outside the chart selection, so a pinned tooltip stays behind an open Point sheet.
- `ViewChrome` is the floating top row: Back (`view-back`), the refresh button (`views-refresh`) and More (`view-more`, "Open on web"). The More sheet sends `mobile_view_more_opened` (`view_type`) when it opens.
- `ViewTitle` holds the title with the pin button (`view-pin`), the status line (`views-updated`), the refresh hint, the date range control and the resolved dates.
- `ViewsReauthState` replaces the content when `useViewsAccess()` is not `ok`, on the list and on every view screen.
- `ViewErrorState`: "This view was deleted" (`view-deleted`), no access (`view-no-access`) or a failed read (`view-error`), with Unpin when the view is pinned. A first read that returns a query error, reaches the request deadline, or has no available request budget shows the failed state with Try again, including when the read supplied metadata but no result. It sends `mobile_views_error_shown` (`screen`: the view type; `kind`: `deleted`, `no_access`, `scope` or `failed`). `RefreshFailedBanner` shows when a visible item's last read failed, and failed values dim to 50%.

| Screen | Content |
| --- | --- |
| Dashboard | Tiles in one column (`FlatList`, `ChartCanvasBudget` keyed by tile id). The first time the dashboard shows, it sends `mobile_dashboard_tiles_shown` (`tiles_total`, `tiles_text`, `tiles_web_only`). A tile is a number, a line or bar chart, funnel steps, a retention grid, a bar list, a card that opens on the web, or a text card. Tiles that the phone draws have a full-screen button in their head (`view-tile-fullscreen-{tileId}`). Tiles with their own date range say "Uses its own range" and keep their numbers when the range changes. |
| Insight | The big number with its change pill, then the visual (`InsightVisual`) under a caption row with the full-screen button (`view-fullscreen`), ⓘ for "About this chart" (`view-about`). |
| Web analytics | The overview numbers in two columns, each with its change from the previous period. It always compares, as the web's overview tile does. |

A tap on a pinned tooltip opens the Point sheet (`point-sheet`): the bucket and every series value, "Watch recordings", "View people", "Open on web", "About this chart" and "Copy value".
People and recordings load through `usePointActors`, one `blocking` actors query at a time; closing the sheet drops a query that has not started. In demo, rows that open the web say "Not available in the demo".
An insight kind without a phone renderer shows "This chart opens on the web." `insightDisplay()` in `snapshotChart.ts` decides from the saved query, so a tile keeps its display while it loads; see [Kinds that still open the web](#kinds-that-still-open-the-web).
A drawable tile that the cache-only dashboard read found without a cache says "Not loaded yet" with Load (`view-tile-load-{tileId}`), which reads that tile only. It shows a skeleton while its read runs. A result with nothing to draw says "No data for this range" (`view-tile-empty-{tileId}`, `view-insight-empty`, `chart-fullscreen-empty`), or "No data" without a range. `insightRenderState()` returns `pending`, `empty` or `ready`.

## Date range control

The range sits in each view's header, under the title (`src/features/views/range/`).

- **Header row** (`ViewRangeControl`): ‹ (`range-step-prev`), the range button (`view-range`), › (`range-step-next`), and "Not saved" (`view-range-not-saved`) while the range differs from the saved one. The resolved dates show under the row.
- **Steps:** ‹ and ›, or a swipe on the button (right for the earlier period), step through periods with a selection haptic. Steps start from the window the server resolved (`rangeStep.ts`), so they wait while a new range loads. › stops at the current period, and a step that lands on it returns to the matching relative preset, so the cache is shared with the web again. All time cannot step. Screen readers adjust the button up or down to step, and activate it to open the sheet.
- **Sheet** (`RangeSheet`, `range-sheet`): what the view shows now, six chips (`range-chip-{today|yesterday|24h|7d|30d|90d}`), the web's other presets (`range-preset-{key}`; "This year", no "Last year"), "Custom range" (`range-custom`), "Compare to previous period" (`range-compare`), and "Reset to saved range" (`range-reset`) only while the range differs. Chips and presets apply at once and keep the sheet open; Done (`sheet-done`) closes it.
- **Custom range** (`RangeCalendar`, `range-calendar`): a month grid in the project timezone. The first tap sets the start, the second the end (taps in reverse order swap), and a third starts over. Future days are disabled. ‹ › (`range-month-prev`, `range-month-next`) or a swipe change the month, and Apply (`range-apply`) sends date-only strings.
- **Compare:** on an insight it runs the compare query from the data layer, and is off for All time. The query takes `query.source` from any read of the insight, so a range change with compare on sends only the compare query. An insight saved with compare shows its saved range from the retrieve, which already carries both periods. Opened from a tile, the insight shares the dashboard's range but keeps its own compare toggle. On a dashboard the switch stays disabled with "Compare works on single insights. Open a chart to compare." while `DASHBOARD_COMPARE_SUPPORTED` is false. Web analytics has no compare row.

A range change reads with `blocking`, never `force_*`: the new override is a new cache key, so the screen hooks run their open path again (`trigger: range`). Each range has its own queue group, so a new range drops the queued reads of the previous one and its own reads go next.
While the new range loads, the insight and web analytics screens keep the previous values on screen (`rangeLoading`), and dashboard tiles keep their layout.
Dashboard rows count as visible by tile id, because a range change gives every tile a new item key while the list keeps the same rows.
Number and Chart pins in the list keep the saved range. Ranges last for the session, per view, in memory.
`useViewRange` sends `mobile_date_range_changed` (`chip`, `more`, `custom`, `step`, `reset`) and `mobile_date_range_compared`. The sheet sends `mobile_date_range_sheet_opened` (`view_type`; `entry`: `button`, `not_saved` or `accessibility`) when it opens.

## Charts beyond line and bar

`insightDisplay(snapshot)` returns `number`, `chart`, `funnel`, `retention`, `bars` or `web`. It takes the display from the saved query (`queryDisplay`), with the same rules the adapters use (`isDrawableFunnel`, `isDrawableRetention`, `isRankingQuery`, `timeSeriesChartKind`). `InsightVisual` (`src/features/views/InsightVisual.tsx`) renders every display except a big number, in tiles and on the insight screen.

| Display | When | Renderer |
| --- | --- | --- |
| `number` | Big number insights that have one value | `NumberBody` on tiles, the hero on the insight screen |
| `chart` | Trends line and bar displays, with any number of series and breakdowns | `MetricChart` with a legend |
| `funnel` | `FunnelsQuery` in the steps layout. A breakdown adds its values step by step and says so under the steps | `FunnelSteps` |
| `retention` | `RetentionQuery` that counts people, without a breakdown | `RetentionGrid` |
| `bars` | Trends value bars, tables, pies, donuts and proportion bars | `BarList` |
| `web` | Everything else, and a funnel or retention result that its adapter cannot draw | `OpensOnWeb` |

- `FunnelSteps`, `RetentionGrid` and `BarList` live in `src/ui/chart/` and draw React Native rows, not a Skia canvas. Their data comes from `src/model/adapters/funnel.ts`, `retention.ts` and `breakdown.ts` through `InsightSnapshot.funnel`, `.retention` and `.ranking`.
- Pins keep one series: `capabilities.chart` still means one series without a breakdown, and `pinChartSeries` draws the first current series only.
- A breakdown insight has no big number, because no one value stands for it. A trends insight with a breakdown, or a ranking with several values, has `capabilities.number = false`.
- A tap on a funnel step, bar row or retention cell selects it (`useItemSelection`), under the same one-selected-chart rule as a line chart tooltip: an outside tap, a scroll away, Android back or new data clears it. A funnel step shows the median time from the previous step, a bar row its share of the total (or its rank when the values do not add up), and a retention cell a callout under the grid.
- A tile ranks six values; "+N more" opens the bar list full screen.
- Every chart kind is one adjustable VoiceOver element: a summary label, the selected item as its value, and a swipe up or down to move. Its actions are "About this chart" and "Open full screen".
- These charts have no Point sheet: the API inventory has no actors query for funnels, retention or bars.

## Full screen

`app/views/chart/[shortId].tsx` renders `FullScreenChart`. Open it with `useOpenFullScreen()`, which sends `mobile_chart_fullscreen_opened` (`entry`: `button`, `legend_more`, `rows_more` or `accessibility`; `display`: `chart`, `funnel`, `retention` or `bars`) and pushes `chartHref(shortId, queryKey)`.

- Entries: the tile head button, the insight screen's caption row, the legend "+N" pill, the bar list "+N more" row, and the VoiceOver action "Open full screen".
- `key` is the JSON cache key of the snapshot that opened the screen. Full screen therefore shows the same session range, compare and tile layers as the tile or insight. While a new range loads on the insight screen, `key` names the previous range's entry, which is the one on screen (`InsightScreenState.queryKey`). Without `key`, it reads the insight's own entry.
- It reads the cache only and never sends a request. A key without a cached snapshot (the app restarted, or a deep link to an insight not opened yet) shows "This chart isn't loaded" with "Go back" (`chart-fullscreen-missing`).
- A line or bar chart fills the space, scrubs on a drag in any direction, shows every tooltip row, and lists every series as a 44 pt legend row that scrolls. Funnels, retention (all periods) and bar lists (all rows) show in a card.
- Charts on this screen send the usual chart events with `context: fullscreen`.
- Portrait only: the app has no `expo-screen-orientation`, and landscape needs that native module in a new binary. There is no "Zoom to range" or "Show as table" yet.

## Kinds that still open the web

These show the "This chart opens on the web." card, on tiles and on the insight screen. The phone never computes them once it knows the kind: the item's `drawable()` is false, so open, focus, the button, pull and "Try again" send no `blocking` or `force_*` read for them, on a dashboard and on the insight screen. The button and pull still send cache-only reads (the dashboard read, or `force_cache` on the insight screen), and the tile has no refresh button. A cold open of an insight with nothing cached reads once with `blocking`, because the kind is unknown until that read.

- Paths (`PathsQuery`), stickiness (`StickinessQuery`: its x axis is "Day N", not dates) and lifecycle (`LifecycleQuery`: stacked bars with negative dormant values).
- SQL insights (`HogQLQuery`, `DataVisualizationNode`) that are not a big number. The phone has no table renderer.
- Trends world maps, calendar heatmaps and box plots.
- Funnels in the trends or time-to-convert layout, and funnels broken down by cohort: one person can be in several cohorts, so a sum would count them twice.
- Retention with a breakdown, or with a sum or average aggregation (amounts, not people).
- Web analytics query tiles on a dashboard, and any other query kind.

The web analytics screen shows the overview numbers only. Its top lists open on the web, because the data layer reads only the overview query.

## What waits on the backend

The tab makes no backend change. [`VIEWS_BACKEND_FOLLOWUPS.md`](VIEWS_BACKEND_FOLLOWUPS.md) lists the server work that would unlock more, ranked by user value, with the app change that follows each item. The main ones:

- A server-side check of `next_allowed_client_refresh` for app callers, so focus can force a refresh safely.
- Display mode and chosen tile on the server, so pins keep their mode on a new phone.
- Insights viewed on the web in Recent, and phone views in the web's "Recently viewed".
- Compare on dashboards: `DASHBOARD_COMPARE_SUPPORTED` stays false until US and EU run a build that accepts `compareFilter` in a dashboard override (the deploy check at the end of that file).

## Smoke flow

`.argent/flows/views-smoke.yaml` starts on sign-in with demo mode off and:

1. pins Signups as a number in Edit pins;
2. opens Product KPIs, picks 7 days, steps back and resets;
3. opens the Daily active users tile, turns on compare, opens the Point sheet from the chart tooltip (`chart-tooltip`), and opens the chart full screen with the previous period in the legend;
4. back on the dashboard, pins a tooltip on the first tile, selects a bar list row and a funnel step, opens the funnel full screen, and selects a retention cell;
5. opens the Dashboards list from Browse, goes home and exits the demo.

After an edit, restart Metro with `--clear` before you replay the flow: the watcher can serve stale modules.
