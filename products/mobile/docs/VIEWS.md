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

Order and display mode stay on the phone, in the `views-pin-prefs:v1` store (AsyncStorage).
The app never writes the server's `order`: `reorder` is closed to OAuth, and a PATCH would move a sibling-environment pin into this environment.
A new pin, made on the web or the phone, goes after the ranked pins.
Signing out clears the prefs.

Recent merges the last 20 views opened on this phone (`views-recent:v1`, per project) with the dashboards this user viewed on the web.
Insights viewed on the web do not appear: no per-user source is open to OAuth without a new scope.

## Refresh

OAuth requests skip the server's DRF throttles, so the app holds itself to the published personal API key budgets.

- **Automatic reads never force.** On open, screen focus and app foreground, an item reads with `blocking`, which computes only past `cache_target_age`. An item is due when it has no good value, its `cache_target_age` has passed, or its last read is 5 minutes old, and never within a minute of its last read.
- **Dashboards open like the web:** a `force_cache` dashboard read, then `blocking` for each visible tile with no result or a passed `cache_target_age`.
- **The button and pull force only what the server allows:** `force_blocking` for each visible item past its `next_allowed_client_refresh` (in server time, from the `Date` header, plus 2 s) and a minute past its last read. The list and each dashboard also allow one forced pass per 5 minutes. When nothing may be forced, the button shows a check, and a tap shows "Up to date. You can refresh again in N min." for 3 s.
- **One queue** (`refreshQueue.ts`): 2 requests in flight, one request per freshness key (a second caller joins it), one request per item per minute, a pause per budget family after a 429 or 503 (`Retry-After`, else 30 s), and one retry 5 s after a rate-limited answer.
- **Hard caps** (`src/api/budget.ts`): token buckets at 25% of each published budget, counted in `send()` for every request of the family, including the report metrics. An empty bucket sends nothing.
- **Freshness only from good responses.** A rate-limited insight answer carries `last_refresh: now()` with no result. Freshness and values change only on a response with a result and no error.

The status line shows "Updating…" while a request of the screen runs, "Updated N min ago" from the oldest good `last_refresh` on screen, and "Updated just now" only when that oldest value is under a minute old.

## Date ranges

A range lasts for the session, per view, in memory (`rangeStore.ts`).
Overrides always send `date_to`, also as null, because the server merges filters by top-level key.
SQL tiles without `{filters}` read without the override, because it would only change their cache key.
Compare on dashboards stays off behind `DASHBOARD_COMPARE_SUPPORTED` until US and EU run a build that accepts `compareFilter` in a dashboard override.

## Demo mode

`src/demo/views.ts` returns API-shaped answers, so demo mode runs the same adapters, queue and status line.
Demo numbers start 42 minutes old; a forced demo read makes them current and moves the next allowed force 3 minutes ahead.

## The Views tab

The third slot of the bottom bar opens the Views tab (`app/(tabs)/views.tsx`, `src/features/views/list/ViewsScreen.tsx`).
It replaced the Products slot, which opened the web app's product library. `mobile_products_opened` went with it; the bar now sends `mobile_views_opened` when the tab is selected, with the pin count from the cached pin list.

The screen is one `SectionList`: a search field, Pinned, Recent and Browse.
The header shows the status line and the refresh hint from `useViewsList().refresh`, the refresh button and a More menu with "Edit pins".
Loading, the pin list error and the sign-in state are separate screens. The sign-in state shows when `useViewsAccess()` is not `ok`, with the copy of the plan's scope section.

### Pins

A pin shows in one of three modes, chosen on this phone:

| Mode | Shows | Height | Reads data |
| --- | --- | --- | --- |
| Row | Icon, name, the view type ("Dashboard", "Notebook · Opens on the web") | 64 pt | No |
| Number | The value, a neutral change pill, the saved range or the tile name, a 14-bucket sparkline | 139 pt | Yes |
| Chart | The value, the change pill, a compact `MetricChart` | 207 pt | Yes |

Each mode has a fixed height, so the list never moves when a value arrives or a chart's canvas replaces its sparkline placeholder.
Chart pins pass `canvasSlot` and sit inside `ChartCanvasBudget`, so at most six Skia canvases are mounted; the list feeds both the budget and the refresh rules from one `onViewableItemsChanged`.
A tap on a Chart pin's plot pins a tooltip, and a tap on its name or value opens the view.
Web analytics and pins that open on the web show as rows only (`pinModes`).

A dashboard pin in Number or Chart mode shows one tile.
Picking Number or Chart on a dashboard pin without a tile opens "Choose tile" at once, with the first tile that can show that mode chosen.
The sheet lists the dashboard's tiles from the cached dashboard, or one `force_cache` dashboard read when it has none or it is 5 minutes old.
A pin whose tile is gone (its insight answers 404, or the cached dashboard no longer has the tile) shows as a row with "The chosen tile was removed. Choose another."

### Pin actions

- Long press any pin for its menu: Show as Row, Number or Chart, Choose tile (dashboards), Move up, Move down, Unpin.
- Long press a Recent, Browse or search row for Pin to Views (or Unpin) and Open.
- Swipe a row left for Pin or Unpin. Chart pins have no swipe, because their plot takes horizontal drags.
- Every Recent, Browse and search row has a pin button.
- "Edit pins" (More menu, or Edit next to Pinned) lists the pins with a remove button, a Row, Number and Chart toggle, and a drag handle. Screen readers move a pin with the handle's actions.

Order and modes go to the device-local prefs through `usePinActions` (`move`, `reorder`, `setDisplayMode`, `chooseTile`). The app never writes the server's `order`.
Pin and unpin show a toast with Undo. Undo pins the view again as a new row, so it comes back as a Row at the end of the list.

### Search and Browse

Search shows local matches first (pins as their cards, Recent rows), then dashboards and insights from the server, without the views already shown.
Browse has Dashboards, Insights, Web analytics and Recordings. Recordings opens the project's replay list on the web.
The Dashboards and Insights lists (`app/views/browse/*.tsx`, `src/features/views/browse/BrowseListScreen.tsx`) load 30 rows at a time and search on the server with `useBrowseSearch`.

### Routes

| View | Route |
| --- | --- |
| Dashboard | `/views/dashboard/{ref}?from={entry}[&mode={display mode}]` |
| Insight | `/views/insight/{short_id}?from={entry}[&mode={display mode}]` |
| Web analytics | `/views/web-analytics?from={entry}` |
| Browse lists | `/views/browse/dashboards`, `/views/browse/insights` |

`from` is the `ViewEntry` (`pinned`, `recent`, `browse` or `search`) for `mobile_view_opened`; `mode` is the pin's display mode.
