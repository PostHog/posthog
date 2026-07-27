---
name: creating-an-endpoint
description: >
  Create a PostHog endpoint with the right shape on the first try — covers query kind choice, name
  conventions, what to expose as variables (HogQL code_name vs insight breakdown),
  data_freshness_seconds, and whether to materialise on day one. Use when the user says "create an endpoint", "expose this
  query as an API", "turn this insight into an endpoint", or asks for help structuring a new
  endpoint. Steers away from common mistakes: materialising a query with cohort breakdowns or
  compare mode, inline-only variables on a materialised endpoint, unbounded date ranges, ambiguous
  names.
---

# Creating an endpoint

This skill walks through creating a new endpoint with the right configuration. Endpoints expose
saved HogQL or insight queries as callable HTTP routes — the configuration choices made at
creation time determine cost, latency, and how callers integrate.

The materialisation deep-dive lives at `references/materializing.md`. Pull it in when the
materialisation decision is non-obvious.

## When to use this skill

- "Create an endpoint for [query]"
- "Expose this insight as an API"
- "Help me turn this HogQL into a callable endpoint"
- A new caller (mobile app, customer-facing dashboard, downstream pipeline) needs PostHog data
  and the user is choosing how to deliver it

## Decisions to make in order

### 1. Should this even be an endpoint?

Endpoints are right when:

