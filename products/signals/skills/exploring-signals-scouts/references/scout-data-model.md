# Scout data model — what you're reading

Three records describe a scout's life on a project, plus one snapshot it orients from. This
reference is the vocabulary for everything `exploring-signals-scouts` returns.

## SignalScoutConfig — the scout's settings

One row per `(team, skill_name)`. Returned by `signals-scout-config-list`. This is the scout's
control surface, separate from its instruction body (the `LLMSkill`).

| Field                  | Meaning                                                                                       |
| ---------------------- | --------------------------------------------------------------------------------------------- |
| `id`                   | Config id — the handle `signals-scout-config-update` takes to tune it.                        |
| `skill_name`           | The `signals-scout-*` skill this config controls. Fixed; one config per skill per team.       |
| `enabled`              | `false` = paused. The coordinator skips disabled scouts entirely.                             |
| `emit`                 | `false` = **dry-run**: the scout runs and reasons every tick but writes nothing to the inbox. |
| `run_interval_minutes` | Cadence, 10–43200. Default 60 (hourly). The coordinator dispatches when due.                  |
| `last_run_at`          | When it last fired. `null` = never run. Drives the due-check.                                 |

A scout that is `enabled: true, emit: false` is alive and working — it just can't post findings.
This is the intended posture for a new or freshly-edited scout, and the most common cause of "my
scout does nothing" reports.

## SignalScoutRun — one execution

Returned by `signals-scout-runs-list` (summary) and `signals-scout-runs-retrieve` (detail; same
shape). Each run is one sandboxed agent execution of one scout. The run is a thin bridge to a
`tasks.TaskRun` — status, timing, and the full transcript live on the Task side.

`runs-retrieve` takes the run id as `id`, **not** `run_id` — even though the list and the detail
payload both name the field `run_id`. Pass the list's `run_id` value through as `id`.

