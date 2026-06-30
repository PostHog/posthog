---
name: exploring-scouts
description: >
  How to explore and make sense of PostHog Signals scouts — the scheduled agents that scan a
  project and emit findings into the Signals inbox. Use when a user wants to understand what
  scouts they have, how each one is behaving, and whether the fleet is actually working. Covers
  surveying the fleet and its schedules, reading recent scout runs and drilling into a single
  run's reasoning, inspecting the durable scratchpad memory the fleet has built up, tracing a
  run to the findings it emitted, and assessing a scout's health and performance over time
  (cadence, success rate, emit rate, signal-to-noise). Read-only and exploratory — to write or
  tune a scout, use `authoring-scouts` instead. Trigger on "what are my scouts doing",
  "how is my <x> scout performing", "show me recent scout runs", "why did this scout find/emit
  nothing", "what has the fleet learned", "explore scout run <id>", "is my scout working".
metadata:
  owner_team: signals
---

# Exploring Signals scouts

A **scout** is a scheduled agent that wakes on its own interval, looks at one PostHog project,
decides what's genuinely worth surfacing, and either emits it as a **finding** into the Signals
inbox or closes out empty (a real, valid outcome). PostHog ships a fleet of canonical scouts — a
cross-product generalist (`signals-scout-general`) plus per-surface specialists (error tracking,
logs, AI observability, experiments, feature flags, session replay, web analytics, surveys, and
more). A project may also have **custom scouts** beyond the canonical fleet — any
`signals-scout-*` skill a team authored (e.g. `-brand-mentions`, `-mcp-feedback`) shows up here
too, so don't assume a fixed roster: `signals-scout-config-list` is the authoritative roster for
a project. (One caveat: a just-authored scout has no config row until the coordinator's next
tick auto-registers one — or until someone registers it via the write-side
`signals-scout-config-create` — so a brand-new scout may briefly be missing from the list.)

This skill helps you **understand and explore what a project's scouts are doing and how they're
performing** — entirely through read-only MCP tools. It is the observability counterpart to
the `authoring-scouts` skill (which teaches writing and tuning) and to the
`inbox-exploration` skill (which covers the inbox reports scouts feed into).

**Scouts come in two output channels — know which one you're looking at.** Most scouts
**emit weak findings** (`emit_signal`) that the pipeline groups into reports; their output shows
up as `emitted_count` / `emitted_finding_ids` on a run. A few scouts (those listing
`emit_report` / `edit_report` in `allowed_tools` — the canonical generalist `signals-scout-general`
is the first) **author or edit inbox reports 1:1 directly**, skipping the pipeline; their output
shows up as `emitted_report_ids` / `edited_report_ids` instead, and **their `emitted_count` stays
0 even on a productive run**. Don't read `emitted_count: 0` as "did nothing" without checking the
report columns and the run summary first.

There are six things you can observe about the fleet, each with its own tool:

| What you want to know                        | Tool                                     | What it tells you                                                                      |
| -------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------- |
| Which scouts run, how often, in what posture | `signals-scout-config-list`              | One row per scout: schedule, `enabled`, `emit`, `last_run_at`, `description`           |
| What the scouts actually did, run by run     | `signals-scout-runs-list` / `-retrieve`  | Per-run status, timing, end-of-run summary, `emitted_count`, deep-link                 |
| What the fleet has learned across runs       | `signals-scout-scratchpad-search`        | Durable per-team memory (baselines, noise, allowlists)                                 |
| What the scouts actually **emitted**         | `execute-sql` over `document_embeddings` | The authoritative per-finding record (weight, severity, confidence) — see below        |
| Which of a run's findings became reports     | `signals-scout-runs-emission-reports`    | Per-emission link from a run's finding to the inbox report it grouped into (or `null`) |
| What the scouts surfaced to the user         | `inbox-reports-list`                     | Findings that cleared the bar and became inbox reports                                 |

