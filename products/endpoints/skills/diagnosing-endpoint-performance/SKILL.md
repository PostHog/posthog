---
name: diagnosing-endpoint-performance
description: >
  Diagnose why a PostHog endpoint is slow or expensive and propose a concrete fix — bump the cache
  TTL, enable materialisation, restructure variables, or rewrite the query. Use when the user says
  "this endpoint is slow", "my endpoint times out", "we're hitting the cost cap on this one", or
  asks "should I materialise this?". Focuses on a single named endpoint, not a project-wide audit.
---

# Diagnosing endpoint performance

This skill walks through a specific endpoint that is slow, expensive, or unreliable, and produces
a concrete recommendation. It is the deep-dive counterpart to `auditing-endpoints` (which finds
candidates).

## When to use this skill

- "This endpoint is slow / timing out"
- "Why is my endpoint hitting the cost cap?"
- "Should I materialise X?"
- An endpoint surfaced from `auditing-endpoints` as a failing materialisation or expensive caller
- The user has a specific endpoint in mind and wants advice

If the question is project-wide ("what should I clean up?"), use `auditing-endpoints` first.

## Available tools

| Tool                                | Purpose                                                                                        |
| ----------------------------------- | ---------------------------------------------------------------------------------------------- |
| `endpoint-get`                      | Full endpoint config: query, current version, `data_freshness_seconds`, materialisation status |
| `endpoint-versions`                 | History of every version (query + materialisation state); which version is current             |
| `endpoint-materialization-status`   | Whether materialisation is eligible, current state, last run, last error                       |
| `endpoints-materialization-preview` | What the materialised query would look like, plus the rejection reason if ineligible           |
| `endpoints-last-execution-times`    | When was it last called (endpoint-level sanity-check that it is in active use)                 |
| `execute-sql`                       | Query `query_log` for endpoint-level call frequency and per-call duration/bytes                |

## The decision tree

When deciding what to recommend, walk these in order — the first one that applies is the cheapest
fix.

### Step 1 — Is it cached at all?

Fetch the endpoint and look at `data_freshness_seconds` (it sets both the cache TTL and, when
materialised, the refresh cadence). If the user's traffic
calls the same parameters repeatedly within that window, every call after the first is a cache
hit and effectively free.

- TTL is at the default (24h / 86400s) and the data really doesn't need fresher than that →
  done, no change needed.
- TTL is at the 900s floor (15 min) and the user is hitting the endpoint many times per minute →
  bump the TTL. This is almost always the cheapest first move. (`data_freshness_seconds` is an
  enum: 900, 1800, 3600, 21600, 43200, 86400, 604800 — there is no sub-15-minute value.)
- TTL is at the floor _because the data must be fresh_ (e.g. real-time dashboard) → cache won't
  help, skip to step 2.

The shape of the variables matters here: if every call passes different `user_id` or `date_from`
values, the cache has many distinct keys and a higher TTL helps less. If almost every call uses
the same handful of parameter combinations, the cache helps a lot.

### Step 2 — Should it be materialised?

Materialisation pre-computes the query into a saved view that's refreshed on a schedule. Reads
become near-instant — at the cost of staleness equal to the refresh interval, plus storage and
compute for the materialisation itself.

Call `endpoints-materialization-preview`. The response tells you:

- **Eligible + clean transform** → strong candidate. Recommend enabling, especially for
  endpoints with predictable filter shapes (variables, breakdowns).
- **Not eligible**, with a rejection reason → cannot materialise. The reason often hints at the
  next step (see step 3 — rewrite).
- **Eligible but the transform is gnarly** (lots of range pairs, complex aggregation
  re-derivation) → materialisation will work but may not save much. Worth flagging before
  flipping the switch.

When materialisation is enabled, callers **must pass all materialised variables** — calls without
them are rejected (security: prevents returning unfiltered data). Pair the recommendation with
a note about which variables become required.

### Step 3 — Does the query need rewriting?

If the endpoint isn't eligible for materialisation, the rejection reason from
`endpoints-materialization-preview` is usually the lead:

- **Cohort breakdown / compare mode rejection** → regular property breakdowns materialise fine;
  only cohort breakdowns and compare mode are blocked. Swap a cohort breakdown for a property
  breakdown, or drop compare mode (expose the comparison window as a variable instead).
- **JOINs combined with variables** → a top-level `JOIN` plus a variable filter is rejected for
  materialisation, because applying the variable changes the joined row cardinality and silently
  produces wrong results (e.g. `LEFT JOIN` non-matches lose the variable column). Restructure so the
  variable filters a single table — push the filter into a subquery/CTE that's then joined, rather
  than filtering across the join. This is the most common "looks fine but won't materialise" trap.
