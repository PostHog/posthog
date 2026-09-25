---
name: filtering-bot-traffic
description: 'Identify, measure, and exclude bot / crawler / AI-agent traffic in PostHog web and product analytics using the traffic classification surface (the isLikelyBot / getTrafficType HogQL functions and the $virt_* virtual properties). Use when the user asks to "exclude bots", "filter out crawlers", "remove bot traffic from my numbers", "how much of my traffic is bots / AI crawlers", "is GPTBot / ChatGPT / Claude hitting my site", "break down traffic by human vs bot", or wants clean human-only counts in an insight or dashboard. For the real-time Live tab bot tiles, use exploring-live-traffic instead.'
---

# Filtering and measuring bot traffic

PostHog classifies every request by user agent so you can tell humans apart from bots,
crawlers, and AI agents anywhere HogQL runs — the SQL editor, insights, trends, and Web
analytics breakdowns. This skill teaches you (the agent) how to use that classification to:

- exclude bots so analytics reflect human traffic only
- measure how much traffic is automated, and which bots / operators are responsible
- separate AI-agent traffic (worth measuring) from noise (worth dropping)
- pick the right surface — virtual properties for the insight builder, functions for raw SQL

For real-time ("right now", last 30 min) bot questions and the Live tab tiles, use the
**exploring-live-traffic** skill instead. This skill is for historical windows, saved
insights, dashboards, and filtering.

## When to use this skill

Use it when the user wants to:

- exclude or filter out bots ("remove bots from my pageviews", "humans only")
- quantify automated traffic ("what % of traffic is bots?", "how much is AI crawlers?")
- find which bots hit them ("which crawlers visit us?", "is ChatGPT reading our docs?")
- break a trend down by traffic type or bot name
- measure AI-agent / AI-search traffic specifically (AEO / answer-engine visibility)

Do **not** use it for the Live tab, real-time numbers, or the per-minute bot charts —
that is exploring-live-traffic.

## The classification surface

Two equivalent ways to reach the same classification. Prefer **virtual properties** in the
insight builder and filters; use **functions** in hand-written SQL or when you need a value
the virtual properties don't expose.

### Virtual properties (insight builder, filters, breakdowns)

These read `$raw_user_agent` for you, so you don't pass anything in. Available wherever you
pick an event property. There is no fallback to `$user_agent`: that property has no
materialized column and almost no event carries it, so an event without `$raw_user_agent` is
classified as having no user agent at all. Read **Events with no user agent count as bots**
below before you use any of them as a filter.

