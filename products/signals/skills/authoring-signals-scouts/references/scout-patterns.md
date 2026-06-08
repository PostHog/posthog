# Scout patterns (a cookbook)

A catalog of the **reference architectures** scouts fall into. Most new scouts are a
variation on one of these — pick the closest shape as your starting point, copy the named
canonical scout it maps to, and swap in your surface's discriminator and queries. The
[`scout-anatomy.md`](scout-anatomy.md) body structure is the same for all of them; what
changes between patterns is **what the scout watches**, **how it reads that data**, and
**what its signal-vs-noise discriminator is**.

This is a living reference — add a pattern when a genuinely new shape proves itself, rather
than letting every scout reinvent one.

## What a scout can watch

The single most useful thing to internalize: **a scout is not limited to PostHog
analytics events.** It can watch anything the project can see, and the emit / dedupe /
memory contract is identical regardless of where the data comes from.

| Source                       | How the scout reads it                                                                                                                                                  |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Collected events**         | `read-data-schema` to confirm the event + properties, then `query-*` tools or `execute-sql`. The common case.                                                           |
| **The data warehouse**       | `read-data-warehouse-schema` to confirm columns, then `execute-sql`. **Any source PostHog ingests becomes a queryable table** — see the warehouse-backed pattern below. |
| **PostHog product entities** | dedicated list/get tools (insights, dashboards, surveys, error issues, experiments, flags) plus `execute-sql` over `system.*`.                                          |
| **External systems**         | from inside the sandbox, when it runs with a TRUSTED network — a CLI tool, a public git repo, an HTTP API. See the external-tool pattern.                               |

The warehouse row is the big unlock: once a Slack channel, a Stripe account, a CRM, a
billing system, a support inbox, a social-listening feed, or an app database (via CDC) is
synced into the warehouse, a scout queries it with `execute-sql` exactly like it queries
events — and the watched surface need not be PostHog analytics at all.

## The patterns

| Pattern                       | Watch this when…                                                                           | Canonical example                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| **Anomaly watcher**           | a product surface has a metric with a baseline that can move (bursts, drops, regressions). | `signals-scout-error-tracking`, `-logs`, `-revenue-analytics`, `-csp-violations` |
| **Watchlist explore/exploit** | the surface is too big to cover in one run; you must curate what's worth re-checking.      | `signals-scout-anomaly-detection`                                                |
| **Cross-product correlation** | the question spans products — a cause in one surface, an effect in another.                | `signals-scout-general`                                                          |
| **Recommendation / gap**      | nothing is broken, but the team is missing coverage or following an anti-pattern.          | `signals-scout-observability-gaps`                                               |
| **Warehouse-backed source**   | the signal lives in a non-PostHog source synced into the warehouse.                        | a Slack-channel-sync scout (below)                                               |
| **Custom / single-event**     | one bespoke event carries the whole signal.                                                | an MCP-feedback scout (below)                                                    |
| **Open-text theme**           | the data is free text and the value is in recurring themes, not individual rows.           | `signals-scout-surveys` (open-text); brand/feedback scouts                       |
| **External-tool / code**      | the judgement comes from running a tool or reading code, not from analytics.               | a static-analysis CLI scout (below)                                              |

### Anomaly watcher

The default specialist shape, and the one most surfaces fit.

- **Watched data:** one product surface's metric over time (error counts, log volume, MRR,
  CSP violations, response rates).
- **Discriminator:** deviation of the latest complete bucket from a **seasonality-matched
  baseline** — and a cheap profile-shape read to triage first (e.g. error tracking's
  `count` vs `distinct_users` ratio separates broad-reach bursts from single-user loops).
  Name the discriminator at the top; it's the whole game.
- **Dedupe + memory:** `dedupe:<domain>:<entity>` gates re-emits per entity;
  `pattern:<domain>:baseline` records what normal looks like so the next run doesn't
  re-derive it.
- **Gotcha:** score the **latest complete** bucket, not the in-progress one — a partial
  current hour/day always looks like a drop.
- Copy the closest specialist verbatim and replace the surface + discriminator. Read
  `products/signals/skills/signals-scout-error-tracking/SKILL.md` for the cleanest worked
  example (its `count`-vs-`distinct_users` table is the canonical discriminator).

### Watchlist explore/exploit

For a surface with more to watch than one run can cover (a busy project's dashboards and
insights). The scout can't re-check everything every run, so it **curates**.

- **Watched data:** a durable, scratchpad-held watchlist of high-value entities discovered
  over time (by view count, dashboard membership, traffic).
- **Discriminator:** robust (MAD) deviation from each watched item's own baseline.
- **The balance:** each run splits effort between **exploit** (re-check watchlist items
  that are due) and **explore** (discover new high-value items to add). Neither alone is
  enough — exploit-only goes stale, explore-only never follows up.
- **Dedupe + memory:** the watchlist itself is the memory — `watchlist:<domain>:<id>`
  entries with last-checked timestamps and per-item baselines. This is the one specialist
  that bundles its own references; read
  `products/signals/skills/signals-scout-anomaly-detection/` for the full treatment.