- **"Missing variables" / unbounded scan** → the query reads too much data without a filter.
  Encourage adding a required time-window variable (e.g. `date_from`, `lookback_days`).
- **HogQL with `*` / non-deterministic functions** → narrow the columns selected, replace
  `now()` / `today()` with a variable when possible.

Check `endpoint-versions` to see whether the query was recently changed. Often the regression
came from a specific commit and reverting that version is faster than rewriting.

### Step 4 — Is the slow version even the one being called?

Only the latest version runs by default; older versions run only when a caller pins `?version=N`.
So the version to tune is almost always the current one — unless a pinned older version is the
culprit. Call `endpoint-versions` and read each version's `last_executed_at` to see which versions
have been hit recently; a materialised version with a null or long-stale `last_executed_at` is a
candidate to unmaterialise or delete rather than tune (confirm first — that signal only counts
API-key runs and can be sparse).

For endpoint-level call frequency and per-call cost, query `query_log` with `execute-sql` — it
carries `query_duration_ms`, `read_rows`, and `read_bytes`, handy for confirming how heavy the
endpoint's calls actually are:

```sql
SELECT count() AS calls, max(query_start_time) AS last_called, avg(query_duration_ms) AS avg_ms
FROM query_log
WHERE name = '<endpoint_name>' AND endpoint LIKE '%/endpoints/%' AND is_personal_api_key_request
```

## Workflow

1. Identify the endpoint by name. If the user gave a URL, parse the name from
   `/api/projects/{team_id}/endpoints/{name}/run`.
2. `endpoint-get` to fetch full config. Note: `data_freshness_seconds`, `is_materialized`,
   current version, query kind.
3. `endpoint-materialization-status` to see materialisation health (failed? eligible?).
4. `endpoint-versions` to see the query history and which version is current (the one callers
   hit unless they pin `?version=N`).
5. If the user gave specific symptoms ("times out", "memory limit", "very slow"), walk the
   decision tree above. Otherwise, present the four checkpoints and ask which matches.
6. End with a concrete recommendation — bump TTL, materialise, rewrite, or rollback — and
   confirm before applying it.

## Example interaction

```text
User: "monthly_active_users is timing out for some callers"

Agent steps:
- endpoint-get monthly_active_users → HogQL endpoint, data_freshness_seconds=900,
  is_materialized=false, current version v4
- endpoint-materialization-status monthly_active_users → not materialised; eligible: true
- endpoint-versions monthly_active_users
  → v4 is current; v1–v3 are prior query revisions (callers hit v4 unless pinned)
- endpoints-materialization-preview → eligible, clean transform with one range pair

- "Three things stand out:
   1. Cache TTL is 900 seconds (the 15-min floor), but the data is
      aggregating a month — that aggressive a refresh probably isn't
      necessary. Bumping to 1 hour (3600s) would dramatically reduce
      ClickHouse load.
   2. It's eligible for materialisation with a clean transform. If
      callers can tolerate 5-15 minute staleness, materialisation
      would make reads near-instant.
   3. v4 is the current version, so callers hit it by default — the
      tuning target is clear.

   Quickest win: bump TTL to 3600s. Bigger win: materialise.

   Which trade-off matches your needs? If you need real-time freshness,
   neither helps and we'd need to rewrite the query — likely narrowing
   the aggregation window."
```

## Important notes

- **Cache is almost always the first fix.** It's free, instantly reversible, and doesn't change
  data semantics. Resist jumping to materialisation if a higher TTL would do.
- **Materialisation has hidden costs.** Storage of the materialised view, refresh compute, and
  the requirement that callers pass all variables.
- **Don't rewrite the query without the user.** A query change creates a new version and may
  break callers!!! Surface the suggested change, get sign-off, then apply.
- **Three usage signals.** `endpoint-get`'s `last_executed_at` is endpoint-level recency;
  `endpoint-versions` gives each version's own `last_executed_at`; `query_log` (via `execute-sql`)
  gives endpoint-level call frequency and per-call cost. All count only personal-API-key calls, and
  per-version recency can be sparse — confirm with the user before calling a version dead.
- **The "right" fix depends on the SLA, not the query.** Always ask the user about acceptable
  staleness before recommending materialisation. A 15-minute-stale materialised view is wrong
  for a real-time dashboard, regardless of how cheap it'd be.
- **Tell PostHog what's missing.** If the diagnosis runs into a product limitation (an eligibility
  rule, the TTL enum, required variables), nudge the team via `agent-feedback`.
