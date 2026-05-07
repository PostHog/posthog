---
name: exploring-live-traffic
description: 'Inspects PostHog Web analytics Live tab data — current users online, last-30-minutes pageviews, top pages, referrers, devices, browsers, countries, bot traffic, and the per-minute bot/users charts. Use when the user asks "who is on my site right now?", "what is happening live?", "what bots are crawling me?", asks about the "live tab" / "live dashboard", wants live numbers (last 30 min), or wants help filtering or drilling into the live view. Also covers building product-analytics insights that mirror what the tiles show.'
---

# Exploring Web analytics live traffic

The Web analytics Live tab (`/web/live`) shows real-time activity over a 30-minute sliding
window plus a 60-second "users online" count. It is the place to answer "what is happening
on my site right now?" — pageviews, named bots, devices, geo, top paths, top referrers, and
a live event feed.

This skill teaches you (the agent) how to:

- recognize a request that belongs on the Live tab
- read the tile model (what each card shows, where the data comes from)
- manipulate the only filter that exists (host)
- build product-analytics insights that match a Live tile when the user wants
  longer time ranges or deeper drill-down than the live window offers

The Live tab is **not** a HogQL playground — its data comes from a livestream backed by
short HogQL backfills. When the user wants to query "right now" data with HogQL, point
them at the tab; when they want historical breakdowns, build an insight with the patterns
below.

## When to use this skill

Use this skill when the user:

- asks "who is on my site right now?", "what is happening live?", "show me live traffic"
- mentions the "Live" tab, the "Live dashboard", or the live page (`/web/live`)
- asks about live bot traffic ("which bots are crawling me?", "is GPTBot scraping us?")
- wants to filter live traffic by domain / host
- wants to compare what they see on the Live tab to a longer time window — e.g.
  "the live tab shows GPTBot is hammering us, can you give me a 7-day chart of that?"

Do not use this skill for non-realtime web analytics work — for that, use the standard
Web analytics tab (`/web`).

## Tab structure

URL: `/web/live`

The tab has two filter affordances and a grid of tiles. Date range is **fixed**: 30 minutes
sliding window for everything except "Users online" (last 60 seconds).

### Filters

There is only **one** filter on the live tab: the host (domain) selector.

- It comes from `webAnalyticsFilterLogic.selectedHost`.
- It is **shared with the rest of Web analytics**, so changing it on `/web` propagates to
  `/web/live` and vice-versa.
- It is gated by feature flag `WEB_ANALYTICS_LIVE_DOMAIN_FILTER`. If the flag is off, no
  host filter UI is rendered and all tiles show data across every domain.
- Setting the host filter narrows: the SSE stream, the HogQL backfill queries (so the
  initial 30 min is host-scoped), and the "users online" count.
- There is no date picker, no compare control, no property filters, no test-account
  filter on the Live tab. Do not promise the user controls that don't exist.

When the user asks "filter live traffic by domain `<host>`", direct them to the **Domain**
selector at the top of the Live tab. There is no URL param to set it directly — it
persists in `localStorage` via `webAnalyticsFilterLogic`.

### Stat cards (top strip)

| Card            | What                                            | Window |
| --------------- | ----------------------------------------------- | ------ |
| Users online    | Distinct device IDs seen in the last 60 seconds | 60s    |
| Unique visitors | Distinct device IDs in the last 30 min          | 30m    |
| Pageviews       | `$pageview` count in the last 30 min            | 30m    |

### Content cards

| Card                    | What                                                | Notes                                                                                           |
| ----------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Active users per minute | Bar chart, new vs returning visitors                | last 30 min                                                                                     |
| Top pages               | Animated leaderboard, `$pathname` + view count      | top 10, 30 min                                                                                  |
| Top referrers           | Animated leaderboard, `$referring_domain`           | top 10, 30 min                                                                                  |
| Devices                 | Breakdown bars, `$device_type`                      | top 6 + Other                                                                                   |
| Browsers                | Breakdown bars with logos, `$browser`               | top 6 + Other                                                                                   |
| Top countries           | Breakdown bars, `$geoip_country_code`               | top 6 + Other; replaced by a Country/City tab card if `WEB_ANALYTICS_LIVE_CITY_BREAKDOWN` is on |
| Bot requests per minute | Bar chart, bot events / minute                      | flag `WEB_ANALYTICS_BOT_ANALYSIS`                                                               |
| Bot traffic             | Named bots ranked by event share, with category tag | flag `WEB_ANALYTICS_BOT_ANALYSIS`; rows are clickable and open an insight for that specific bot |
| Countries (world map)   | SVG world map heat                                  | flag `WEB_ANALYTICS_LIVE_MAP`                                                                   |
| Live events             | Streamed event feed (event, person, URL, timestamp) | last 50 events                                                                                  |

Every tile (except the live event feed and world map) has an "Open as new insight"
button that opens a 7-day Trends query in product analytics. The bot traffic tile rows
are also individually clickable — clicking a bot row opens a single-bot trend.

## Bot detection model

Bots are detected server-side. Three virtual properties are attached to the event before
it lands in ClickHouse:

- `$virt_is_bot` — boolean, `true` if classified as a bot
- `$virt_bot_name` — string, the bot's display name (e.g. `Googlebot`, `GPTBot`,
  `Claude`, `Lighthouse`, `HeadlessChrome`)
- `$virt_traffic_category` — string, the category key:
  `ai_crawler`, `ai_search`, `ai_assistant`, `search_crawler`, `seo_crawler`,
  `social_crawler`, `monitoring`, `http_client`, `headless_browser`, `no_user_agent`,
  `regular`

The Live bot tiles count "bot-eligible" events: `$pageview`, `$pageleave`, `$screen`,
`$http_log`, `$autocapture`. `$http_log` is included because most bots emit server-side
HTTP logs rather than JS pageviews.