- An **external system** (someone else's code) needs to call PostHog for data
- The query is **stable** — not exploratory analysis
- The shape is **reusable** — same query with different parameters

Endpoints are wrong when:

- An internal PostHog dashboard or insight needs the data — use the insight directly; an endpoint
  only adds an external API surface you don't need internally
- One-off, exploratory analysis — use the `execute-sql` tool (or the SQL editor) directly

Heavy aggregation is **not** a reason to avoid an endpoint. Endpoints are themselves saved
queries, and a heavy, frequently-called aggregation is often the _best_ case for an endpoint with
materialisation turned on.

If the user is unsure, ask what's calling the endpoint and what shape they expect.

### 2. Pick a name

Names are URL-safe (letters, numbers, hyphens, underscores), start with a letter, max 128 chars,
must be unique within the project. Lean toward:

- **Descriptive over generic** — `weekly_active_users_by_org` over `metrics`
- **Snake_case** — matches how the name appears in code paths and URLs
- **No version in the name** — versions are managed by the endpoint itself
- **No "endpoint" in the name** — redundant

The name appears in the URL: `/api/projects/{team_id}/endpoints/{name}/run`. It's not
trivially renameable later (callers depend on the path) — get it right at creation.

### 3. Pick the query kind

Two options exist:

- **HogQL** (`HogQLQuery`) — raw SQL written by the user. Variables defined via `{variables.x}`
  syntax, matched on `code_name`. Recommended for new endpoints when the caller cares about
  the exact column shape of the response.
- **Insight** — wraps an existing insight definition. Best supported for `TrendsQuery`,
  `LifecycleQuery`, and `RetentionQuery`: these can be materialised, and the breakdown can act as
  a variable (Trends and Retention only; Lifecycle has no breakdown). Other insight kinds such as
  `FunnelsQuery` can run inline but **cannot be materialised and don't expose breakdown
  variables** — rewrite those as HogQL if you need either.

HogQL is the more flexible choice. Pick insight only when the user is genuinely re-publishing an
existing insight (see "Creating from an existing insight" below) rather than building a new query.

### 4. Decide which inputs become variables

Anything that should change per-caller goes in variables; the rest is hard-coded in the query.

**For HogQL endpoints**, variables are declared in the query payload with `code_name`, `type`,
and `default`. Each execution call passes `{ "variables": { "<code_name>": value } }`.

Common patterns:

- Time windows: `date_from`, `date_to`, or a single `lookback_days` integer
- Identity filters: `user_id`, `account_id`, `team_id`
- Pagination control beyond `limit` / `offset` (these are first-class on the run endpoint already)

**For insight endpoints**, the breakdown property acts as the variable (Trends and Retention
only — Lifecycle has no breakdown). Pass the breakdown property name as the key. `date_from` /
`date_to` are accepted as variables **only on non-materialised** insight endpoints — a materialised
endpoint bakes its date range into the view, so callers can't shift the window.

Avoid:

- **Variables that change the shape of the result** — keep the columns stable. If callers need
  fundamentally different result shapes, ship separate endpoints.
- **Variables that bypass safety** — don't expose a `where_clause` variable that lets callers
  inject arbitrary SQL.

### Creating from an existing insight

There's no server-side "make an endpoint from insight N" operation. To do it: read the insight's
query (via the insight tools), pass that query to `endpoint-create`, and set `derived_from_insight`
to the insight's short id so the origin is recorded. The endpoint then owns its own **copy** of
the query — later edits to the insight don't propagate. Starting from scratch instead? Build the
query first with the insight / `sql-variables` tools, then create the endpoint from it.

### 5. Set `data_freshness_seconds`

This one field does **two** jobs, so set it deliberately:

1. **Cache TTL** — results are served from cache until they're this many seconds old.
2. **Materialisation refresh frequency** — on a materialised endpoint, this is also how often the
   warehouse recomputes the materialised view.

So a lower value means fresher data _and_ more frequent recompute/refresh cost; a higher value is
cheaper on both counts but staler.

The value must be one of a fixed set: `900` (15 min), `1800` (30 min), `3600` (1 h), `21600`
(6 h), `43200` (12 h), `86400` (24 h, default), `604800` (7 d). There is no sub-15-minute
option — `900` is the floor.

| `data_freshness_seconds` | When to pick it                                                      |
| ------------------------ | -------------------------------------------------------------------- |
| 900–1800                 | Freshest available — dashboards where staleness is visible           |
| 3600–43200               | Most cases — fresh enough for product usage, cheap to recompute      |
| 86400–604800             | Reports, weekly/daily metrics, anything aggregated over long periods |

Bias toward higher values unless the user explicitly needs fresher data. On a materialised
endpoint, remember this also sets the refresh cadence.

### 6. Decide on day-one materialisation

See `references/materializing.md` for the full decision tree. Short version:

- **Recommend materialisation** when the endpoint will be called frequently, latency matters,
  and the user can tolerate staleness equal to the refresh interval (typically 5-15 minutes for
  scheduled materialisation, or hourly).
- **Skip materialisation** for low-traffic endpoints, exploratory new endpoints (you don't
  know yet if it'll get called), and queries where freshness is critical.

If unsure, create unmaterialised and add `is_materialized: true` later once usage stabilises.
That avoids paying for materialisation on a query nobody ends up calling.

## Workflow

1. Confirm the use case (step 1 above). If it's not actually a fit for an endpoint, recommend
   the alternative.
2. Agree a name with the user.
3. Walk through the query — confirm it's HogQL or insight, and that the columns/shape make sense.
4. Identify what should be a variable. Show the user the variable declaration syntax.
5. Pick `data_freshness_seconds` based on the user's freshness requirement (ask if not clear) —
   remembering it also sets the materialisation refresh cadence.
6. Make the materialisation call. If on the fence, ship without and revisit later.
7. Call `endpoint-create` with the agreed config.
8. Confirm by calling `endpoint-run` with a sample payload to verify the response shape.
9. Hand off to `consuming-endpoints-from-client-code` if the user is about to wire it up.

## Example interaction

```text
User: "I want to expose our monthly active users count as an API
       for our analytics partner"

Agent:
- "Quick check: is the partner going to call this on demand, or
   should we be pushing data to them? Endpoints are pull-only."
- User: "On demand"
- "Got it. A few choices:
   - Name: how about monthly_active_users? Lowercase, descriptive,
     no version baggage.
   - The query — is it HogQL or are you exposing an existing insight?
     HogQL gives you exact column control; insight reuses what you've
     already built.
   - What should the partner be able to filter by? Org, time window,
     both?
   - How fresh? If MAU drifts within a day is fine, we can cache
     results for 1-24 hours and serve almost everything from cache.
   - Materialisation: if the partner is going to hit this many times
     per day, materialising it would make responses near-instant.
     The trade-off is ~10-15 minute staleness.

   What's your starting point on these?"

[user picks: HogQL, lookback_days + org_id variables, 3600s TTL,
 not materialised yet]

- endpoint-create monthly_active_users {query, variables, ...}
- endpoint-run with sample payload {org_id: "test", lookback_days: 30}
- "Created and tested. Want help wiring up the client code?
   That's consuming-endpoints-from-client-code."
```

## Important notes

- **The name lives in the URL.** Changing it later requires migrating callers. Pick well.
- **HogQL endpoints are more flexible than insight endpoints.** Default to HogQL unless the
  user has a specific reason to wrap an existing insight.
- **Variables with no default fail at call time.** Always set defaults during creation so the
  endpoint is testable from the playground without specifying every variable.
- **Materialised endpoints require all variables to be passed.** Calls without them are
  rejected — this is intentional (security: prevents returning unfiltered data). Pair the
  materialisation recommendation with a note to the user about which variables become required.
  (Optional/partial variables on materialised endpoints are a known limitation the PostHog team
  plans to lift — if it's blocking the user, nudge them via the `agent-feedback` tool.)
- **Don't enable materialisation on a query that isn't eligible.** Use
  `endpoints-materialization-preview` first to confirm eligibility and see the rejection reason
  if any.
- **Endpoints are not stable forever.** When the user changes the query, a new version is created
  automatically (the old version stays accessible via `?version=N`). `data_freshness_seconds` and
  materialisation are per-version. Adjust as the endpoint evolves.
- **Recommend callers pin to a version.** Tell the user to call with `?version=N` rather than
  relying on "latest" — that way a future query edit (which cuts a new version) can't silently
  change their results. They bump the pinned version deliberately once they've validated the new
  one.
- **Share friction via `agent-feedback`.** If a limitation gets in the way (eligibility rules,
  required variables, the TTL enum), send the PostHog team a note — it's how the product and these
  tools improve.
