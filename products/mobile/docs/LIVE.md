# Live

The Live screen mirrors the web's Web analytics → Live tab: users online, a world map of where visitors are, active users per minute, top pages and referrers for the last 30 minutes, a devices, browsers and countries card, and the newest events.
It reads the web's HogQL polling transport, not the event stream, so it needs no backend change.

Live is the Home tab (`app/(tabs)/live/`, `/live`): the first slot of the bottom bar and the start page until the person picks another in Settings.
Views has no Browse row for Live, because Live is Home.
Live also opens as a pushed screen at `/views/live?from={entry}` (`app/views/live.tsx`) with the usual Back and More chrome, from the Live chip on Web analytics (`from=web_analytics`) and from deep links.
More has "Open on web", which opens `/web/live`. Live is not a navigation pin, because it is Home.
`LiveScreen({ from, chrome })` draws both: on Home (`chrome="tab"`) the tabs header draws the title "Live" and a Pause or Resume button (`live-pause`) left of More, the content starts with the cards, and the tabs menu has Open on web.
Home has no dot or status line while updates succeed.
When polling keeps failing, the header shows "Reconnecting…" until updates recover.
The warning waits for the check in **Failures** below.
When the person comes back to Home during the same failure streak, the check runs again before the warning shows.
Deep link: `posthog://views/live` opens the pushed screen.
Live needs `query:read`, so it reuses the Views access check (`useFeatureAccess('views')`) and `ViewsReauthState`.

## Files