| Field                    | Meaning                                                                                                                                            |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_id`                 | UUID of the run. Pass it to `runs-retrieve` as `id`. Strictly team-scoped (404 across teams).                                                      |
| `skill_name`             | Which scout ran.                                                                                                                                   |
| `skill_version`          | The body version that ran. If a scout was edited, older runs ran an older version — useful when comparing behavior before/after a change.          |
| `status`                 | Run outcome, from the linked `TaskRun` (see below).                                                                                                |
| `started_at`             | ISO-8601 — when the `TaskRun` was created.                                                                                                         |
| `completed_at`           | ISO-8601 — when it finished. `null` while in flight. Duration = `completed_at - started_at`.                                                       |
| `task_id`, `task_run_id` | Identifiers on the Tasks side.                                                                                                                     |
| `task_url`               | Relative deep-link to the Tasks UI for this run — **the full transcript** (every tool call and reasoning step) lives here, not in the run payload. |
| `summary`                | The scout's own one-paragraph end-of-run close-out. The primary thing to read and relay. Empty for runs that errored before close-out.             |

### Run status values

`status` flows from the linked `tasks.TaskRun`. Treat a completed run with an empty-handed summary
as a **healthy quiet run**, not a failure — most runs should close out empty.

- in-flight / started — currently running (`completed_at` null).
- completed — finished cleanly. May or may not have emitted; read the `summary`.
- failed — the run errored before closing out. Its `summary` is empty and the payload exposes
  **no error field** — read the transcript to see what went wrong (open `task_url`, or pull it as
  data with `tasks-runs-session-logs-retrieve`). In practice the common failure is a ~30-minute
  timeout (the per-run budget), not a logic-broken scout; a `failed` run whose duration ≈ the budget
  is almost always a timeout. The usual cause is over-investigation (the scout ran to the wall), but
  some are false timeouts — the scout finished quickly and the run then hung on a dropped close-out;
  the session log distinguishes the two (tool calls up to the wall vs. silence long before it).

(The exact string set comes from the Tasks `TaskRun` model; match leniently — read the `summary`
and `completed_at` together rather than keying on one status string.)

## Run → finding link (and why it's awkward)

Findings are **not** stored on the run row, and there is no emit flag or finding count on it
either — so you cannot query "which runs emitted" directly from the run. When a scout emits, the
finding goes through `emit_signal()` with `source_product="signals_scout"` /
`source_type="cross_source_issue"` and flows through the same grouping pipeline as every other
source. Each finding gets a deterministic `source_id = run:<run_id>:finding:<finding_id>`:

- The `source_id` is stored at the **top level** of the signal's `metadata` (i.e.
  `metadata.source_id`), alongside `metadata.source_product` — not inside `metadata.extra`. Grouping
  v2 generates its own `document_id` and dedupes on that — never on `source_id` — so re-emitting the
  same `finding_id` creates a second signal rather than updating the first.
- The `source_product="signals_scout"` tag rides through grouping into the persisted signal
  metadata, so a report that contains a scout finding carries `signals_scout` among its contributing
  signals. That's what `inbox-reports-list { "source_product": "signals_scout" }` filters on, and
  it's the direct way to list scout-backed reports.

Two ways to follow a finding, then: filter the inbox by `source_product="signals_scout"` to see the
reports the fleet produced, or read the run's prose `summary` for the per-run record of what a single
run did or didn't emit. A run that closed out empty has no findings — expected and correct most of
the time, since scouts only emit when they clear a high bar.

## SignalScratchpad — durable fleet memory

Returned by `signals-scout-scratchpad-search`. One row per `(team, key)`; re-using a key upserts.
This is the fleet's cross-run memory — prose entries scouts write so future runs are smarter and
quieter.

| Field                       | Meaning                                                                |
| --------------------------- | ---------------------------------------------------------------------- |
| `key`                       | Agent-chosen semantic key, unique per team. Carries a category prefix. |
| `content`                   | Prose, read verbatim into a future run's prompt.                       |
| `created_by_run_id`         | Which run wrote it (`null` if the run was later deleted).              |
| `created_at` / `updated_at` | When written / last rewritten.                                         |

The `key` prefix tells you the kind of learning: `pattern:` (baseline), `watch:` (a live issue
tracked but still below the emit bar), `noise:` (ignore), `addressed:` (fixed/moved on), `dedupe:`
(gate re-emit), `allowlist:` (never re-surface), `not-in-use:` (surface not used), `mcp-gap:`
(tooling gap). This vocabulary is open — scouts coin their own prefixes and `<domain>` labels, so
treat an unfamiliar prefix as just another category. Entries link to each other with `[[key]]`
wikilinks. The canonical prefix set and the four-state dedupe classifier the fleet reasons in terms
of live in
[`../../authoring-signals-scouts/references/dedupe-and-memory.md`](../../authoring-signals-scouts/references/dedupe-and-memory.md).

## SignalProjectProfile — orientation snapshot

Returned by `signals-scout-project-profile-get`. A deterministic, cached snapshot of "what's true
about this project" — products in use, product intents, integrations, warehouse sources, signal
source configs (split enabled/disabled), inbox report counts, and top events with reach/burst
metrics. This is the ground truth every scout cold-starts from.

When exploring, reach for the profile to **explain** scout behavior: a scout watching a surface the
profile shows as absent (no logs, no LLM events, no revenue source) has nothing to do, and its
quiet runs are correct. The profile is ground truth from authoritative tables; the scratchpad is
the fleet's inferred learnings — don't conflate them.

## How the coordinator decides what runs

Useful context when a scout's runs are sparser than its schedule implies. A periodic Temporal
coordinator ticks (~every 30 min) and, for each enrolled team, dispatches every enabled scout whose
schedule is due (`last_run_at is None` or `now - last_run_at >= run_interval_minutes`),
most-overdue first, capped per tick. Enrollment is via the `signals-scout` feature flag's allowlist.
So a scout can be enabled yet run late if: the team was drained from the flag, the scout was
disabled, or busy ticks hit the per-tick cap. There is no sampling — a due, enabled, enrolled scout
runs.
