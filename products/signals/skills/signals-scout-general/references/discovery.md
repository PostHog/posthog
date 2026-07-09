# Discovery: mapping what a project actually uses

The profile and `top_events` are a starting point, not the whole picture. They
enumerate configured entities and the busiest events, but whole products are
invisible to them — session replay, logs, tracing/APM, revenue, and the _state_ of
error tracking all live in data the profile doesn't carry — and the profile lags
products that shipped recently. On a project with no specialist scouts, you're the
only thing watching those surfaces, so confirm what's live yourself.

Two things evolve under you: the **team's** product mix (they adopt new products,
turn others off) and **PostHog's** own offering (new products ship with new MCP
tools). The reliable substrate through both is the **MCP tool surface** — it tracks
what's possible to look at and grows over time. Lean on it: a tool family that
wasn't there last time is a strong hint of a product worth folding into the map.

## One cheap pass, then a durable map you keep current

Discovery is amortized, not repeated every run:

- **No `pattern:general:coverage-map` yet (early runs):** spend this run building
  it. Run the breadth pass below, then write the map.
- **Map exists and is recent:** skip discovery. Read it, pick a live surface, and
  investigate — rotating across surfaces over successive runs.
- **Map is stale (~weekly, or the project clearly changed):** re-sense-check it.
  Re-run the breadth pass, skim the MCP tools for capabilities new since last time,
  and update the parts that drifted. Don't assume last week's map is still complete
  — products appear on both sides.

Stay bounded — discovery is orientation, not investigation. A handful of cheap reads
is enough; you have future runs to go deep.

## Breadth pass: event taxonomy + tool surface

Two cheap reads do most of the work.

**1. The event taxonomy.** `read-data-schema` (events) returns the event names this
team captures — and the names alone reveal which products are live:

| Signal in the event taxonomy               | Product that's live              |
| ------------------------------------------ | -------------------------------- |
| `$exception`                               | Error tracking                   |
| `$ai_generation` / `$ai_span` / `$ai_*`    | LLM analytics (AI observability) |
| `$pageview` / `$pageleave` / `$web_vitals` | Web analytics                    |
| `$snapshot` / session activity             | Session replay                   |
| `$feature_flag_called`                     | Feature flags                    |
| `$csp_violation`                           | CSP reporting                    |
| high-volume custom events                  | Product analytics                |

**2. The MCP tool surface.** Skim the available tools (the MCP's own `search` /
`tools` discovery). New `query-*` or product tool families that weren't there before
are how you notice PostHog shipped a product you don't yet have a lens for — pick it
up and probe whether this team uses it.

Pair both with the profile's configured-entity sections (dashboards, flags,
experiments, surveys, pipelines, warehouse sources, cohorts): together they tell you
what's "configured," what's "emitting," and what's "now possible to query."

## Confirm the surfaces the taxonomy can't show

A few products don't announce themselves cleanly in the event list — probe them
directly when the breadth pass hints they might be present, one cheap read each:

- **Error tracking** — `query-error-tracking-issues-list` (issue count + recent
  activity; `$exception` volume alone doesn't tell you issue state).
- **Session replay** — `query-session-recordings-list` (are sessions recording, and
  how recently?).
- **Logs** — `query-logs` (any volume, by service / severity).
- **Tracing / APM** — `query-apm-spans` (OTel spans present?).
- **LLM analytics** — `query-llm-traces-list` (live traces, not just `$ai_*` counts).
- **Revenue** — revenue events in the taxonomy, or warehouse Stripe sources in the
  profile.
- **Data warehouse** — the profile's `external_data_sources`; deeper structure via
  `read-data-warehouse-schema`.

When you hit a surface no tool seems to cover, that's worth a `mcp-gap:` scratchpad
note (see [conventions.md](conventions.md)) — a capability the fleet may want later.

## Write the coverage map

Persist what you found as a single durable entry, overwriting it in place
(`pattern:general:coverage-map`). Make it future-run actionable: each live product
with a rough volume / last-seen and a one-line "what's worth watching here," an
explicit list of products that are _absent_ so future runs don't re-probe them, and
the date you last sense-checked it. Example shape:

```text
key:     pattern:general:coverage-map
content: "2026-06-22 discovery (team has NO specialist scouts — general owns all).
         LIVE: error_tracking (~12k $exception/day, 40 issues, watch new-issue
         bursts); web_analytics ($pageview ~80k/day, 3 channels); session_replay
         (recording, ~1.5k/day); feature_flags (22 active). ABSENT (skip until a
         refresh): llm_analytics (no $ai_*), apm (no spans), revenue (no Stripe
         source), surveys, csp. Last full sense-check 2026-06-22; re-check ~weekly
         or on a visible project change / new MCP tool family."
```

Future runs read this first, skip the absent products, and rotate attention across
the live ones — that's what turns a once-a-day generalist into something that covers
the whole project over a week instead of re-checking one corner, and keeps up as
both the team and PostHog change.
