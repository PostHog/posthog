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

These read `$raw_user_agent` and `$ip` for you, so you don't pass anything in — the IP
signal catches crawlers that use real browser user agents from operator-published IP
ranges (e.g. Google's mobile rendering service). Available wherever you pick an event
property. (`$user_agent` without `$raw_user_agent` is intentionally not read — it has no
materialized column; such events classify via the empty-UA path.)

| Property                 | Value                                                                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `$virt_is_bot`           | boolean — `true` for bots / crawlers / automation                                                                                                                                              |
| `$virt_traffic_type`     | `Regular`, `AI Agent`, `Bot`, or `Automation`                                                                                                                                                  |
| `$virt_traffic_category` | finer category, e.g. `ai_crawler`, `ai_search`, `ai_assistant`, `search_crawler`, `seo_crawler`, `social_crawler`, `monitoring`, `http_client`, `headless_browser`, `no_user_agent`, `regular` |
| `$virt_bot_name`         | display name, e.g. `Googlebot`, `GPTBot`, `ClaudeBot`                                                                                                                                          |
| `$virt_bot_operator`     | company behind the bot, e.g. `Google`, `OpenAI`, `Anthropic`                                                                                                                                   |

### HogQL functions (raw SQL)

Pass the user agent explicitly — `properties.$raw_user_agent`. All functions also take an
optional client IP (matched against operator-published bot IP ranges) and an optional Web
Bot Auth Signature-Agent value (matched against known signed agents like ChatGPT agent):
`isLikelyBot(ua[, ip[, signature_agent]])`. Signal precedence is UA, then signature
agent, then IP.

| Function                              | Returns                                                            |
| ------------------------------------- | ------------------------------------------------------------------ |
| `isLikelyBot(ua[, ip[, sig]])`        | `true` if any signal matches a bot (empty UA counts as a bot)      |
| `getTrafficType(ua[, ip[, sig]])`     | `AI Agent` / `Bot` / `Automation` / `Regular`                      |
| `getTrafficCategory(ua[, ip[, sig]])` | subcategory; `regular` for humans                                  |
| `getBotType(ua[, ip[, sig]])`         | same subcategory but empty string for humans — handy for filtering |
| `getBotName(ua[, ip[, sig]])`         | bot name; empty for humans                                         |
| `getBotOperator(ua[, ip[, sig]])`     | operator/company; empty for humans                                 |

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
-- human pageviews only (UA + IP signals, same as $virt_is_bot)
SELECT count() AS human_pageviews
FROM events
WHERE event = '$pageview'
    AND NOT isLikelyBot(properties.$raw_user_agent, properties.$ip)

-- top bots by hits
SELECT
    getBotName(properties.$raw_user_agent, properties.$ip) AS bot,
    getBotOperator(properties.$raw_user_agent, properties.$ip) AS operator,
    count() AS hits
FROM events
WHERE event = '$pageview'
    AND isLikelyBot(properties.$raw_user_agent, properties.$ip)
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

- **Needs a captured `$raw_user_agent`.** Classification is computed at query time, so it
  works on any historical event — no need to restrict `dateRange.date_from`. Events whose
  source never sets `$raw_user_agent` (including SDKs that only send `$user_agent`) fall
  through to `Automation` / `no_user_agent`, below. The IP signal additionally needs
  `properties.$ip`; the signature-agent signal needs a server forwarding the
  `Signature-Agent` header as `$signature_agent` (only reachable via the explicit
  three-argument functions, not the virtual properties).
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