## Building product-analytics queries that mirror the Live tab

When the user wants a longer window, a saved insight, a dashboard tile, or to share a
view of what's on the Live tab, build a Trends insight. The "Open as new insight"
buttons in the UI use exactly these recipes:

### Bot traffic breakdown (matches the bot tile header)

A single chart of all bots over time, broken down by name. This is the canonical
"who's crawling me?" view.

```json
{
  "kind": "TrendsQuery",
  "interval": "hour",
  "dateRange": { "date_from": "-7d" },
  "series": [
    {
      "kind": "GroupNode",
      "custom_name": "Requests",
      "operator": "OR",
      "math": "total",
      "nodes": [
        { "kind": "EventsNode", "event": "$pageview", "math": "total" },
        { "kind": "EventsNode", "event": "$pageleave", "math": "total" },
        { "kind": "EventsNode", "event": "$screen", "math": "total" },
        { "kind": "EventsNode", "event": "$http_log", "math": "total" },
        { "kind": "EventsNode", "event": "$autocapture", "math": "total" }
      ]
    }
  ],
  "properties": [{ "key": "$virt_is_bot", "value": ["true"], "operator": "exact", "type": "event" }],
  "breakdownFilter": {
    "breakdown": "$virt_bot_name",
    "breakdown_type": "event",
    "breakdown_limit": 25
  },
  "trendsFilter": { "display": "ActionsBarValue" }
}
```

### Single bot drill-down (matches a clicked bot row)

```json
{
  "kind": "TrendsQuery",
  "interval": "hour",
  "dateRange": { "date_from": "-7d" },
  "series": [
    /* same combined "Requests" GroupNode as above */
  ],
  "properties": [
    { "key": "$virt_is_bot", "value": ["true"], "operator": "exact", "type": "event" },
    { "key": "$virt_bot_name", "value": ["GPTBot"], "operator": "exact", "type": "event" },
    { "key": "$virt_traffic_category", "value": ["ai_crawler"], "operator": "exact", "type": "event" }
  ],
  "trendsFilter": { "display": "ActionsLineGraph" }
}
```

The category filter is optional — include it when the user asks about a specific
bot+category combo (`Lighthouse · headless_browser` is a different signal from
`Lighthouse · monitoring`).

### Bot category breakdown (matches the bot events chart tile)

Use breakdown by `$virt_traffic_category` instead of `$virt_bot_name` when the user
wants "AI crawlers vs SEO crawlers vs everything else" rather than per-bot rows.

### Top pages / referrers / devices / browsers / countries

For non-bot tiles, use `$pageview` with `math: unique_users`, breakdown by the
underlying property:

| Tile          | breakdown property    | display           |
| ------------- | --------------------- | ----------------- |
| Top pages     | `$pathname`           | `ActionsBarValue` |
| Top referrers | `$referring_domain`   | `ActionsBarValue` |
| Devices       | `$device_type`        | `ActionsPie`      |
| Browsers      | `$browser`            | `ActionsPie`      |
| Countries     | `$geoip_country_code` | `WorldMap`        |

Always inherit the live tab's host filter when the user is asking about a specific
domain — add `{ "key": "$host", "value": ["<host>"], "operator": "exact", "type": "event" }`
to `properties`.

### Defaults to use

- `dateRange.date_from`: `-7d` unless the user names a window — the live view itself
  is 30 min, but the user is almost always asking about a longer window when they
  request an insight version.
- `interval`: `hour` for 7-day windows, `minute` only for windows under a day,
  `day` for windows beyond 14 days.
- Always inherit the host filter when one is set on the Live tab. Don't drop it
  silently — that changes the answer.

## Common requests and the right move

| User says                                                 | Right move                                                                                                                                                |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "What's happening on the site right now?"                 | Send them to `/web/live`                                                                                                                                  |
| "Filter live traffic to `example.com`"                    | Use the Domain selector at top of `/web/live`                                                                                                             |
| "Show me bots crawling us in the last 30 min"             | `/web/live` → Bot traffic tile                                                                                                                            |
| "Show me bots crawling us this week"                      | Build the "Bot traffic breakdown" insight above with `date_from: -7d`                                                                                     |
| "How much is GPTBot hitting us?"                          | Build the "Single bot drill-down" insight, set `$virt_bot_name` to `GPTBot`                                                                               |
| "Why is the live tab showing X but my dashboard shows Y?" | The live tab is a 30-min sliding window over events; dashboards aggregate over the picked range. They are not directly comparable beyond the last 30 min. |
| "Add a date range to the live tab"                        | The Live tab has no date picker — for ranges, build a Trends insight using the patterns above                                                             |
| "Filter live traffic by browser / device / country"       | Not supported — only the host filter exists. Build a Trends insight with the relevant breakdown + filter instead                                          |

## Gotchas

- Bot virtual properties (`$virt_*`) only exist on events processed by the bot
  classification step. They are not retroactive — events from before the classifier
  shipped will not have them. Keep `dateRange.date_from` within the last few months
  for reliable bot results.
- `$http_log` events come from server-side log capture, not from `posthog-js`. If a
  project does not emit `$http_log`, bots that don't run JS (most crawlers) will be
  invisible to the bot tiles.
- The 30-minute window is a sliding aggregation over an in-memory buffer in the
  browser — refreshing the page replays the backfill HogQL, not the SSE stream. Do
  not interpret a brief "0" right after page load as a real drop.
- The host filter strips the protocol — pass `example.com`, not `https://example.com`.
- Tile order is persisted per-team in `localStorage` (under feature flag
  `WEB_ANALYTICS_LIVE_EDIT_LAYOUT`). If a user's layout looks different from yours,
  it is not a bug.