### Cross-product correlation

The generalist's job. Not a deep dive into one surface — that's what specialists are for —
but the **seams between** surfaces.

- **Watched data:** signals from multiple products at once, looking for causal chains: a
  deploy → an error burst → a conversion dip → a revenue drop.
- **Discriminator:** temporal coincidence + a plausible causal story across ≥2 surfaces.
- **Technique:** rotate the investigative lens across runs to avoid lens-lock (a generalist
  that always looks at errors becomes a worse error-tracking specialist). Start from
  `signals-scout-general`.

### Recommendation / gap

The odd one out: nothing is wrong, but something is **missing or sub-optimal**. Emits P3
recommendations rather than P0–P2 anomalies.

- **Watched data:** the delta between what exists and what good practice would have — events
  with no insight coverage, critical events with no alert, a sequential funnel nobody built,
  insights pointing at events that stopped firing.
- **Discriminator:** a high-value entity that lacks the coverage/configuration it should
  have.
- **Calibration:** default `severity` P3; weight by how much the gap matters, not by
  urgency. Don't flood the inbox — a recommendation the team won't act on is noise.
- See `products/signals/skills/signals-scout-observability-gaps/SKILL.md`.

### Warehouse-backed source scout

**The pattern that lets a scout watch anything PostHog can ingest.** A non-PostHog source
(a Slack channel, a billing system, a CRM, a support tool, a social-listening feed) is
synced into the data warehouse on a schedule; the scout reads the resulting table with
`execute-sql` and turns it into signals. The watched surface is not analytics data at all —
it's whatever that upstream system produces.

- **Watched data:** one (or a few) warehouse tables. Always confirm columns with
  `read-data-warehouse-schema` first — column names are source-defined and often opaque.
- **Discriminator:** read off whatever the source already gives you cheaply. If the upstream
  pre-classifies rows (a sentiment field, a category, a status), anchor on that — it's a
  free discriminator. Otherwise derive one (recency × a keyword/shape match × recurrence).
- **Dedupe + memory:** dedupe on a **stable source id** carried in the row (a post id, a
  ticket id, an external primary key) — `dedupe:<domain>:<source_id>`. Don't dedupe on the
  warehouse row id; syncs re-materialize rows.
- **Gotchas — these bite every warehouse scout:**
  - **Watermark/cursor.** Synced tables are append-only and grow; consecutive syncs often
    overlap, so the same logical record recurs across rows and across runs. Track how far
    you've processed in a scratchpad cursor (`pattern:<domain>:cursor` = "processed through
    {timestamp}") and only look past it each run. The cheap close-out is "has the max
    timestamp advanced past my cursor?"
  - **Timestamp parsing.** Warehouse timestamps are often strings — parse explicitly
    (`parseDateTimeBestEffort(...)`), and confirm which parse functions the table supports
    rather than assuming.
  - **The table may not be in the project profile.** It's a warehouse table, not an event,
    so `project-profile-get` won't list it. Rely on SQL; handle the "table missing entirely"
    case with a `not-in-use:<domain>:team{team_id}` close-out.
  - **Evidence `source_product`:** use `data_warehouse`, and cite the source id as
    `entity_id` so a human can pivot to the original record.
- **Worked example shape** — a scout over a Slack channel that's synced to the warehouse:
  the upstream tool posts pre-classified items into the channel, the channel syncs to a
  warehouse table every few hours, and the scout (running hourly) sweeps new rows past its
  cursor, anchors on the pre-classified discriminator, dedupes by the source post id, and
  emits the few that clear the bar. Everything else — the anatomy, the emit contract, the
  four-states classifier — is identical to an events-based scout.

### Custom / single-event scout

When one bespoke event captured into PostHog carries the whole signal (a product's own
telemetry, a feedback event, a domain-specific action).

