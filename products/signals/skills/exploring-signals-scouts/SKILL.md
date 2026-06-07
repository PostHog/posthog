---
name: exploring-signals-scouts
description: >
  How to explore and make sense of PostHog Signals scouts — the scheduled agents that scan a
  project and emit findings into the Signals inbox. Use when a user wants to understand what
  scouts they have, how each one is behaving, and whether the fleet is actually working. Covers
  surveying the fleet and its schedules, reading recent scout runs and drilling into a single
  run's reasoning, inspecting the durable scratchpad memory the fleet has built up, tracing a
  run to the findings it emitted, and assessing a scout's health and performance over time
  (cadence, success rate, emit rate, signal-to-noise). Read-only and exploratory — to write or
  tune a scout, use `authoring-signals-scouts` instead. Trigger on "what are my scouts doing",
  "how is my <x> scout performing", "show me recent scout runs", "why did this scout find/emit
  nothing", "what has the fleet learned", "explore scout run <id>", "is my scout working".
metadata:
  owner_team: signals
---

# Exploring Signals scouts

A **scout** is a scheduled agent that wakes on its own interval, looks at one PostHog project,
decides what's genuinely worth surfacing, and either emits it as a **finding** into the Signals
inbox or closes out empty (a real, valid outcome). PostHog ships a fleet of canonical scouts — a
cross-product generalist (`signals-scout-general`) plus per-surface specialists
(`-error-tracking`, `-llm-analytics`, `-logs`, `-revenue-analytics`, `-surveys`,
`-csp-violations`, `-observability-gaps`). A project may also have **custom scouts** beyond the
canonical fleet — any `signals-scout-*` skill a team authored (e.g. `-brand-mentions`,
`-mcp-feedback`) shows up here too, so don't assume the roster is only the canonical set.

This skill helps you **understand and explore what a project's scouts are doing and how they're
performing** — entirely through read-only MCP tools. It is the observability counterpart to
[`authoring-signals-scouts`](../authoring-signals-scouts/SKILL.md) (which teaches writing and
tuning) and to [`inbox-exploration`](../inbox-exploration/SKILL.md) (which covers the inbox
reports scouts feed into).

There are four things you can observe about the fleet, each with its own tool:

| What you want to know                        | Tool                                    | What it tells you                                             |
| -------------------------------------------- | --------------------------------------- | ------------------------------------------------------------- |
| Which scouts run, how often, in what posture | `signals-scout-config-list`             | One row per scout: schedule, `enabled`, `emit`, `last_run_at` |
| What the scouts actually did, run by run     | `signals-scout-runs-list` / `-retrieve` | Per-run status, timing, end-of-run summary, deep-link         |
| What the fleet has learned across runs       | `signals-scout-scratchpad-search`       | Durable per-team memory (baselines, noise, allowlists)        |
| What the scouts surfaced to the user         | `inbox-reports-list`                    | Findings that cleared the bar and became inbox reports        |

The orienting fifth is `signals-scout-project-profile-get` — the deterministic snapshot of "what's
true about this project" that every scout cold-starts from. When a scout found nothing, this is
usually why.

## Start here: is the fleet even set up?

Don't assume the project has scouts. The fleet only runs on teams enrolled via the `signals-scout`
feature flag, and a project may have no configs, all-disabled scouts, or scouts stuck in dry-run.
Run this first whenever a user asks about their scouts for the first time in a session.

```json
signals-scout-config-list
```

Read the result against three cases:

The config list is unpaginated — it comes back as `{ results: [...] }` (a bare array), with no
`count` field. Read the result against three cases:

- **Empty (`results: []`)** — no scouts are registered. The project isn't enrolled in the scout
  fleet (or hasn't ticked yet). Say so plainly; don't go fishing for runs. Point the user at the
  Signals scout settings / PostHog Code onboarding rather than inventing activity.
- **Configs exist but all `enabled: false`** — the fleet is registered but paused. Nothing is
  running. Tell the user which scouts exist and that they're all off.
- **At least one `enabled: true`** — the fleet is registered and that scout is allowed to run. For
  each enabled scout note its `run_interval_minutes` (cadence), `emit` (false = **dry-run**, runs
  but writes nothing to the inbox), and `last_run_at` (when it last fired — `null` means it has
  never run). One caveat before reporting "it's live": runs are gated by the `signals-scout` feature
  flag, not by `enabled`. A project that was enrolled and later drained from the flag keeps its
  `enabled: true` rows, but the coordinator no longer plans runs for it — so a stale or `null`
  `last_run_at` on an enabled scout usually means the project is no longer enrolled, not that the
  scout is idle. When `last_run_at` is recent, the scout is genuinely running; proceed to the user's
  actual question.

A scout that is `enabled: true` but `emit: false` is the most common source of "my scout isn't
doing anything" confusion: it _is_ running and reasoning every tick, it just isn't allowed to post
findings yet. Always surface the `emit` posture when reporting on a scout.

See [`references/scout-data-model.md`](references/scout-data-model.md) for every field on a config,
run, and scratchpad entry, the run status values, and how the pieces link together.

## Workflow: survey the fleet

"What scouts do I have / what are they doing?" — lead with `config-list`, then enrich with the
most recent run per scout so the user sees liveness, not just configuration.

1. `signals-scout-config-list` — the roster.
2. For each enabled scout, `signals-scout-runs-list` and pick the newest run with a matching
   `skill_name` (runs come back newest-first across the whole fleet, so a single call usually
   covers everyone). Report `status` and how long ago it ran.

Present it as a table the user can scan — scout, cadence, posture, last run, last outcome — and
call out anything anomalous (never run, last run errored, stuck in dry-run for a long time).

## Workflow: understand one scout end to end

"How does my error-tracking scout work / how is it doing?"

1. **Read its config** — find the row in `config-list` for `signals-scout-error-tracking`:
   schedule, posture, last run.
2. **Read its body** — `posthog:llma-skill-get {"skill_name": "signals-scout-error-tracking"}`
   returns the team's actual instruction set (which may be a canonical default or a diverged,
   hand-edited row). This is what the agent is told to do every run — its signal-vs-noise
   discriminator, explore patterns, and disqualifiers. To understand _why_ a scout behaves the
   way it does, read its body.