| Property                 | Value                                                                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$virt_is_bot`           | boolean — `true` for bots / crawlers / automation                                                                                                                                              |
| `$virt_traffic_type`     | `Regular`, `AI Agent`, `Bot`, or `Automation`                                                                                                                                                  |
| `$virt_traffic_category` | finer category, e.g. `ai_crawler`, `ai_search`, `ai_assistant`, `search_crawler`, `seo_crawler`, `social_crawler`, `monitoring`, `http_client`, `headless_browser`, `no_user_agent`, `regular` |
| `$virt_bot_name`         | display name, e.g. `Googlebot`, `GPTBot`, `ClaudeBot`                                                                                                                                          |
| `$virt_bot_operator`     | company behind the bot, e.g. `Google`, `OpenAI`, `Anthropic`                                                                                                                                   |

### HogQL functions (raw SQL)

Pass the user agent explicitly. Use `properties.$raw_user_agent`, which is the expression the
virtual properties use internally. Do not reach for `properties.$user_agent`: almost no event
carries it, so every row reads as an empty user agent and classifies as a bot.

| Function                 | Returns                                                               |
| ------------------------ | --------------------------------------------------------------------- |
| `isLikelyBot(ua)`        | `true` if the UA matches a bot/automation pattern, or the UA is empty |
| `getTrafficType(ua)`     | `AI Agent` / `Bot` / `Automation` / `Regular`                         |
| `getTrafficCategory(ua)` | subcategory; `regular` for humans                                     |
| `getBotType(ua)`         | same subcategory but empty string for humans — handy for filtering    |
| `getBotName(ua)`         | bot name; empty for humans                                            |
| `getBotOperator(ua)`     | operator/company; empty for humans                                    |

## Events with no user agent count as bots

`isLikelyBot` matches the empty string, so **every event without a `$raw_user_agent` is a bot**,
and `$virt_traffic_type` reports it as `Automation`. That is right for web traffic, where a
request with no user agent is almost always a script, but it also sweeps in every event that was
never a web request: server-side SDK captures, and any other source that does not set a user
agent. `$virt_is_bot` is the same expression, so it gives the same answer.

On a project that mixes web and non-web capture this is a large share of all events, so a plain
`$virt_is_bot = false` filter can move pageview and visitor counts a long way without the user
expecting it. Before you present a bot-filtered number:

1. Check how much of the range has no user agent, so you know what the filter will remove:

   ```sql
   SELECT
       empty(ifNull(properties.$raw_user_agent, '')) AS no_user_agent,
       count() AS events
   FROM events
   WHERE timestamp > now() - INTERVAL 7 DAY
   GROUP BY no_user_agent
   ```

2. To keep only events that carry a user agent, add this guard alongside the bot filter. It
   reads the stored `$raw_user_agent`, so it is not a proof of browser origin: it also drops a
   browser event whose user agent was stripped, and keeps a non-browser capture that set one.
   Scope to a web event or a known web source when the count has to be web-only.

   ```json
   [
     { "key": "$raw_user_agent", "operator": "is_set", "type": "event" },
     { "key": "$virt_is_bot", "value": ["false"], "operator": "exact", "type": "event" }
   ]
   ```

3. Say which population the number reflects. "Events with a stored user agent", "web
   traffic", and "everything not classified as a bot" are three different groups.

Cookieless events are a separate case. The user agent is used at capture time and then stripped,
so those events provably had one. PostHog is rolling out a modifier that classifies them as
regular traffic, so they may or may not be counted as bots on a given project. The
`$raw_user_agent` guard drops them either way, because the stored property is gone.

## Traffic types — what to keep vs drop

`getTrafficType` / `$virt_traffic_type` sorts every request into four buckets. The default
move differs per bucket — don't treat them all as noise:

| Type         | What it is                                                                              | Default move                                                                 |
| ------------ | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `Regular`    | Human visitors                                                                          | Keep                                                                         |
| `AI Agent`   | AI crawlers, AI search, AI assistants (GPTBot, ClaudeBot, PerplexityBot, ChatGPT-User)  | Often **measure**, don't drop — these are how AI tools find and cite content |
| `Bot`        | Search crawlers, SEO tools, social previews, monitoring (Googlebot, AhrefsBot, Pingdom) | Exclude from human metrics; track separately for SEO                         |
| `Automation` | HTTP clients and headless browsers (curl, python-requests, Puppeteer)                   | Usually noise — exclude                                                      |

## Recipes

### Exclude bots from an insight (humans only)

Add a property filter `$virt_is_bot` `exact` `false`:

```json
{ "key": "$virt_is_bot", "value": ["false"], "operator": "exact", "type": "event" }
```

Drop it into any TrendsQuery / FunnelsQuery / etc. `properties`. This changes the counts
only, not the stored data.

This also drops every event with no stored user agent, which on most projects means all
non-web capture. Pair it with `$raw_user_agent` `is_set` to keep only events that carry a
user agent, and see **Events with no user agent count as bots** above.

To exclude a narrower slice (e.g. keep AI agents but drop monitoring + automation), filter
on `$virt_traffic_type` or `$virt_traffic_category` with `operator: is_not` instead.

### What share of traffic is automated

Break a pageview trend down by `$virt_traffic_type`:

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }],
  "breakdownFilter": { "breakdown": "$virt_traffic_type", "breakdown_type": "event" },
  "trendsFilter": { "display": "ActionsBarValue" }
}
```

### Which bots / operators are hitting us

Filter to bots and break down by name (or `$virt_bot_operator` for company-level):

