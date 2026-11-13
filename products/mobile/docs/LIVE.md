# Live

The Live screen mirrors the web's Web analytics → Live tab: users online, active users per minute, top pages and referrers for the last 30 minutes, a devices, browsers and countries card, and the newest events.
It reads the web's HogQL polling transport, not the event stream, so it needs no backend change.

The route is `/views/live?from={entry}` (`app/views/live.tsx`), a pushed screen with the usual Back and More chrome.
More has "Pin to navigation" (or "Unpin from navigation") and "Open on web", which opens `/web/live`.
Live opens from the Browse row (`views-browse-live`), from the Live chip on Web analytics (`from=web_analytics`), and as a pinned tab (`app/(tabs)/live/`, `/live`), which can also be the start page.
`LiveScreen({ from, chrome })` draws both: on the tab (`chrome="tab"`) the tabs header draws the title alone, the content starts with one row (the dot, the status line, the Pause pill), and the tabs menu has Unpin and Open on web.
Deep link: `posthog://views/live` opens the pushed screen.
Live needs `query:read`, so it reuses the Views access check (`useFeatureAccess('views')`) and `ViewsReauthState`.

## Files

| File                                  | Holds                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/api/live.ts`                     | The queries, the 30-minute window, the project read, and the live events `stats` read                                                            |
| `src/model/live.ts`                   | View models                                                                                                                                      |
| `src/model/adapters/live.ts`          | Pure adapters: minute buckets, ranked rows with rank changes, breakdowns, events, users online                                                   |
| `src/features/live/liveController.ts` | The polling controller: focus, app state, Pause, timers, failure streaks                                                                         |
| `src/features/live/liveRead.ts`       | One read: runs the jobs two at a time and merges them into the last snapshot                                                                     |
| `src/features/live/hooks.ts`          | `useLiveFeed`: the data source (demo or project), both pollers, users online fallback, error events. `useLiveUsersOnline`: the Live chip's count |
| `src/features/live/LiveScreen.tsx`    | `LiveScreen({ from, chrome })` and its body, title, status line and paused banner                                                                |
| `src/ui/LiveDot.tsx`                  | The pulsing dot, shared with the Live chip                                                                                                       |
| `src/demo/live.ts`                    | The seeded demo traffic                                                                                                                          |

## Requests

Each read sends these jobs through `POST query/` with `refresh: blocking` and no status polls, two at a time.
The HogQL text follows `loadQueryData` in `frontend/src/scenes/web-analytics/LiveMetricsDashboard/liveWebAnalyticsMetricsLogic.tsx`, in its unfiltered form: the window goes in `values` (`dateFrom`, `dateTo`), not in `{filters}`.

| Job              | Query                                                                     | Card                           |
| ---------------- | ------------------------------------------------------------------------- | ------------------------------ |
| `usersPageviews` | Visitor, new visitor and pageview counts per minute                       | Stats, Active users per minute |
| `paths`          | `TrendsQuery`, `$pageview` by `$pathname`, minute interval, top 10        | Top pages                      |
| `referrer`       | Pageviews per referring domain per minute, `$direct` when empty           | Top referrers                  |
| `device`         | Unique device counts by `$device_type` across the window                  | Devices                        |
| `browser`        | Unique device counts by `$browser` across the window                      | Browsers                       |
| `geo`            | Unique visitor counts by `$geoip_country_code` across the window          | Countries                      |
| `recentEvents`   | The newest 50 events                                                      | Live events                    |
| `usersOnline`    | `uniq(distinct_id)` over the last minute, only when the stats read is off | Users online                   |

The window starts at the first of the 30 minutes on screen and ends one minute after now to allow for clock skew.
The activity chart and breakdown queries stop at the end of the current minute so totals cover the displayed buckets.
HogQL counts visitors by their first minute in the window and deduplicates across the full window for each breakdown category.
These jobs return counts to the app.
The events query selects `toUnixTimestamp64Milli(timestamp)` instead of the web's `toString(timestamp)`, which is wall-clock time in the project's time zone with no offset.
The `usersPageviews` query leaves out the web's bot column, because Live has no bot cards.
`paths` sets `breakdown_path_cleaning` when the project has path cleaning rules, as the web does.

Two more reads, outside the query budget:

- `GET api/projects/{id}/` once per project and session, for `live_events_token` and `path_cleaning_filters`. The server sends the token only when the grant covers `query:read`.
- `GET {live host}/stats` with `Authorization: Bearer <live_events_token>`, every 10 seconds, on US Cloud (`live.us.posthog.com`) and EU Cloud (`live.eu.posthog.com`). It is a plain `fetch` with an 8-second timeout. It answers `users_on_product`.

Users online comes from the HogQL `usersOnline` job instead when the host is not Cloud, the project has no token, or two stats reads in a row fail. It then changes every 30 seconds.

The Live chip on the Web analytics screen reads users online alone: the stats read every 30 seconds, or the `usersOnline` query alone every 30 seconds on the `live` budget when the stats read is off. It reads only while the Web analytics screen is focused and the app is in the foreground, and never runs the jobs above. After a failed read, the chip keeps its last count for 10 seconds, then retries once before showing “Reconnecting…”. It waits up to 5 more seconds for that check, joining a read already in progress. A successful check updates the count without showing a warning. The chip and Live screen pause their pulses and clocks when their screens are hidden or the app leaves the foreground.

## Polling

`LiveController` runs one poller for the 30-second read and one for the 10-second stats read.

- **Reads only while seen.** A poller reads when the screen is focused, the app is in the foreground and the user has not paused. Losing focus stops at once and aborts the read in flight. Live never polls behind another screen.
- **Background grace.** When the app leaves the foreground, reads stop after 2 seconds, like the web's hidden-tab grace. Coming back within 2 seconds changes nothing. Coming back later reads at once, then polls again.
- **Timed from the end of a read**, so a slow read never overlaps the next.
- **Slower after 10 minutes.** After 10 minutes of polling with no user action, the read comes every 60 seconds instead of 30. Pull to refresh, Try again, Resume, reopening the screen, and coming back to the foreground after reads stopped set it back to 30 seconds and start the 10 minutes again. Scrolling does not count. The status line still says when the last update came. The stats read keeps its 10-second interval.
- **Pause** stops every timer and aborts the read in flight. Resume reads at once, then polls again.
- **Pull to refresh** reads now. While paused it reads once and stays paused.
- **Failures.** A job that fails, or answers with a query that still runs, keeps its card's last value. After a failed read, the status line keeps its previous state for 10 seconds, then retries once or joins a read already in progress. If that check fails or has not completed after 5 more seconds, it shows "Reconnecting…" and the toast "Couldn't update live data. Retrying…" once per failure streak. A successful check cancels the warning. This extra read uses the existing query budget and does not reset the inactivity slowdown. Subsequent reads use the normal interval (30 or 60 seconds), with total failures doubling the delay up to 5 minutes. A first read that fails shows "Couldn't load live data" with Try again.
- **A missing scope** (403 naming `query:read`) reports a Views scope error, so the screen shows the sign-in state.

## Budget

Live spends the `live` budget family (`src/api/budget.ts`): 60 requests a minute and 900 an hour, so its polling never empties the Views or replay buckets and theirs never stop Live.
The other families hold 25% of the published budget. Live polls by design, and at 25% a normal session would stop after about half an hour, so Live holds 75% of the published query budget.
The buckets refill all the time, so the hourly bucket gets 15 requests back each minute.
One read is 7 queries, or 8 with the users online count.
In the first 10 minutes a focused screen sends up to 16 queries a minute, 1 more than the refill. After that it sends up to 8 a minute, less than the refill.
So steady polling never empties the hourly bucket, and a focused screen keeps updating for as long as it stays open.
Many pulls to refresh in a row can still empty the minute bucket. Reads then fail with "Reconnecting…" until the bucket refills.

## Screen

1. Title "Live" with a dot: green and pulsing while live, gray when paused or reconnecting, still with reduced motion. The status line says "Live · updated 12 s ago", "Paused", "Reconnecting…" or "Loading…". The Pause or Resume pill (`live-pause`) sits at the right of the title.
2. Paused banner (`live-paused-banner`): "Paused. Tap Resume to catch up." with Resume (`live-banner-resume`).
3. Stats (`live-stats`): Users online, Unique visitors and Pageviews, with the web's tooltips in a toast when a label is tapped. A changed number counts to its new value in 300 ms and flashes blue.
4. Active users per minute (`live-activity`): 30 stacked bars, new visitors (green) under returning visitors (blue), as the web draws them. A visitor is new in the first minute of the window that shows them. The line under the chart names the scrubbed minute, or the current one: "21:14 · 18 visitors · 9 pageviews". The last bar is in progress.
5. Top pages and Top referrers (`live-top-pages`, `live-top-referrers`): ten rows with views and their share of the window's pageviews. A row that changes rank slides to its place with a ↑ or ↓ badge that fades after 4 seconds. "Direct / None" is in italics.
6. Breakdown (`live-breakdown`): Devices, Browsers or Countries, with the total and a share bar per row. Browsers and countries show their top six and an "Other" row. Countries show a flag and a name from the web analytics helper (`countryName`), which uses `Intl.DisplayNames` where the runtime has it and a short list otherwise; codes neither names stay codes. Rows do not open anything, because the web's visitor drill-down is behind a flag.
7. Live events (`live-events`): the newest 50, newest first. Events that arrive after the first read slide in with a short highlight. A tap opens the event sheet (`live-event-sheet`): Person with Copy, URL or Screen, Session with "Watch recording", and "View person on web". Watch recording opens the app's session screen when the session replay flag is on, and the web player otherwise.

Loading shows the skeleton (`live-loading`). Empty cards say "No activity in the last 30 minutes", "No pageviews recorded in the last 30 minutes", "No referrer data in the last 30 minutes", "No device data", "No browser data", "No country data" or "Waiting for events…". A card whose job has not answered yet says "Couldn't load this yet. Live tries again every 30 seconds."

## Analytics

| Event                            | Properties                                                                                                                      |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `mobile_live_opened`             | `from` (the `ViewEntry`; `web_analytics` for the chip, `tab` for the pinned tab), `chrome`: `tab` or `stack`. Each focus counts |
| `mobile_live_opened_in_web`      |                                                                                                                                 |
| `mobile_live_error_shown`        | `kind`: `load_failed` or `refresh_failed`, once per streak                                                                      |
| `mobile_live_refreshed`          | `trigger`: `pull` or `resume`                                                                                                   |
| `mobile_live_paused`             | `trigger`: `button` or `background`                                                                                             |
| `mobile_live_resumed`            | `trigger`: `button` or `foreground`                                                                                             |
| `mobile_live_breakdown_changed`  | `breakdown`: `devices`, `browsers` or `countries`                                                                               |
| `mobile_live_event_sheet_opened` | `kind`: `pageview`, `screen` or `other`                                                                                         |
| `mobile_live_event_action_taken` | `action`: `view_person`, `watch_recording`, `copy_distinct_id`                                                                  |

The chart also sends the shared `mobile_chart_*` events with the `view` context.

## Demo mode

`src/demo/live.ts` writes invented hedgebox.net traffic from a seeded generator, and answers each job in the shape of its query, so demo mode runs the same adapters.
Visitors come and go, page weights drift so ranks swap now and then, and an event arrives every 1.2 to 3.6 seconds.
Events are written up to the moment of each read, so nothing moves while paused, and the next read catches up.
One simulator lives for the app session, so reopening Live continues the same traffic.
Users online comes from the HogQL count in demo mode. Watch recording and View person on web are not available in the demo.

## Not in v1

- The web's domain and device filters, the city, bot and recent visitor queries, and the visitor drill-down from a breakdown row.
- The event stream (`/events` on the live host). The screen's layout does not depend on the transport.
- The project's time zone on the chart: times are in the device's time zone, like the app's other charts.
- Referrer favicons.