The orienting tool is `signals-scout-project-profile-get` — the deterministic snapshot of "what's
true about this project" that every scout cold-starts from. When a scout found nothing, this is
usually why.

## Output handling: expect to offload to a file

Two of these tools — `signals-scout-runs-list` and especially
`tasks-runs-session-logs-retrieve` — routinely return payloads that **overflow an MCP client's
token budget and get spilled to a file**. This is the normal path, not an error. Plan for it up
front rather than discovering it after a failed call:

- **Keep `limit` small** on `signals-scout-runs-list` (~10–15). Each row carries a long prose
  `summary`, and runs come back newest-first across the _whole_ fleet, so even a modest page is
  large.
- **Session logs are large by nature.** A single run's log is hundreds of KB to a few MB. Fetch it
  with **`call --json`** (so the saved file is real JSON, not the pretty text format — `jq`-able)
  and read the saved file with `jq` / a script rather than inline.
- **Don't hand-parse the session log.** The bundled [`scripts/`](#helper-scripts) do the
  reconstruction for you — see below.

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
  but writes nothing to the inbox), and `last_run_at`. One caveat before reporting "it's live": runs
  are gated by the `signals-scout` feature flag, not by `enabled`. A project that was enrolled and
  later drained from the flag keeps its `enabled: true` rows, but the coordinator no longer plans
  runs for it — so a stale or `null` `last_run_at` on an enabled scout usually means the project is
  no longer enrolled, not that the scout is idle.

  **`last_run_at` is a _dispatch_ stamp, not proof a run executed.** The coordinator advances it the
  moment it _enqueues_ a child workflow for a due scout — before any worker picks the run up. Child
  dispatch is fire-and-forget, so if workers are saturated or down the children just queue and no
  run ever materializes, yet `last_run_at` keeps marching forward each tick. So a recent
  `last_run_at` means "dispatched this tick," **not** "a run is genuinely happening." The
  authoritative liveness signal is the newest actual **run row** in `signals-scout-runs-list`, not
  the config stamp. Cross-check them: if `last_run_at` is fresh (minutes ago) but no run row has
  appeared for that scout in well over its `run_interval_minutes`, the fleet is **dispatching but
  not running** — workers backed up / down, or runs stranded — a real reliability problem, not a
  live scout. Don't report "it's running" off `last_run_at` alone.

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
2. **Read its body** — `posthog:skill-get {"skill_name": "signals-scout-error-tracking"}`
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
- **Filter by emit outcome** with `emitted` — `emitted=true` returns only runs that surfaced at
  least one finding, `emitted=false` only the quiet runs. This is the direct way to answer "which
  runs actually emitted something?" without parsing prose.

Each summary row carries `run_id`, `skill_name`, `skill_version`, `status`, `started_at`,
`completed_at`, `emitted_count` (how many findings the run emitted), `emitted_finding_ids` (their
ids), `emitted_report_ids` / `edited_report_ids` (reports a report-authoring scout wrote or edited
directly — see the report-channel note below), `task_url` (a deep-link into the Tasks UI for the
full transcript), and the `summary` prose.
Lead with the `summary` when narrating to the user — it's the scout's own plain-language close-out —
and always offer the `task_url` for the full reasoning.

## Workflow: drill into a single run

When the user wants the full story of one run (or pastes a run id / Tasks URL):

```json
signals-scout-runs-retrieve
{ "id": "<uuid>" }
```

Note the field name flip: `runs-list` returns each run's id as `run_id`, but `runs-retrieve`
takes it as `id`. Pass the `run_id` value through as `id`.

Returns the full run: `status`, `started_at` / `completed_at` (compute duration from these),
`skill_name` / `skill_version` (what ran, at what body version), the end-of-run `summary`,
`emitted_count` / `emitted_finding_ids`, and `task_url`. The transcript — the actual tool calls and
reasoning — lives in the Tasks UI behind `task_url`, not in this payload; hand the user that link
when they want to see every step. A **failed** run returns an empty `summary` and **no error
field** — the payload looks the same as the list row, so to learn _why_ it failed you need the
transcript.