3. **Read its recent runs** — `runs-list` with `text` set to the skill's domain, or just scan the
   newest runs and filter to its `skill_name`. The end-of-run `summary` on each run is the scout's
   own account of what it looked at and decided.
4. **Read what it remembered** — `scratchpad-search` (see below). The memory entries a scout wrote
   reveal the baselines and noise it has internalized about this project.

## Workflow: read recent runs

`signals-scout-runs-list` returns the most recent runs across the whole fleet, newest first
(capped at 100). Use it to answer "what happened lately?"

- **Scope to a window** with `date_from` / `date_to` (ISO-8601; inclusive lower, exclusive upper
  on `created_at`). Walk backwards by passing an earlier `date_to`.
- **Search summaries** with `text` — a case-insensitive substring match on each run's end-of-run
  `summary`. This is how the headless scout dedupes, and it's how you find "did any run already
  look at the checkout error spike?"

Each summary row carries `run_id`, `skill_name`, `skill_version`, `status`, `started_at`,
`completed_at`, `task_url` (a deep-link into the Tasks UI for the full transcript), and the
`summary` prose. Lead with the `summary` when narrating to the user — it's the scout's own
plain-language close-out — and always offer the `task_url` for the full reasoning.

## Workflow: drill into a single run

When the user wants the full story of one run (or pastes a run id / Tasks URL):

```json
signals-scout-runs-retrieve
{ "id": "<uuid>" }
```

Note the field name flip: `runs-list` returns each run's id as `run_id`, but `runs-retrieve`
takes it as `id`. Pass the `run_id` value through as `id`.

Returns the full run: `status`, `started_at` / `completed_at` (compute duration from these),
`skill_name` / `skill_version` (what ran, at what body version), the end-of-run `summary`, and
`task_url`. The transcript — the actual tool calls and reasoning — lives in the Tasks UI behind
`task_url`, not in this payload; hand the user that link when they want to see every step. A
**failed** run returns an empty `summary` and **no error field** — the payload looks the same as
the list row, so to learn _why_ it failed you must open `task_url`.

**Telling whether a run emitted is not as direct as you'd hope.** The run row carries no emit
flag and no finding count — the only readily-available signal is the prose `summary`, which says
"EMITTED nothing" on a quiet run and names what it emitted otherwise. Read it carefully: a phrase
like "already emitted P1 … did not re-emit" describes a _prior_ run and means this run emitted
nothing, so substring-matching the summary for "emitted" is unreliable. Findings do carry a
deterministic `source_id = run:<run_id>:finding:<finding_id>`, but it's stored in the signal's
`metadata.extra` (not a top-level field) and grouping merges scout findings into the same
clusters as other sources, so the `source_product: "signals_scout"` inbox filter does **not**
reliably surface them. See [`references/scout-data-model.md`](references/scout-data-model.md) for
the run-to-finding link and its limits.

