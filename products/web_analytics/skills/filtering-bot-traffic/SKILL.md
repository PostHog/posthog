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

These read the user agent for you (falling back from `$raw_user_agent` to `$user_agent`),
so you don't pass anything in. Available wherever you pick an event property.

| Property                 | Value                                                                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$virt_is_bot`           | boolean — `true` for bots / crawlers / automation                                                                                                                                              |
| `$virt_traffic_type`     | `Regular`, `AI Agent`, `Bot`, or `Automation`                                                                                                                                                  |
| `$virt_traffic_category` | finer category, e.g. `ai_crawler`, `ai_search`, `ai_assistant`, `search_crawler`, `seo_crawler`, `social_crawler`, `monitoring`, `http_client`, `headless_browser`, `no_user_agent`, `regular` |
| `$virt_bot_name`         | display name, e.g. `Googlebot`, `GPTBot`, `ClaudeBot`                                                                                                                                          |
| `$virt_bot_operator`     | company behind the bot, e.g. `Google`, `OpenAI`, `Anthropic`                                                                                                                                   |

### HogQL functions (raw SQL)

Pass the user agent explicitly. Use `coalesce(nullIf(properties.$raw_user_agent, ''), properties.$user_agent)`
to cover both server-side (`$raw_user_agent`) and JS SDK (`$user_agent`) captures. The `nullIf`
keeps an empty `$raw_user_agent` from shadowing a real `$user_agent` and being misread as a bot —
this mirrors the expression the virtual properties use internally.

| Function                 | Returns                                                                      |
| ------------------------ | ---------------------------------------------------------------------------- |
| `isLikelyBot(ua)`        | `true` if the UA matches a bot/automation pattern (empty UA counts as a bot) |
| `getTrafficType(ua)`     | `AI Agent` / `Bot` / `Automation` / `Regular`                                |
| `getTrafficCategory(ua)` | subcategory; `regular` for humans                                            |
| `getBotType(ua)`         | same subcategory but empty string for humans — handy for filtering           |
| `getBotName(ua)`         | bot name; empty for humans                                                   |
| `getBotOperator(ua)`     | operator/company; empty for humans                                           |

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

Drop it into any TrendsQuery / FunnelsQuery / etc. `properties`. Visitor, session, and
pageview counts then reflect human traffic only, without changing stored data.

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
    AND NOT isLikelyBot(coalesce(nullIf(properties.$raw_user_agent, ''), properties.$user_agent))

-- top bots by hits
SELECT
    getBotName(coalesce(nullIf(properties.$raw_user_agent, ''), properties.$user_agent)) AS bot,
    getBotOperator(coalesce(nullIf(properties.$raw_user_agent, ''), properties.$user_agent)) AS operator,
    count() AS hits
FROM events
WHERE event = '$pageview'
    AND isLikelyBot(coalesce(nullIf(properties.$raw_user_agent, ''), properties.$user_agent))
GROUP BY bot, operator
ORDER BY hits DESC
```

## Seeing bots that don't run JavaScript

Most crawlers and AI agents never execute JS, so `posthog-js` never fires a `$pageview` for
them — they're invisible to client-side analytics. To measure them, the project must forward
server access logs as `$http_log` events carrying `$raw_user_agent`. If a user asks "why
don't I see GPTBot when I know it's crawling us?", the answer is almost always: no `$http_log`
ingestion. Point them at server-side capture (the **Vercel logs** source, an edge worker, or
the capture API) before building bot insights.

## Gotchas

- **Needs a captured user agent.** Classification is computed at query time from the event's
  `$raw_user_agent` / `$user_agent`, so it works on any historical event — there's no need to
  restrict `dateRange.date_from`. The one requirement is that a user agent was captured; events
  from sources that never set one can't be classified (and empty UAs fall through to
  `Automation` / `no_user_agent`, below).
- **`isLikelyBot` is "likely".** Detection is a user-agent heuristic — some bots spoof
  real browser UAs, and some legit tools use bot-like ones. Treat it as best-effort, not
  ground truth.
- **Empty user agent = bot.** Requests with no UA (server-to-server, misconfigured SDKs)
  classify as `Automation` / `no_user_agent`, so `isLikelyBot` returns `true`.
- **Don't silently drop the host filter.** If the user is scoped to one domain, inherit
  `$host` in `properties` — leaving it out changes the answer.
- **Bot definitions evolve.** The detected-bot list changes over time, so re-running the
  same query later can classify older events differently. Definitions live in
  `products/web_analytics/backend/hogql_queries/bot_definitions.py`.