You don't have to open the UI for that: **`tasks-runs-session-logs-retrieve` returns the run's
session log (every tool call, message, and reasoning step) as data** — handy when you're
diagnosing a failure or want to trace exactly what a run did without leaving the conversation. Pass
the run's `task_run_id` as `id` and its `task_id` (both are on the run row).

The raw stream is large (hundreds of KB to a few MB) and will overflow inline, so **fetch it with
`call --json` and let it spill to a file**, then run it through
[`scripts/render_run_report.py`](#helper-scripts) rather than parsing it by hand.

⚠️ **Do not reach for `exclude_types: "tool_call_update,…"` to slim it down.** It is tempting —
the stream is dominated by incremental `tool_call_update` chunks — but each tool's **actual input
lives only in those chunks**: the base `tool_call` event carries an empty `rawInput`, and the
streamed updates build the input (and the final `rawOutput`) token by token. Excluding them leaves
you with tool _names_ but no idea what the scout actually queried. Fetch the **full** log and let
the script reassemble each call (it groups by `toolCallId`, keeps the richest `rawInput`, and
attaches the completion's `rawOutput`/`status`).

**Whether a run emitted is a first-class field: `emitted_count`.** For a **signal scout**,
`emitted_count > 0` means the run surfaced that many findings and `emitted_count: 0` means it closed
out empty. Don't parse the prose `summary` for this any more — a phrase like "already emitted P1 …
did not re-emit" describes a _prior_ run, so substring-matching the summary for "emitted" is
unreliable, whereas `emitted_count` is the authoritative tally. `emitted_finding_ids` lists the
`finding_id`s behind that count, in emit order; each maps to a `Signal` with
`source_id = run:<run_id>:finding:<finding_id>`, giving a reliable run → finding link. See
[`references/scout-data-model.md`](references/scout-data-model.md) for the run-to-finding link and
how an emitted finding rides through grouping into the `source_product: "signals_scout"` inbox
filter.

**For a report-authoring scout, `emitted_count` is the wrong field — it stays 0.** A report scout
(`emit_report` / `edit_report` in `allowed_tools`) doesn't emit weak findings; it writes reports
directly, tallied on the run as **`emitted_report_ids`** (reports it authored via `emit_report`) and
**`edited_report_ids`** (reports it mutated via `edit_report`). So a productive report-scout run
reads `emitted_count: 0` with a non-empty `emitted_report_ids` and a summary like
`Report authored: <id>`. Check those columns (and the inbox report itself via
`inbox-reports-retrieve`) before concluding a report scout did nothing.

**To go from a run straight to the _reports_ its findings produced**, call
`signals-scout-runs-emission-reports` with the run's `run_id` instead of re-deriving the link by
hand. It returns one row per emission — the `finding_id`, its `source_id`, and the linked inbox
`report` (`id`, `title`, `status`), or `null` when that finding never grouped into a report (or the
report was deleted/suppressed). This is the direct answer to "did this run's findings actually
become inbox reports?" — the run-scoped equivalent of the cross-referencing the signal-to-noise
health check (below) otherwise does by hand. It's strictly team-scoped (a foreign run UUID returns 404) and
needs `task:read` on top of `signal_scout:read`, since it exposes report titles.

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
suppress it. The canonical prefix vocabulary and the four-state dedupe classifier the fleet
reasons in terms of are documented in the `authoring-scouts` skill
(`references/dedupe-and-memory.md`).

## Workflow: list what scouts have actually emitted

"What has the fleet emitted lately / show me every finding my scouts produced." The run row
carries no emit flag and no finding count, the prose `summary` is heuristic, and the inbox
filter (below) is lossy because grouping merges scout findings into mixed-source clusters. The
**authoritative** per-finding record is the emitted signal itself, in the `document_embeddings`
table — queryable for any team via `execute-sql` (the general path). When a scout emits,
`emit_signal` writes a signal with `source_product="signals_scout"`; the scout's attribution
(`skill_name`, `finding_id`, `severity`, `confidence`) lands in `metadata.extra`, with `weight`
and `source_id` at the top level.

Fetch with `execute-sql` and format with [`scripts/emitted_signals.py`](#helper-scripts) — the
exact query lives in the script's header. One row per finding, filterable by any set of scouts:

```bash
#   call --json execute-sql { "truncate": false, "query": "<the emitted-signals query>" }  -> emitted.txt
python scripts/emitted_signals.py --signals emitted.txt --now <ISO> [--skill mcp-feedback,general]
```

A row here is **ground truth that a finding persisted** — it cleared every emit gate. The flip
side matters when explaining a gap: a scout can narrate "EMITTED ..." in its `summary` yet have
the emit **silently dropped** by a preflight gate (dry-run at the time, the org hasn't approved
AI processing, or the `signals_scout` source is disabled), or the emit failed. Those never reach
this table, so a claimed-but-absent finding is itself a diagnostic, not a script bug. The emit
contract behind each row (weight vs. confidence rubrics, severity, dedupe) is documented in the
`authoring-scouts` skill (`references/emit-contract.md`); the run → finding link and its
limits are in [`references/scout-data-model.md`](references/scout-data-model.md).

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
scout-backed reports is the normal, expected state. For the per-run view of what emitted, work from
the runs instead: `signals-scout-runs-list?emitted=true` lists every emitting run, and each run's
`emitted_count` / `emitted_finding_ids` tell you how many and which findings it produced (each
`finding_id` maps to a `Signal` with `source_id = run:<run_id>:finding:<finding_id>`). To browse the
inbox more broadly, use the `inbox-exploration` skill (statuses, suggested reviewers, drilling
into a report's underlying signals). The emit contract behind each finding — weight, confidence,
severity, the description prose — is documented in the `authoring-scouts` skill
(`references/emit-contract.md`).

## Workflow: assess health and performance

"Is my scout actually working / earning its cost?" There's no single metric — judge a scout over a
window of runs. Pull the runs (`runs-list` with a `date_from`), then reason across the dimensions
below. The full playbook, including how to read each signal and the common failure modes, is in
[`references/assessing-performance.md`](references/assessing-performance.md).

- **Cadence adherence** — are runs landing roughly every `run_interval_minutes`? Large gaps mean
  the coordinator is skipping it (disabled, drained from the flag, or capped out on busy ticks) —
  _or_ it's dispatching but the runs aren't materializing. Tell the two apart with `last_run_at`: if
  the config's `last_run_at` is also stale, the coordinator stopped planning it; if `last_run_at` is
  fresh but the newest run row is hours old, it's the dispatch-vs-execution divergence above (workers
  backed up / down, or runs stranded), which `runs-list` alone hides.
- **Success rate** — how many runs reach a clean `status` vs. error out? A run of errors is a
  broken scout, not a quiet one.
- **Emit rate** — what fraction of runs emitted vs. closed out empty. Read it straight off
  `emitted_count` per run (or split the window with `runs-list?emitted=true` / `?emitted=false`).
  Near-zero over a long window on a live surface can mean the discriminator is too strict (or the
  surface really is quiet); near-100% usually means it's too noisy. Most healthy scouts emit rarely.
- **Signal-to-noise** — of what it emitted, how much became actionable inbox reports vs. got
  suppressed? `signals-scout-runs-emission-reports` gives this per run directly — each emitted
  finding paired with the report it grouped into (or `null` if it never surfaced) — so across a
  window the share of emissions with a live, non-suppressed report is the scout's hit rate. (You can
  still derive it by hand: tie each run's `emitted_finding_ids` to their `Signal` rows and
  cross-check `inbox-reports-list` states — `signals-scout-runs-emission-reports` is just the shortcut.)
- **Memory growth** — a healthy scout accumulates `pattern:` / `noise:` / `dedupe:` entries over
  time. A scout with an empty scratchpad after many runs isn't learning.

## Helper scripts

The skill bundles four **pure formatters** under [`scripts/`](scripts/) for the most common asks.
They do **no network I/O** — they are the back half of an "agent fetches, script formats" split.
The pattern is always the same:

1. Fetch each payload with the MCP using **`call --json`** (raw JSON, not the pretty text format)
   and save it to a file. For the big ones (`runs-list`, `tasks-runs-session-logs-retrieve`) this
   is mandatory anyway — they overflow inline and spill to a file you can point the script at.
2. Run the script over those files.

All four are stdlib-only Python 3.11+ and print **plain text** to stdout (or `--out`) — designed
to read well in a terminal, so save them as `.txt`.

### `scripts/render_run_report.py` — drill into one run

Produces the kind of detailed write-up you'd want when inspecting a single run: header
(status, duration, posture), a **narrated timeline that interleaves the agent's narration with
each tool call _and its real input_**, the end-of-run summary, and any scratchpad memory.

```bash
# fetch (note --json), saving each to a file:
#   call --json signals-scout-runs-retrieve { "id": "<run_id>" }            -> run.json
#   call --json tasks-runs-session-logs-retrieve { "id": "<task_run_id>", "task_id": "<task_id>", "offset": 0 }  -> log.json   (FULL — no exclude_types)
#   (optional) call --json signals-scout-scratchpad-search { ... }          -> mem.json
#   (optional) call --json signals-scout-config-list {}                     -> cfg.json
python scripts/render_run_report.py --run run.json --log log.json \
    --scratchpad mem.json --config cfg.json --out report.txt
```

Modes (`--mode`, default `detailed`):

| Mode       | Contains                                                           | `--log` needed? |
| ---------- | ------------------------------------------------------------------ | --------------- |
| `summary`  | header + posture + close-out prose                                 | no              |
| `detailed` | + narrated timeline with tool **inputs** + tool tally + scratchpad | yes             |
| `full`     | + each tool call's (truncated) **output** inline                   | yes             |

Other flags: `--show-output` (outputs in detailed mode), `--input-width` / `--output-width`
(truncation), `--no-art` (skip the hedgehog banner), `--base-url` (defaults to `us.posthog.com`).

### `scripts/fleet_survey.py` — survey the whole fleet

One scannable table — scout, enabled, posture, cadence, last run, last outcome — with a "worth a
look" section that flags never-run, stuck-in-dry-run, and last-run-failed scouts.

```bash
#   call --json signals-scout-config-list {}                 -> cfg.json
#   (optional) call --json signals-scout-runs-list { "limit": 30 }  -> runs.json   (small limit!)
python scripts/fleet_survey.py --config cfg.json --runs runs.json --now <current-ISO-time>
```

Pass `--now` (the current time, ISO-8601) to get relative "ago" columns; the emit/quiet column is
a **heuristic** on each run's summary prose — confirm against the summary before trusting it.

### `scripts/assess_health.py` — health over a window of runs

Implements the "assess health and performance" workflow above: a per-scout table (runs, success
%, emit %, cadence gap vs interval, adherence, median duration, memory growth) plus a "worth a
look" section flagging all-failed scouts, timeout-shaped failures, cadence stalls, staleness, and
empty scratchpads.

```bash
#   call --json signals-scout-runs-list { "limit": 100, "date_from": "<ISO>" }  -> runs.json
#   (optional) call --json signals-scout-config-list {}                          -> cfg.json
#   (optional) call --json signals-scout-scratchpad-search {}                    -> mem.json
python scripts/assess_health.py --runs runs.json --config cfg.json \
    --scratchpad mem.json --now <current-ISO-time> [--skill signals-scout-general]
```

`--config` is what lets it score cadence adherence (the expected interval) and staleness (the
authoritative `last_run_at`, which the windowed runs can miss when the 100-row cap truncates the
newest runs). Without `--scratchpad` the memory column shows `n/a` and no memory flags fire. The
emit % is the same summary-prose heuristic — cross-check signal-to-noise against
`inbox-reports-list`.

### `scripts/emitted_signals.py` — every finding the fleet actually emitted

Implements the "list what scouts have actually emitted" workflow: the authoritative per-finding
table (when, scout, severity, weight, confidence, `finding_id`, one-line hypothesis) plus a
per-scout rollup (emit count, severity mix, weight range, latest emit). Unlike `assess_health`'s
emit **%** — a prose heuristic — this reads the emitted signals directly, so it's exact.

Its input is **not** a `signals-scout-*` tool; it's an `execute-sql` result over
`document_embeddings` (the general, any-team path). The full query lives in the script's header —
copy it verbatim. `execute-sql` returns a pipe-delimited text table (even under `call --json` it's
that text wrapped in a JSON string), so the script parses that text; the query deliberately selects
only pipe-safe scalar columns (the multi-line `description` is excluded, `hypothesis` is sanitized).

```bash
#   call --json execute-sql { "truncate": false, "query": "<emitted-signals query from the header>" }  -> emitted.txt
python scripts/emitted_signals.py --signals emitted.txt --now <current-ISO-time> \
    [--skill mcp-feedback,general] [--severity P0,P1,P2] [--since <ISO>] [--sort weight] [--wide]
```

`--skill` takes a comma-separated set (the `signals-scout-` prefix is optional). `--wide` adds the
`scout_run_id` so you can chain straight into `render_run_report.py` for the run that emitted a
finding. Remember the coverage caveat: this lists signals that **persisted** — a finding a run
summary claims but that's absent here was gated (dry-run / AI processing not approved / source
disabled) or failed.

## Tips

- **Always surface the `emit` posture.** "Running but in dry-run" is the single most common reason
  a user thinks a scout is broken when it isn't.
- **An empty close-out is success.** Most runs should find nothing. Don't report a wall of clean,
  empty runs as a problem.
- **Emit-vs-quiet is a first-class run field.** Filter runs directly with `runs-list?emitted=true`
  (or read `emitted_count` per run) to find what emitted, without parsing the prose `summary`. The
  `source_product: "signals_scout"` inbox filter lists the _reports_ the fleet surfaced; an empty
  result there means it hasn't emitted yet (scouts hold a high bar), not that the filter is broken.
- **Check the output channel before judging a report scout.** A report-authoring scout
  (`emit_report` / `edit_report` in `allowed_tools`, e.g. `signals-scout-general`) leaves
  `emitted_count: 0` even when productive — its work is in `emitted_report_ids` / `edited_report_ids`
  and the inbox report it wrote. `runs-list?emitted=true` and emit-% health metrics key off
  `emitted_count`, so they undercount report scouts; judge those by their report columns instead.
- **A ~30-min run that `failed` is usually a timeout, not a broken scout.** Completed runs finish
  in a couple of minutes. Most often the scout over-investigated and ran the full budget (the fleet
  self-corrects by writing "tight-run recipe" scratchpad entries) — but some are false timeouts
  where the scout actually finished in a few minutes and the run then hung on a dropped close-out.
  The session log (above) tells them apart: real over-investigation shows tool calls right up to the
  wall; a false timeout goes silent long before it. Don't assume over-investigation from duration
  alone.
- **Lead with the run `summary`**, then offer `task_url` for the full transcript — don't dump raw
  run rows at the user.
- **`last_run_at: null`** means a scout has never fired — check it's enabled and the project is
  enrolled before digging further.
- **To explain a quiet scout, read the project profile.** `signals-scout-project-profile-get`
  shows whether the surface it watches is even in use — a logs scout on a project with no logs has
  nothing to do.
- **This skill is read-only.** To change a scout's schedule, posture, or body, hand off to
  the `authoring-scouts` skill — it covers `signals-scout-config-update` and the
  skills-store edit path.