A run with `status` complete and an empty-handed summary ("surface at baseline, nothing to
emit") is a **healthy** outcome, not a failure — most runs should close out empty. Treat a stream
of empty close-outs as the fleet doing its job, not as the fleet being broken.

## Workflow: inspect what the fleet has learned

The **scratchpad** is the fleet's durable, per-team memory — prose entries scouts write so future
runs get smarter and quieter. Reading it tells you what the fleet believes about this project.

```json
signals-scout-scratchpad-search
{ "text": "error_tracking" }
```

Returns entries newest-first (capped at 100); `text` matches `content` and `key`
case-insensitively. Omit `text` to browse everything. Each entry's `key` carries a category
prefix that tells you _what kind_ of learning it is:

| Prefix        | Meaning                                                            |
| ------------- | ------------------------------------------------------------------ |
| `pattern:`    | A baseline — how this team's data normally shapes                  |
| `watch:`      | A live issue being tracked but still below the emit bar            |
| `noise:`      | A pattern the fleet has decided to ignore (dev-only, single-user…) |
| `addressed:`  | Something the team fixed or moved on from                          |
| `dedupe:`     | A gate on re-emitting a specific issue / fingerprint / finding     |
| `allowlist:`  | Vetted entities never to re-surface                                |
| `not-in-use:` | A product/surface this team doesn't use (close-out memo)           |
| `mcp-gap:`    | A tooling gap a scout noticed worth raising later                  |

This is the common vocabulary, not a closed set — scouts coin their own prefixes and `<domain>`
labels as needed (the live fleet uses `watch:` heavily, for example), so treat an unfamiliar
prefix as just another category. Entries cross-reference each other with `[[key]]` wikilinks. Keys
follow `<prefix>:<domain>:<entity>` (e.g. `dedupe:error_tracking:019e8375-…`).

When a user asks "why isn't my scout flagging X anymore?", search the scratchpad for `noise:`,
`addressed:`, `dedupe:`, and `allowlist:` entries — the fleet may have deliberately learned to
suppress it. The canonical prefix vocabulary and the four-state dedupe classifier the fleet reasons
in terms of are documented in
[`../authoring-signals-scouts/references/dedupe-and-memory.md`](../authoring-signals-scouts/references/dedupe-and-memory.md).

## Workflow: see what scouts have surfaced

Scout findings reach the user as inbox reports. Filter the inbox to the scout source:

```json
inbox-reports-list
{ "source_product": "signals_scout", "limit": 20 }
```

This is the direct way to find scout-backed reports. Each finding is emitted with
`source_product="signals_scout"`, that tag rides through grouping into the report's signal metadata,
and the inbox filter keeps any report whose contributing signals include `signals_scout` — so the
result is the set of reports the fleet has surfaced.

An empty result means the fleet hasn't emitted (yet), **not** that the filter is broken. Scouts hold
a high bar — most runs close out without emitting — so on a quiet or newly enrolled project zero
scout-backed reports is the normal, expected state. Read it as "nothing surfaced," and fall back to
each run's `summary` for the per-run record of what was (or wasn't) emitted. To browse the inbox more
broadly, use the [`inbox-exploration`](../inbox-exploration/SKILL.md) skill (statuses, suggested
reviewers, drilling into a report's underlying signals). The emit contract behind each finding —
weight, confidence, severity, the description prose — is documented in
[`../authoring-signals-scouts/references/emit-contract.md`](../authoring-signals-scouts/references/emit-contract.md).

## Workflow: assess health and performance

"Is my scout actually working / earning its cost?" There's no single metric — judge a scout over a
window of runs. Pull the runs (`runs-list` with a `date_from`), then reason across the dimensions
below. The full playbook, including how to read each signal and the common failure modes, is in
[`references/assessing-performance.md`](references/assessing-performance.md).

- **Cadence adherence** — are runs landing roughly every `run_interval_minutes`? Large gaps mean
  the coordinator is skipping it (disabled, drained from the flag, or capped out on busy ticks).
- **Success rate** — how many runs reach a clean `status` vs. error out? A run of errors is a
  broken scout, not a quiet one.
- **Emit rate** — what fraction of runs emitted vs. closed out empty. Near-zero over a long window
  on a live surface can mean the discriminator is too strict (or the surface really is quiet);
  near-100% usually means it's too noisy. Most healthy scouts emit rarely.
- **Signal-to-noise** — of what it emitted, how much became actionable inbox reports vs. got
  suppressed? Cross-check emitted findings against `inbox-reports-list` report states.
- **Memory growth** — a healthy scout accumulates `pattern:` / `noise:` / `dedupe:` entries over
  time. A scout with an empty scratchpad after many runs isn't learning.

## Tips

- **Always surface the `emit` posture.** "Running but in dry-run" is the single most common reason
  a user thinks a scout is broken when it isn't.
- **An empty close-out is success.** Most runs should find nothing. Don't report a wall of clean,
  empty runs as a problem.
- **There's no emit flag to filter on.** Neither the run row nor the inbox exposes a clean
  "scout-emitted" filter — judge emit-vs-quiet from each run's `summary`, and don't read an empty
  `source_product: "signals_scout"` inbox result as "the fleet emitted nothing."
- **A ~30-min run that `failed` is usually a timeout, not a broken scout.** Completed runs finish
  in a couple of minutes; a run that ran the full budget and failed over-investigated. The fleet
  self-corrects by writing "tight-run recipe" scratchpad entries.
- **Lead with the run `summary`**, then offer `task_url` for the full transcript — don't dump raw
  run rows at the user.
- **`last_run_at: null`** means a scout has never fired — check it's enabled and the project is
  enrolled before digging further.
- **To explain a quiet scout, read the project profile.** `signals-scout-project-profile-get`
  shows whether the surface it watches is even in use — a logs scout on a project with no logs has
  nothing to do.
- **This skill is read-only.** To change a scout's schedule, posture, or body, hand off to
  [`authoring-signals-scouts`](../authoring-signals-scouts/SKILL.md) — it covers
  `signals-scout-config-update` and the skills-store edit path.