| File                                        | Holds                                                                                                                                            |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/api/live.ts`                           | The queries, the 30-minute window, the project read, and the live events `stats` read                                                            |
| `src/model/live.ts`                         | View models                                                                                                                                      |
| `src/model/adapters/live.ts`                | Pure adapters: minute buckets, ranked rows with rank changes, breakdowns, events, users online                                                   |
| `src/features/live/liveController.ts`       | The polling controller: focus, app state, Pause, timers, failure streaks                                                                         |
| `src/features/live/liveRead.ts`             | One read: runs the jobs two at a time and merges them into the last snapshot                                                                     |
| `src/features/live/hooks.ts`                | `useLiveFeed`: the data source (demo or project), both pollers, users online fallback, error events. `useLiveUsersOnline`: the Live chip's count |
| `src/features/live/LiveScreen.tsx`          | `LiveScreen({ from, chrome })` and its body, title, status line and paused banner                                                                |
| `src/features/live/LiveMapCard.tsx`         | The "Where visitors are" card                                                                                                                    |
| `src/features/live/LiveNoTraffic.tsx`       | The Quiet and Not set up cards, then Meanwhile                                                                                                   |
| `src/features/live/LiveMeanwhile.tsx`       | Meanwhile: two pinned views and the Inbox row, with `LiveMeanwhileRow`; `useLiveMeanwhile` reads them from the cache                             |
| `src/features/live/LiveCountriesScreen.tsx` | Visitors by country (`app/views/live-countries.tsx`)                                                                                             |
| `src/features/live/LiveCountryList.tsx`     | The country list of Visitors by country                                                                                                          |
| `src/features/live/liveWorldStore.ts`       | Live's countries and Pause state, written by the map card as it opens Visitors by country                                                        |
| `src/features/live/map/`                    | `WorldMap` (Skia; `WorldMap.web.tsx` loads CanvasKit), `mapColors`, `mapGeometry` (fit and tap hit testing), the generated `worldPaths.ts`       |
| `src/ui/LiveDot.tsx`                        | The pulsing dot, shared with the Live chip                                                                                                       |
| `src/demo/live.ts`                          | The seeded demo traffic                                                                                                                          |

## Requests

Each read sends these jobs through `POST query/` with `refresh: blocking` and no status polls, two at a time.
The HogQL text follows `loadQueryData` in `frontend/src/scenes/web-analytics/LiveMetricsDashboard/liveWebAnalyticsMetricsLogic.tsx`, in its unfiltered form: the window goes in `values` (`dateFrom`, `dateTo`), not in `{filters}`.

| Job              | Query                                                                        | Card                             |
| ---------------- | ---------------------------------------------------------------------------- | -------------------------------- |
| `usersPageviews` | Visitor, new visitor and pageview counts per minute                          | Stats, Active users per minute   |
| `paths`          | `TrendsQuery`, `$pageview` by `$pathname`, minute interval, top 10           | Top pages                        |
| `screens`        | The `$screen` form of `paths`: `$screen` by `$screen_name`, no path cleaning | Top screens, in place of `paths` |
| `referrer`       | Pageviews per referring domain per minute, `$direct` when empty              | Top referrers                    |
| `device`         | Unique device counts by `$device_type` across the window                     | Devices                          |
| `browser`        | Unique device counts by `$browser` across the window                         | Browsers                         |
| `geo`            | Unique visitor counts by `$geoip_country_code` across the window             | Countries, the map               |
| `recentEvents`   | The newest 50 events                                                         | Live events                      |
| `usersOnline`    | `uniq(distinct_id)` over the last minute, only when the stats read is off    | Users online                     |

The window starts at the first of the 30 minutes on screen and ends one minute after now to allow for clock skew.
The activity chart and breakdown queries stop at the end of the current minute so totals cover the displayed buckets.
HogQL counts visitors by their first minute in the window and deduplicates across the full window for each breakdown category.
These jobs return counts to the app.
The events query selects `toUnixTimestamp64Milli(timestamp)` instead of the web's `toString(timestamp)`, which is wall-clock time in the project's time zone with no offset.
The `usersPageviews` query leaves out the web's bot column, because Live has no bot cards.
`paths` sets `breakdown_path_cleaning` when the project has path cleaning rules, as the web does.
A read sends `paths` or `screens`, never both. That job runs after the others and takes its form from this read's activity (see [No web traffic](#no-web-traffic)).
The map adds no read: the `geo` answer gives both the Countries breakdown (top six and "Other") and `LiveSnapshot.world`, every country with visitors, which the map and Visitors by country draw.

Two more reads, outside the query budget:

- `GET api/projects/{id}/` once per project and session, for `live_events_token`, `path_cleaning_filters` and `ingested_event`. The server sends the token only when the grant covers `query:read`. While `ingested_event` is false, Live reads it again (see [No web traffic](#no-web-traffic)).
- `GET {live host}/stats` with `Authorization: Bearer <live_events_token>`, every 10 seconds, on US Cloud (`live.us.posthog.com`) and EU Cloud (`live.eu.posthog.com`). It is a plain `fetch` with an 8-second timeout. It answers `users_on_product`.

Users online comes from the HogQL `usersOnline` job instead when the host is not Cloud, the project has no token, or two stats reads in a row fail. It then changes every 30 seconds.

The Live chip on the Web analytics screen reads users online alone: the stats read every 30 seconds, or the `usersOnline` query alone every 30 seconds on the `live` budget when the stats read is off. It reads only while the Web analytics screen is focused and the app is in the foreground, and never runs the jobs above. After a failed read, the chip keeps its last count for 10 seconds, then retries once before showing “Reconnecting…”. It waits up to 5 more seconds for that check, joining a read already in progress. A successful check updates the count without showing a warning. The chip and Live screen pause their pulses and clocks when their screens are hidden or the app leaves the foreground.

## Polling

`LiveController` runs one poller for the 30-second read and one for the 10-second stats read.

- **Reads only while seen.** A poller reads when the screen is focused, the app is in the foreground and the user has not paused. Losing focus stops at once and aborts the read in flight. Live never polls behind another screen.
- **Focus back.** Getting the focus back reads at once when the last data is older than the read interval (30 seconds), or after a failed read. Otherwise the next read comes when that interval ends, so going back and forth between Live and a screen it pushes does not send a full read each time.
- **Background grace.** When the app leaves the foreground, reads stop after 2 seconds, like the web's hidden-tab grace. Coming back within 2 seconds changes nothing. Coming back later reads at once, then polls again.
- **Timed from the end of a read**, so a slow read never overlaps the next.
- **Slower after 10 minutes.** After 10 minutes of polling with no user action, the read comes every 60 seconds instead of 30. Pull to refresh, Try again, Resume, reopening the screen, and coming back to the foreground after reads stopped set it back to 30 seconds and start the 10 minutes again. Scrolling does not count. The pushed screen's status line still says when the last update came. The stats read keeps its 10-second interval.
- **Pause** stops every timer and aborts the read in flight. Resume reads at once, then polls again.
- **Pull to refresh** reads now. While paused it reads once and stays paused.
- **Failures.** A job that fails, or answers with a query that still runs, keeps its card's last value. After a failed read, the status keeps its previous state for 10 seconds, then retries once or joins a read already in progress. If that check fails or has not completed after 5 more seconds, Home's header and the pushed screen's status line show "Reconnecting…" until updates recover. The toast "Couldn't update live data. Retrying…" appears once per failure streak. A successful check cancels the warning. This extra read uses the existing query budget and does not reset the inactivity slowdown. Subsequent reads use the normal interval (30 or 60 seconds), with total failures doubling the delay up to 5 minutes. A first read that fails shows "Couldn't load live data" with Try again.
- **A missing scope** (403 naming `query:read`) reports a Views scope error, so the screen shows the sign-in state.

Visitors by country does not run Live's read. Pushing it takes the focus from Live, so Live's poller stops at once, and the screen runs its own poller (`useLiveWorld`) with the `geo` job alone and the same rules: 30 seconds, 60 after 10 minutes, focus, background grace and backoff.
The map card writes Live's countries and Pause state to `liveWorldStore` as it pushes the screen. Pause cannot change while the screen covers Live. The screen paints those countries first, then reads `geo` at once and every interval after, and clears the store when it closes.
It follows Live's Pause: while Live is paused it reads nothing and says "Paused". It has no Pause button or pull to refresh of its own.
Back on Live, the focus rule above applies: Live reads at once only when its data is older than 30 seconds.

## Budget

Live spends the `live` budget family (`src/api/budget.ts`): 60 requests a minute and 900 an hour, so its polling never empties the Views or replay buckets and theirs never stop Live.
The other families hold 25% of the published budget. Live polls by design, and at 25% a normal session would stop after about half an hour, so Live holds 75% of the published query budget.
The buckets refill all the time, so the hourly bucket gets 15 requests back each minute.
One read is 7 queries, or 8 with the users online count.
In the first 10 minutes a focused screen sends up to 16 queries a minute, 1 more than the refill. After that it sends up to 8 a minute, less than the refill.
So steady polling never empties the hourly bucket, and a focused screen keeps updating for as long as it stays open.
Visitors by country sends 1 query a read, at most 3 in its first minute, while Live sends none.
Many pulls to refresh in a row can still empty the minute bucket. Reads then fail with "Reconnecting…" until the bucket refills.

## Screen

1. Title. On Home the tabs header draws "Live", with the Pause or Resume button (`live-pause`) left of More, and the content has no title row. The pushed screen draws its own title "Live" with a dot: green and pulsing while live, gray when paused or reconnecting, still with reduced motion. Its status line (`live-status`) says "Live · updated 12 s ago", "Paused", "Reconnecting…" or "Loading…", and its Pause or Resume pill (`live-pause`) sits at the right of the title.
2. Paused banner (`live-paused-banner`): "Paused. Tap Resume to catch up." with Resume (`live-banner-resume`).
3. Stats (`live-stats`): Users online, Unique visitors and Pageviews, with the web's tooltips in a toast when a label is tapped. A changed number counts to its new value in 300 ms and flashes blue.
4. Where visitors are (`live-map`): "18 countries · last 30 minutes", a world map, and "🇺🇸 United States leads with 15 visitors". Land is `segmentEmpty`; a country with visitors is blue by its share of the leading country's visitors, with the web's 30% floor toward the land color. The whole card opens Visitors by country; a tap on a country with visitors opens it with that country selected.
5. Active users per minute (`live-activity`): 30 stacked bars, new visitors (green) under returning visitors (blue), as the web draws them. A visitor is new in the first minute of the window that shows them. The line under the chart names the scrubbed minute, or the current one: "21:14 · 18 visitors · 9 pageviews". The last bar is in progress.
6. Top pages and Top referrers (`live-top-pages`, `live-top-referrers`): ten rows with views and their share of the window's pageviews. A row that changes rank slides to its place with a ↑ or ↓ badge that fades after 4 seconds. "Direct / None" is in italics. App only shows Top screens (`live-top-screens`, column "Screen") in place of Top pages, with shares of the listed screen views, and no Top referrers.
7. Breakdown (`live-breakdown`): Devices, Browsers or Countries, with the total and a share bar per row. Devices or Browsers is not offered when its only row is "Unknown", as for app events. With neither and no countries, the card is hidden. Browsers and countries show their top six and an "Other" row. Countries show a flag and a name from the web analytics helper (`countryName`), which uses `Intl.DisplayNames` where the runtime has it and a short list otherwise; codes neither names stay codes. Rows do not open anything, because the web's visitor drill-down is behind a flag.
8. Live events (`live-events`): the newest 50, newest first. Events that arrive after the first read slide in with a short highlight. A tap opens the event sheet (`live-event-sheet`): Person with Copy, URL or Screen, Session with "Watch recording", and "View person on web". Watch recording opens the app's session screen when the session replay flag is on, and the web player otherwise.

Loading shows the skeleton (`live-loading`). Empty cards say "No activity in the last 30 minutes", "No pageviews recorded in the last 30 minutes", "No screen views recorded in the last 30 minutes", "No referrer data in the last 30 minutes", "No device data", "No browser data", "No country data" or "Waiting for events…". A card whose job has not answered yet says "Couldn't load this yet. Live tries again every 30 seconds."

## No web traffic

The state comes from the project read and the last snapshot (`liveProjectState` in `src/model/adapters/live.ts`):

| State        | When                                                                                                                      | Screen                                                                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `not_set_up` | The project read says `ingested_event: false`                                                                             | No Pause. The setup card (`live-not-set-up`), then Meanwhile. The pushed screen's status says "Not receiving events yet", with a gray dot  |
| `quiet`      | Every job answered and the window is empty: no visitor in any minute, no events, empty top lists, every breakdown total 0 | Pause stays. The Quiet card (`live-quiet`), then Meanwhile. The pushed screen's status says "Live · waiting for activity", with a gray dot |
| `app_only`   | No pageviews, and screens: a Top screens list with rows, or a `$screen` event among the newest events                     | The usual cards: Pageviews 0, Top screens, no Top referrers, no Browsers segment                                                           |
| `web`        | Anything else, such as server-side events without pageviews or screens, and while parts of the snapshot are missing       | The usual cards. Server-side events alone show an empty Top pages                                                                          |

A project read that fails counts as unknown, so Live shows what the snapshot says and retries the project read every minute while the screen is visible, as well as on focus and return to the foreground.
`ingested_event` turns true for anything the project ingests, also logs, traces and metrics. Such a project shows Quiet or its cards, not the setup card.

**Top screens.** The top list job runs last in a read. It asks `screens` instead of `paths` when this read's activity has visitors and no pageviews (`livePathsMode`), or the last read's activity when this read's activity job failed. So an app project lists screens from its first read, and no read sends both forms.
`LiveSnapshot.topPagesMode` says which form `topPages` holds, and rank badges compare rows of one form only.
The table labels follow that retained form even when activity changes, until a query for the new form succeeds.

**Quiet.** The Quiet card says "Quiet right now" and "No events in the last 30 minutes. Live keeps checking." The stats, map, chart and list cards are hidden. Polling goes on as usual, so the cards come back with the first event. The 10-second stats read waits while Quiet, because users online are not on screen, and the next 30-second read ends Quiet.

**Not set up.** The setup card says "Install PostHog to see live activity" and "This project has not sent an event yet. Add the web snippet or an SDK and Live fills in within a minute."
"Open setup guide" opens `{host}/project/{id}/onboarding` on the web, where the person picks the web snippet or an SDK. It is disabled with "Not in the demo" in demo mode, and with "Not available over http" when the host is not https. "Open Views" switches to the Views tab.
Live runs no jobs and no stats reads in this state. While the screen is seen, it reads the project again every minute, and on each focus and each return to the foreground, at most once a minute (`PROJECT_RECHECK_MS` in `hooks.ts`). These reads are outside the query budget. A pull reads it at once. When `ingested_event` turns true, the normal poller starts. When a later project read fails, Live keeps the last answer.

**Meanwhile** (`live-meanwhile`): the "Meanwhile" eyebrow and a card with up to two pinned views, in Views order, then "Inbox".
A pin row shows its icon, name and type (or tile name), and, when Views last read a value for it, the number, change pill and a sparkline (`usePinGlance`, shared with the Views list). A tap opens the view (`from=live_meanwhile`).
The Inbox row says "N unread", or "Nothing unread", from the inbox list the app last loaded (`useInboxUnreadCount`), or "Inbox" alone before that, and switches to the Inbox tab.
Meanwhile sends no data reads: pin values, automatic pin displays and the unread count come from the cache. When the pin list was never read in the session, it reads the pin list once (`usePins`, without the re-read on reconnect). With no pins, the card has the Inbox row only.

## Visitors by country

`/views/live-countries[?country={ISO code}]` (`liveCountriesHref`), pushed from the map card with Back only.
The title block is the "Live" eyebrow, "Visitors by country", and a status line with the live dot: "60 visitors in 20 countries · last 30 minutes", "Paused · …", "Reconnecting…" or "Loading…".
The map is full width, up to 40% of the window height and centered, so in landscape the stuck map leaves room for the list. A caption sits under it: the leader and "Tap a country", or the selected country ("🇦🇺 Australia · 5 visitors (6.8%)") with Clear.
The map and caption stick under the chrome while the list scrolls, so a selected row and its outline stay on screen together.
The list (`live-countries-list`) has every country: flag, name, a blue bar scaled to the leading country, and "13 (21.7%)". Rows slide when ranks change, like the top pages rows.
A tap on a country with visitors selects it: an `ink` outline on the map, a tinted row, and the list scrolls the row into view. A tap on a row selects it on the map. A tap on the sea or on a country without visitors does nothing.
A tap on the sea, or inside a country smaller than 12 pt, also tries points up to 12 pt around it, so small countries can be tapped.
A `country` in the route that is not in the screen's first countries selects nothing.
Loading shows the skeleton, a first read that fails shows "Couldn't load live data" with Try again, and no countries say "No country data in the last 30 minutes".

### Map data

`src/features/live/map/worldPaths.ts` is generated. `pnpm map:generate` (`scripts/generate-world-map.mjs`) reads the web's `products/product_analytics/frontend/insights/trends/WorldMap/countryVectors.tsx` and writes one path per ISO 3166-1 alpha-2 code in the source's 2754 × 1200 Robinson viewBox. It joins each country's shapes in absolute coordinates rounded to whole units, so islands keep their place. Run it again when the web's map changes, and commit the result.
The map draws the viewBox from x 90 to 2670 and y 16 to 1172, without the empty Pacific margins. Skia parses the paths on the first draw and keeps them for the app session.

## Analytics

| Event                            | Properties                                                                                                                                                                       |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mobile_live_opened`             | `from` (the `ViewEntry`; `web_analytics` for the chip, `tab` for Home), `chrome`: `tab` or `stack`. The bar counts Home once per tab switch; the pushed screen counts each focus |
| `mobile_live_opened_in_web`      |                                                                                                                                                                                  |
| `mobile_live_error_shown`        | `kind`: `load_failed` or `refresh_failed`, once per streak                                                                                                                       |
| `mobile_live_refreshed`          | `trigger`: `pull` or `resume`                                                                                                                                                    |
| `mobile_live_paused`             | `trigger`: `button` or `background`                                                                                                                                              |
| `mobile_live_resumed`            | `trigger`: `button` or `foreground`                                                                                                                                              |
| `mobile_live_breakdown_changed`  | `breakdown`: `devices`, `browsers` or `countries`                                                                                                                                |
| `mobile_live_event_sheet_opened` | `kind`: `pageview`, `screen` or `other`                                                                                                                                          |
| `mobile_live_event_action_taken` | `action`: `view_person`, `watch_recording`, `copy_distinct_id`                                                                                                                   |
| `mobile_live_map_opened`         | `from`: `card` (the card) or `map_country` (a country on the card's map)                                                                                                         |
| `mobile_live_country_selected`   | `source`: `map` or `row`, on Visitors by country                                                                                                                                 |
| `mobile_live_country_cleared`    | Clear on Visitors by country                                                                                                                                                     |
| `mobile_live_state_shown`        | `state`: `app_only`, `quiet` or `not_set_up`, once per focus for each state                                                                                                      |
| `mobile_live_setup_opened`       | Open setup guide on Not set up                                                                                                                                                   |
| `mobile_live_meanwhile_opened`   | `target`: `view` or `inbox`                                                                                                                                                      |

The chart also sends the shared `mobile_chart_*` events with the `view` context.

## Demo mode

`src/demo/live.ts` writes invented hedgebox.net traffic from a seeded generator, and answers each job in the shape of its query, so demo mode runs the same adapters.
Visitors come and go, page weights drift so ranks swap now and then, and an event arrives every 1.2 to 3.6 seconds. Visitors come from 21 countries, so the map shows 15 or more at a time.
Events are written up to the moment of each read, so nothing moves while paused, and the next read catches up.
One simulator lives for the app session, so reopening Live continues the same traffic.
Users online comes from the HogQL count in demo mode. Watch recording and View person on web are not available in the demo.
The store demo always shows web traffic. In a development build, `EXPO_PUBLIC_DEMO_LIVE_STATE=app_only`, `quiet` or `not_set_up` shows that state instead (`liveDemoState`): app events with screen names and no browser, no events, or a project read that says `ingested_event: false`. See [TESTING.md](TESTING.md).

## Not in v1

- The web's domain and device filters, the city, bot and recent visitor queries, and the visitor drill-down from a breakdown row.
- The event stream (`/events` on the live host). The screen's layout does not depend on the transport.
- The project's time zone on the chart: times are in the device's time zone, like the app's other charts.
- Referrer favicons.