- **Watched data:** one event, confirmed via `read-data-schema` (the event **and** the
  properties you'll filter on — both are team-specific and may be absent).
- **Discriminator:** a discriminating property on the event. Pick the one property that
  separates actionable from noise (a sentiment, a category, a `task_completed=false` flag)
  and anchor on it.
- **Corroboration:** strengthen a qualitative finding by quantifying blast radius against a
  **second** event — e.g. cross-check a complaint about a tool against that tool's error
  rate over the same window. "Failed on N of M calls" raises confidence far above the raw
  complaint.
- **Dedupe + memory:** `dedupe:<domain>:<entity>` per recurring issue;
  `pattern:<domain>:baseline` for the normal submission rate/mix.

### Open-text theme scout

A cross-cutting variation, not a standalone surface: when the watched data is **free text**
(survey open-text responses, feedback submissions, social posts, support messages), the
value is in **recurring themes**, not individual rows.

- **The core rule:** aggregate. Emit **one themed finding** backed by several items, not one
  finding per item. A stream of one-off complaints erodes the inbox's trust; a single
  "these 6 submissions all describe X" is actionable.
- **Discriminator:** the same root issue appearing across ≥2 items (same category, same
  complaint shape, same requested feature) — or a single, unusually sharp, concrete item
  that's worth surfacing at n=1.
- **Dedupe + memory:** `dedupe:<domain>:<theme-slug>` / `addressed:<domain>:<theme-slug>`
  gate the **theme**, not the individual rows. Quote 1–3 representative items verbatim in
  evidence; cite item ids inline.
- **Gotcha — PII.** Free-text sources often contain personal data (emails, phone numbers,
  names). Summarize the issue and link the source; never copy raw personal contact details
  into a finding.
- This layers onto the warehouse-backed or custom-event patterns — `signals-scout-surveys`
  does it over survey open-text; the same shape applies to any text stream.

### External-tool / code-review scout

When the judgement comes from **running a tool or reading code**, not from analytics. The
scout reaches out from the sandbox to a public git repo, assesses recently-changed files,
and turns the result into P3 recommendations. There are two judge modes:

- **Tool-as-judge** — run a deterministic static-analysis CLI and surface what it finds; the
  tool is the source of truth, the scout just runs it correctly and triages. Confidence is
  high because the tool is deterministic.
- **Rules-as-judge** — fetch a published ruleset/checklist and have the agent read the code
  and apply the rules with its own judgment. More flexible, lower intrinsic confidence —
  only emit statically-verifiable violations.

Both share the same skeleton:

- **Watched data:** files changed in a recent window (e.g. the last 7 days) in a code repo,
  and the tool/ruleset output over them.
- **Discriminator:** a high-impact finding **attributed to recent changes** — a violation in
  a file that changed this week. Noise is the pre-existing backlog, low-severity style nits,
  and anything a sibling scout already emitted for the same file.
- **Calibration:** P3 recommendations; `weight` ~0.4–0.6. **One finding per file** (bundle
  that file's issues), **cap the emits per run** (worst offenders first), and cross-check
  sibling scouts' runs so two code scouts don't double-report the same file.
- **Dedupe + memory:** `dedupe:<domain>:<repo>:<path>` (+ a `...:<rule-id>` qualifier);
  `addressed:<domain>:<repo>:<path>` gates re-emits; `pattern:<domain>:<repo>` records the
  repo's stack so the next run doesn't re-derive it.
- **Requirements & gotchas — specific to reaching outside the sandbox:**
  - Needs a **TRUSTED network** sandbox and the runtime (e.g. `node`/`npx`, `git`, `curl`).
    Declare this in the scout's `compatibility` so the harness provisions it.
  - **Prefer `git` over authenticated APIs.** Scouts run without third-party credentials.
    Clone cheaply (`git clone --filter=blob:none`) or reuse an on-disk checkout, and derive
    the changed-file set from `git log --since=… --name-only` — zero API calls. If you must
    hit an unauthenticated API, it's rate-limited (~60 req/hr); cap calls per run.
  - **Cap the work and never silently truncate.** Bound the number of files assessed and the
    emits per run; if you drop files for budget, say how many in the close-out.
  - **Calibrate the tool/ruleset to the target's reality.** A ruleset written for one stack
    (e.g. a server framework) mostly doesn't apply to a different one (e.g. a client-only
    SPA) — scope the rules per repo before applying them, or the findings are noise.
  - **Attribute to the diff.** Use the tool's diff/PR mode if it has one; otherwise filter
    its full output down to the recently-changed file set. Don't re-emit standing debt.
  - **Be honest when the tool can't run.** If the CLI can't execute in the sandbox (registry
    unreachable, needs a heavy install you shouldn't attempt), record a memory entry with the
    exact error and close out — never pretend it ran clean.
  - Skip generated/test files; evidence `source_product` is the tool name (or `github`).

## Cross-cutting techniques

These compose into any pattern above:

- **Fast sweep + gated deep pass.** One scout can do two amounts of work: a cheap
  **never-miss sweep** every run (the urgent case — a live problem, an agent-blocking
  failure) plus a heavier **deep pass** gated to a longer cadence (themes, slow-moving
  analysis) via a scratchpad gate (`pattern:<domain>:last-deep-pass` = "deep pass last run
  {timestamp}; skip if <12h"). This gives urgent findings low latency while keeping
  soft-signal emits to a trickle. Useful whenever a surface has both "page someone now" and
  "worth knowing eventually" signals.
- **Watermark/cursor** (detailed under the warehouse pattern) — for any append-only,
  overlapping, or unbounded source, track processed-through in scratchpad so each run is
  incremental and dedupe survives across runs.
- **Blast-radius corroboration** — turn a qualitative signal into a quantified one by
  cross-checking a second source over the same window. Raises confidence and weight, and
  gives the human a number to act on.

## Picking and combining

Start from the table at the top: find the row that matches **where your signal lives** and
**what shape it takes**, copy that canonical scout, and swap in your discriminator. Real
scouts routinely combine patterns — a warehouse-backed scout that does open-text theme
aggregation on a fast-sweep/deep-pass cadence is three of these at once, and that's normal.
The patterns are starting shapes, not boxes.