```json
{
  "kind": "TrendsQuery",
  "dateRange": { "date_from": "-30d" },
  "series": [{ "kind": "EventsNode", "event": "$pageview", "math": "total" }],
  "properties": [{ "key": "$virt_is_bot", "value": ["true"], "operator": "exact", "type": "event" }],
  "breakdownFilter": { "breakdown": "$virt_bot_name", "breakdown_type": "event", "breakdown_limit": 25 },
  "trendsFilter": { "display": "ActionsBarValue" }
}
```

### Measure AI-agent traffic specifically

Filter `$virt_traffic_type` `exact` `AI Agent`, break down by `$virt_bot_operator` to see
which tools (OpenAI, Anthropic, Perplexity, …) read your site and which pages they hit.

### Raw SQL equivalents

```sql
-- human pageviews only
SELECT count() AS human_pageviews
FROM events
WHERE event = '$pageview'
    AND NOT isLikelyBot(properties.$raw_user_agent)

-- top bots by hits, events with a user agent only
SELECT
    getBotName(properties.$raw_user_agent) AS bot,
    getBotOperator(properties.$raw_user_agent) AS operator,
    count() AS hits
FROM events
WHERE event = '$pageview'
    AND notEmpty(ifNull(properties.$raw_user_agent, ''))
    AND isLikelyBot(properties.$raw_user_agent)
GROUP BY bot, operator
ORDER BY hits DESC
```

## Adding a bot PostHog doesn't know yet

The built-in list only covers self-declared user agents PostHog already knows. When a
scraper matters to a project but isn't detected — an internal load test, a partner
integration, a niche crawler — add a **custom bot rule** instead of waiting for the
built-in list to catch up. Rules extend the same classification surface, so `Is bot`
(`isLikelyBot`), `Bot name`, and `Traffic category` reflect them everywhere HogQL runs.

A rule matches one event property — the user agent by default, but also `$ip`, `$lib`,
`$host`, `$pathname`, `$current_url`, `$browser`, `$os`, `$browser_language`,
`$screen_width`, `$screen_height`, `$geoip_country_code`, `$referrer`, or
`$referring_domain` — using `contains` (case-insensitive substring), `regex` (RE2), or
`cidr` (an IP range, only valid with `$ip`). Set `name` to the label reported by `Bot
name`, and optionally `category` to a built-in category like `ai_crawler` to relabel the
traffic type.

Three ways to manage rules:

- **Settings UI** — Settings → Environment → Custom bots.
- **MCP tools** — `web-analytics-bot-rules-list`, `web-analytics-bot-rules-create`,
  `web-analytics-bot-rules-destroy`. Prefer these when driving PostHog through an agent.
- **REST API** — `GET/POST /api/projects/{project_id}/web_analytics_bot_rules/` and
  `DELETE /api/projects/{project_id}/web_analytics_bot_rules/{id}/`.

Listing is open to project members; creating and deleting require a **project admin**
(they mutate the admin-only `modifiers` team setting). A rule whose pattern can't run is
rejected on save, so a bad rule can never take down the project's classification queries.

## Seeing bots that don't run JavaScript

Most crawlers and AI agents never execute JS, so `posthog-js` never fires a `$pageview` for
them — they're invisible to client-side analytics. To measure them, the project must forward
server access logs as `$http_log` events carrying `$raw_user_agent`. If a user asks "why
don't I see GPTBot when I know it's crawling us?", the answer is almost always: no `$http_log`
ingestion. Point them at server-side capture (the **Vercel logs** source, an edge worker, or
the capture API) before building bot insights.

## Gotchas

- **Needs a captured user agent.** Classification is computed at query time from the event's
  `$raw_user_agent`, so it works on any historical event and there's no need to restrict
  `dateRange.date_from`. The one requirement is that a user agent was captured.
- **`isLikelyBot` is "likely".** Detection is a user-agent heuristic. Some bots spoof real
  browser UAs, and some legit tools use bot-like ones. Treat it as best-effort, not ground
  truth.
- **Don't silently drop the host filter.** If the user is scoped to one domain, inherit
  `$host` in `properties` — leaving it out changes the answer.
- **Bot definitions evolve.** The detected-bot list changes over time, so re-running the
  same query later can classify older events differently.
