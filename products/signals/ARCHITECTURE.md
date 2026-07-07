# Signals System Architecture

## Overview

The **Signals** product is a signal grouping and report-generation pipeline. Signals from multiple products and integrations — including session replay, AI observability, error tracking, GitHub, Linear, Zendesk, and the headless **Signals agent** itself (a scheduled scout that emits cross-source findings into the same pipeline) — are emitted into a shared ClickHouse embeddings table, grouped into **SignalReports** via embedding similarity + LLM matching, and then optionally promoted into an agentic report-research flow.

Today the active ingestion path is **emitter → buffer → grouping v2**. The summary path is no longer a simple "summarize signals" LLM step: it runs a report-level safety judge, selects a repository, then performs sandbox-backed multi-turn research that produces findings, actionability, priority, title, summary, and suggested reviewers. Reports that are immediately actionable can automatically start a Tasks coding run via the **autonomy** system.

A report is a **living document**: every piece of work done on it — judgments, repo selection, research findings, pushed commits, task runs, free-form notes — is recorded as an attributed, schema-validated, append-only `SignalReportArtefact`. The status-bearing types resolve latest-wins; the rest accumulate as a work log. This is the surface autonomous agents (the pipeline, custom scouts, and other inbox-driven products) read and write as they act on a report.

---

## Temporal Workflows

Signals ingestion uses a three-stage pipeline: **emitter → buffer → grouping v2**. The emitter and buffer workflows are defined in `backend/temporal/emitter.py` and `backend/temporal/buffer.py`. The grouping v2 workflow is in `backend/temporal/grouping_v2.py` and delegates to the shared `_process_signal_batch()` implementation in `backend/temporal/grouping.py`. The report summary workflow is defined in `backend/temporal/summary.py`.

The original `TeamSignalGroupingWorkflow` (v1) in `backend/temporal/grouping.py` is still registered but is no longer started by `emit_signal()`. Its shared activities and `_process_signal_batch()` implementation are still actively used by v2.

Signals workflows and activities are registered in `backend/temporal/__init__.py` and wired into the `VIDEO_EXPORT_TASK_QUEUE` worker by `posthog/management/commands/start_temporal_worker.py`.
If you add or remove a Signals workflow/activity from `backend/temporal/__init__.py`, you also need to update `posthog/temporal/tests/ai/test_module_integrity.py` (`TestSignalsProductModuleIntegrity`). That test intentionally snapshots the registered workflow/activity lists and will fail until its expected names are updated.

Several additional Signals workflows also exist but are not part of the main report pipeline:

- `backfill-error-tracking` (`backend/temporal/backfill_error_tracking.py`) — backfills recent error tracking issues as signals
- `emit-eval-signal` (`backend/temporal/emit_eval_signal.py`) — converts LLMA evaluation results into Signals inputs on the Signals worker queue
- `run-signals-scout-coordinator` (`backend/temporal/agentic/scout_coordinator.py`) — periodic tick (every `COORDINATOR_INTERVAL_MINUTES = 30`) that fans out scheduled `signals-scout-*` scout runs per (team, skill). Spec'd separately below.
- `RunSignalsScoutWorkflow` (`backend/temporal/agentic/scout_scheduler.py`) — child workflow per planned run; thin wrapper around the harness activity. Spec'd separately below.

### Activity decoration

Every async Signals Temporal activity is decorated with `@scoped_temporal()` from `posthog/temporal/common/scoped.py` (not upstream `@posthoganalytics.scoped()`). It scopes `posthoganalytics.tag()` calls to the activity invocation and auto-captures uncaught exceptions into PostHog error tracking with the workflow's tags attached. The upstream decorator wraps `async def` in a sync wrapper, breaking Temporal's `iscoroutinefunction` dispatch — the worker returns the unawaited coroutine and crashes on JSON encoding. `scoped_temporal()` is the async-aware equivalent (sync helpers can keep using upstream `@posthoganalytics.scoped()`).

```python
from posthog.temporal.common.scoped import scoped_temporal

@temporalio.activity.defn
@scoped_temporal()
async def my_activity(input: ...) -> ...:
    ...
```

### Signal Ingestion Pipeline (v2)

The v1 `TeamSignalGroupingWorkflow` buffered raw `EmitSignalInputs` in memory and carried them over on `continue_as_new`. Under higher signal volume the `continue_as_new` payload could grow too large. The v2 pipeline fixes that by flushing buffered signals to object storage and passing only lightweight object keys between workflows.

```text
emit_signal()                       SignalEmitterWorkflow              BufferSignalsWorkflow              TeamSignalGroupingV2Workflow
     │                                     │                                  │                                  │
     ├─ start (idempotent) ───────────────────────────────────────────────────►│                                  │
     │                                     │                                  │                                  │
     ├─ start (fire-and-forget) ──────────►│                                  │                                  │
     │                                     │                                  │                                  │
     │                              activity: query buffer size               │                                  │
     │                                     ├─ get_buffer_size ───────────────►│                                  │
     │                                     │◄─ size ─────────────────────────┤│                                  │
     │                                     │  (poll+sleep if full)            │                                  │
     │                              activity: signal submit_signal            │                                  │
     │                                     ├─────────────────────────────────►│                                  │
     │                                     │                                  │                                  │
     │                                     │                           (buffer fills / timeout)                  │
     │                                     │                                  │                                  │
     │                                     │                           activity: safety filter + flush           │
     │                                     │                                  ├──► object storage: signals/signal_batches/<uuid>
     │                                     │                                  │                                  │
     │                                     │                           activity: signal-with-start               │
     │                                     │                                  ├─ submit_batch(object_key) ──────►│
     │                                     │                                  │                                  │
     │                                     │                           continue_as_new                    activity: read from object storage
     │                                     │                                  │                                  ├──► object storage
     │                                     │                                  │                                  │
     │                                     │                                  │                           _process_signal_batch()
     │                                     │                                  │                                  │
     │                                     │                                  │                           continue_as_new
```

### `SignalEmitterWorkflow` (`signal-emitter`)

Ephemeral per-signal workflow that provides backpressure between `emit_signal()` and the buffer. One instance per signal, with workflow ID `signal-emitter-{team_id}-{uuid}`.

Defined in `backend/temporal/emitter.py`.

**Flow:**

1. Run `submit_signal_to_buffer_activity`, which:
   a. **Queries** the buffer workflow’s `get_buffer_size` query
   b. If the buffer is full (`>= BUFFER_MAX_SIZE`), **polls with jittered sleep** until space is available, heartbeating while it waits
   c. **Signals** the buffer workflow’s `submit_signal` handler with the signal

This keeps `emit_signal()` fire-and-forget while the emitter workflow absorbs backpressure. The activity currently uses a **3-hour** `start_to_close_timeout` and **10-minute** `heartbeat_timeout`.

### `BufferSignalsWorkflow` (`buffer-signals`)

Buffers incoming signals in memory and periodically flushes them to object storage. One instance per team, with workflow ID `buffer-signals-{team_id}`.

Defined in `backend/temporal/buffer.py`.

**Architecture:**

- New signals arrive via `@workflow.signal` (`submit_signal`), sent by `SignalEmitterWorkflow` instances.
- Exposes `@workflow.query` (`get_buffer_size`) so emitters can implement backpressure by polling buffer occupancy before sending.
- The main loop waits for signals, then waits until either the buffer reaches `BUFFER_MAX_SIZE` (20) or `BUFFER_FLUSH_TIMEOUT_SECONDS` (5s) elapses since the first signal arrived.
- On flush: drains the buffer, runs the **safety filter** on all signals in parallel via `safety_filter_activity`, writes the safe signals to object storage at `signals/signal_batches/<uuid>` via `flush_signals_to_s3_activity`, then sends the object key to the grouping v2 workflow via `signal_with_start_grouping_v2_activity` (which starts the workflow if needed). If the entire batch is unsafe, the flush and grouping steps are skipped.
- If the buffer is already full again after flushing (signals arrived during the flush activities), it loops immediately and flushes again rather than paying a `continue_as_new` restart cost.
- Otherwise it calls `continue_as_new`, carrying over any signals that arrived between drain and now via `BufferSignalsInput.pending_signals`.
- Stored batch objects are cleaned up by object-storage lifecycle policies, not by the workflows.

### `TeamSignalGroupingV2Workflow` (`team-signal-grouping-v2`)

Long-running entity workflow that processes batches of signals from object storage. One instance per team, with workflow ID `team-signal-grouping-v2-{team_id}`.

Defined in `backend/temporal/grouping_v2.py`.

**Architecture:**

- Receives object keys via `@workflow.signal` (`submit_batch`), sent by `BufferSignalsWorkflow`.
- Buffers pending object keys in memory as `list[str]`, which is much lighter than buffering full `EmitSignalInputs`.
- The main loop waits for a batch key, downloads the signals via `read_signals_from_s3_activity`, then processes the full batch via `_process_signal_batch()` from `grouping.py`.
- Caches signal type examples across batches with a TTL (`TYPE_EXAMPLES_CACHE_TTL`, 5 minutes).
- Calls `continue_as_new` after each batch, carrying over any pending keys that arrived during processing.
- Supports **pause/unpause** via `set_paused_until`, `clear_paused`, and `get_paused_state`. The API exposes this through `SignalProcessingViewSet`.
- Errors processing a batch are caught and logged — the workflow continues to the next batch.

### `TeamSignalGroupingWorkflow` (`team-signal-grouping`) — v1, legacy

A long-running entity workflow that serializes all signal grouping for a single team. Exactly one instance per team, with workflow ID `team-signal-grouping-{team_id}`. **It is still registered, but `emit_signal()` no longer starts it.**

**What is still active:**

- The workflow class itself is legacy.
- The shared `_process_signal_batch()` implementation in this file is still the active grouping implementation used by v2.

**Signal processing flow** (per batch, in `_process_signal_batch()`):

1. **Embed** all signal descriptions + **fetch signal type examples** from ClickHouse in parallel
2. **Generate 1–3 search queries** per signal via LLM, using type examples for cross-source context
3. **Embed each query**
4. **Semantic search** the ClickHouse `document_embeddings` HogQL alias for nearest neighbors via `cosineDistance()`
5. **LLM match** — decide whether the signal belongs to an existing report or needs a new one.
   For teams with the `signals-combined-match-specificity` feature flag enabled (checked once per batch via `check_combined_match_enabled_activity`, behind the `combined-match-specificity` workflow patch), this and the specificity check run as **one combined LLM call**: member signals of every candidate report are fetched up front (`fetch_signals_for_reports_activity`, one ClickHouse query) and `match_and_verify_signal_activity` matches and applies the PR test together, so the two stages can never disagree. For all other teams, an existing-report match goes through a separate **match-specificity verification** LLM call afterwards.
6. **Assign** the signal to a `SignalReport` in Postgres, increment counts/weights, check promotion threshold, and **emit** the signal into the embeddings pipeline in one atomic operation
7. **Wait for ClickHouse** — poll until the just-emitted signals are query-visible so subsequent grouping decisions can find them
8. If promoted (weight ≥ threshold), **spawn child** `SignalReportSummaryWorkflow` with `ParentClosePolicy.ABANDON`; `WorkflowAlreadyStartedError` is ignored

Steps 1–4 run in parallel across the batch. Steps 5–7 run sequentially per signal, and earlier-in-batch matches are injected into later signals’ candidate sets before the LLM match call.

### `SignalReportSummaryWorkflow` (`signal-report-summary`)

Runs when a report is promoted to `candidate`. The current flow is **safety judge → repository selection → agentic research → state transition**.

Defined in `backend/temporal/summary.py`.

**Flow:**

1. **Fetch signals** for the report from ClickHouse → `fetch_signals_for_report_activity`
2. **Mark in-progress** in Postgres and advance `signals_at_run` by 3 → `mark_report_in_progress_activity`
3. **Safety judge** → `report_safety_judge_activity`
   - Evaluates the underlying signals for prompt injection / manipulation attempts
   - Persists a `safety_judgment` artefact
4. **Select repository** → `select_repository_activity` (`temporal/agentic/select_repository.py`) — see Repository Selection below
   - If no repository is selected, the workflow synthesizes a “repository selection required” title/summary and transitions to `pending_input`
5. **Agentic research** → `run_agentic_report_activity` (`temporal/agentic/report.py`)
   - Sandbox-backed multi-turn research over the selected repository plus MCP data
   - Appends `repo_selection`, `signal_finding`, `actionability_judgment`, `priority_judgment`, and `suggested_reviewers` artefacts atomically on success (append-only — on re-research only entries that actually changed are appended)
6. **Conditional coding-task auto-start** (inside `run_agentic_report_activity`) — see Autonomy & Auto-Start below
7. **Apply the decision**:
   - If **not actionable** → `reset_report_to_potential_activity` (weight resets to 0, status becomes `potential`)
   - If **requires human input** → `mark_report_pending_input_activity`
   - If **immediately actionable** → `mark_report_ready_activity`
8. If new signals arrived during the run, `mark_report_ready_activity` re-promotes the report to `candidate` and the workflow loops internally rather than spawning a new workflow
9. When a run completes without immediately looping, the workflow publishes a Kafka `signals report completed` message via `publish_report_completed_activity`

On any unhandled exception, the workflow marks the report `failed` and re-raises.

**Timeout / retry details:**

- The grouping workflow starts the summary child with a **1-hour `execution_timeout`**, not 5 hours
- The heavy step is the agentic research activity, which uses a **4-hour `start_to_close_timeout`** and **5-minute heartbeat timeout**
- Most activities use 3-attempt retry policies
- Repo selection and agentic research use single-attempt retries to avoid duplicate sandbox work

#### Repository Selection

Before running the agentic research, the workflow calls `select_repository_activity` (`temporal/agentic/select_repository.py`) — a separate activity that selects the most relevant repository from the team’s GitHub integrations via `select_repository_for_report()` (`report_generation/select_repo.py`).

Keeping repository selection in its own activity gives it independent retry / timeout behavior and makes it reusable across re-promotions.

- **Re-promoted report:** loads and reuses the latest `repo_selection` artefact if it contains a repository
- **0 repos connected:** returns `None` → workflow transitions to `pending_input`
- **1 repo connected:** returns it directly
- **N repos connected:** runs a sandbox repo-discovery agent using `PostHog/.github` as a lightweight dummy clone; the agent uses `gh` CLI to inspect candidate repositories and choose the best match
- The activity runs in a sandbox environment restricted to GitHub-related domains

##### Repository heavy cache

`IntegrationRepositoryCacheEntry` (Postgres, defined in `posthog/models/integration_repository_cache.py`) stores per-repo README + recursive blob paths + descriptive metadata, populated lazily by `GitHubRepositoryFullCache.sync_full_cache_entry()`. It's exposed to the selection agent as the HogQL system table `system.integration_repository_cache` so the agent can grep paths server-side via `ARRAY JOIN splitByString('\n', tree_paths)` instead of hitting GitHub's `/search/code` endpoint (30 req/min hard ceiling). The lightweight (id, name, full_name) list stays on `Integration.repository_cache` (JSONField) so the IDE repo-dropdown read path is unchanged.

`sync_full_cache_entry()` uses a two-tier freshness check, both keyed off `default_branch_sha` as the hydration sentinel (so repos legitimately without a README still hit the fast paths):

1. **TTL gate** — fresh row → return immediately, zero API calls.
2. **SHA gate** — past TTL, two cheap calls to compare the live default-branch SHA against the cached one. Match → refresh only mutable metadata, skip README and tree refetch.
3. **Heavy refetch** — SHA changed → fetch README and the recursive file tree pinned to the same commit, then upsert.

Bulk sync (`sync_full_cache`) fans the per-repo sync out via `run_parallel_with_backoff` (concurrency 10) over the JSONField list as source of truth — orphan rows are evicted, per-repo errors are returned in-place rather than raised. Secondary rate limits propagate with retry hints so the helper backs off cooperatively. The bulk sync is **single-flighted per integration** via a Redis lock: concurrent reports for the same team queue behind the leader (poll every 1s, hard cap 20m wait) and then read the warm cache; the leader heartbeats every 60s to extend its 15m lease, and a lost lease cancels the in-flight body to prevent duplicate syncs.

**Eligibility filter:** Before invoking the agent, `select_repository_for_report` drops candidates that are archived or missing from the heavy cache (e.g., a row whose sync errored during a cold start). The prompt treats SQL hits as primary evidence, so a missing row would read as a false negative. If filtering leaves zero or one candidates, the activity short-circuits without running the agent.

**Truncation caveat:** GitHub's recursive tree endpoint truncates at ~50k entries / 7MB. The `tree_truncated` flag marks affected rows; `tree_paths` is incomplete on those rows and will silently miss files in HogQL grep. Consumers must filter on `tree_truncated=False` and explicitly degrade for truncated repos. Affects <2% of repos; paginated subtree fetch is future work.

#### Re-promotion

Reports are re-promoted when new evidence arrives. A `READY` / `RESOLVED` report re-promotes on every new matching signal (so research reruns with the latest evidence), and a report reset to `potential` re-promotes once it clears the `signals_at_run` snooze gate again.

**Re-research cap.** The research activity reads every non-deleted signal, so re-research cost scales with report size. Once an already-researched report exceeds `RERESEARCH_MAX_SIGNALS` (`SIGNAL_RERESEARCH_MAX_SIGNALS`, default 10), `READY` / `RESOLVED` re-promotion is suppressed: new signals are still assigned, weighted, and emitted, but no new summary run spawns. The cap is enforced in two places: the grouping promotion gate (`assign_and_emit_signal_activity`), which fires the `signal_report_reresearch_skipped` event per suppressed signal so the saved volume is trackable, and the summary self-loop (`mark_report_ready_activity`), which stops an in-flight run from looping into another research pass (no event — this is a rare mid-run edge).

The cap covers **only** the `READY` / `RESOLVED` path (the one that re-promotes on every signal). Re-promotions through the `potential` gate stay uncapped — first research, `candidate` self-heal, snooze return, and a not-actionable reset re-accumulating weight — because they are weight / `signals_at_run`-gated rather than per-signal, so strong new evidence can still resurface a large report.

On re-promotion:

- **Repo selection** reuses the previous `repo_selection` artefact when possible
- **Agentic research** reconstructs previous findings / actionability / priority from artefacts and reuses prior work signal-by-signal when still valid
- **Agentic artefacts** are append-only — the previous run's rows are kept; the new run appends only the entries that actually changed (the agent confirms a still-correct finding/judgment instead of regenerating it), and status types resolve latest-wins
- **`task_run` artefacts are never removed** on re-promotion; they are the historical record of research and auto-started coding runs
- **Auto-start is deduplicated per report** by a legacy `SignalReportTask` implementation link (not the freeform `task_run` log), checked inside the report-row `select_for_update`
- **Workflow ID** includes `run_count` on reruns to avoid Temporal ID collisions with earlier executions

### `SignalReportReingestionWorkflow` (`signal-report-reingestion`)

Deletes a report and re-ingests its signals through the current Signals ingestion pipeline. Useful when grouping decisions need to be re-evaluated after prompt or matching changes.

Defined in `backend/temporal/reingestion.py`. Workflow ID: `signal-report-reingestion-{team_id}-{report_id}`.

**Flow:**

1. **Fetch signals** for the report from ClickHouse → `fetch_signals_for_report_activity`. If no signals are found, the workflow deletes the report only.
2. **Soft-delete signals** in ClickHouse → `soft_delete_report_signals_activity`
   2b. **Wait for ClickHouse** → `wait_for_signal_in_clickhouse_activity`, so re-emitted signals do not race stale rows during semantic search
3. **Delete report** in Postgres → `delete_report_activity`
4. **Re-ingest signals** → `reingest_signals_activity`, which converts each `SignalData` back into an `emit_signal()` call

`emit_signal()` now starts the **buffer + emitter + grouping v2** pipeline, so reingestion flows through the same active path as fresh Signals traffic.

### `TeamSignalReingestionWorkflow` (`team-signal-reingestion`)

Soft-deletes every non-deleted signal for a team and queues all of them for re-ingestion through the active pipeline.

Defined in `backend/temporal/reingestion.py`. Workflow ID: `team-signal-reingestion-{team_id}`.

This workflow is intended for full-team regrouping after changes to matching / prompting / grouping behavior.

It also supports a **delete-only** mode via `TeamSignalReingestionWorkflowInputs(delete_only=True)` / `reingest_team_signals --delete`, which soft-deletes all team signals and clears ORM report state without re-emitting anything.

**Flow:**

1. **Capture existing grouping pause state** → `get_grouping_paused_state_activity`
2. **Pause grouping v2** for the team, extending the pause to at least `now + 10 minutes` → `pause_grouping_until_activity`
3. **Process one batch** of non-deleted signals → `process_team_signals_batch_activity`
   - Fetches the current first `50` non-deleted signals from ClickHouse using `ORDER BY timestamp DESC, document_id DESC`
   - Soft-deletes each signal by emitting a replacement row with the original `document_id`, timestamp, and metadata plus `deleted=true`
   - In normal mode, calls `emit_signal()` for each signal while grouping is paused, so the new signals are buffered but not grouped yet
   - In delete-only mode, skips the `emit_signal()` step entirely
   - Waits for the deleted rows from that batch to land in ClickHouse before returning
4. **Refresh the pause window if needed** so grouping stays paused across long runs while keeping workflow history small
5. **Repeat** until a batch processes `0` remaining non-deleted signals
6. **Delete all team reports + artefacts in Postgres** → `delete_team_reports_activity`
   - Deletes all `SignalReportArtefact` rows for the team
   - Deletes all `SignalReport` rows for the team
   - Runs after all signal batches have been processed, but while grouping is still paused
   - In normal mode, this gives the re-emitted signals a clean ORM state to regroup into once processing resumes
   - In delete-only mode, it leaves both ClickHouse and ORM report state cleared
7. **Restore the prior grouping pause state** → `restore_grouping_pause_activity`

Important detail: the workflow intentionally does **not** paginate across iterations with offsets. Each batch mutates the underlying non-deleted result set by emitting delete rows, so once those rows land in ClickHouse the result set shrinks. Re-fetching the current first batch each time avoids skipping signals.

This workflow is currently started via the Django management command `reingest_team_signals`, not via a REST endpoint. Pass `--delete` to run the delete-only variant.

### `SignalReportDeletionWorkflow` (`signal-report-deletion`)

Soft-deletes a report and all its signals. Triggered by `DELETE /signal_reports/{id}/`.

Defined in `backend/temporal/deletion.py`. Workflow ID: `signal-report-deletion-{team_id}-{report_id}`.

**Flow:**

1. **Fetch signals** for the report from ClickHouse. If none are found, skip to report deletion.
2. **Soft-delete signals** in ClickHouse
   2b. **Wait for ClickHouse** until the deleted rows land
3. **Delete report** in Postgres

This shares the same activities as reingestion; the only difference is that it stops after deletion.

### `SignalsScoutCoordinatorWorkflow` (`run-signals-scout-coordinator`)

Polling coordinator for the headless **Signals agent**. Driven by a Temporal Schedule
defined in `backend/temporal/agentic/schedule.py` with `every=COORDINATOR_INTERVAL_MINUTES`
(30min) and `ScheduleOverlapPolicy.SKIP` to drop ticks rather than queue them. The tick
is just polling granularity — each scout's own `run_interval_minutes` schedule decides
when it actually runs.

Defined in `backend/temporal/agentic/scout_coordinator.py`.

**Flow:**

1. Activity `fetch_enabled_signals_scout_runs_activity` bounds candidates to the teams enrolled via the `signals-scout` feature flag's JSON payload allowlist — `guaranteed_team_ids` minus `skip_team_ids`, with a hardcoded fail-safe default (`_participating_teams` → `_enrolled_team_ids`, modeled on `posthog/temporal/ai_observability/team_discovery.py`). Enrollment is flag-driven: editing the payload in the flag UI enrolls or drains a team next tick with no manual seed. For each enrolled team it calls `sync_canonical_skills(team, prune=True)` to mirror the on-disk `signals-scout-*` skills onto the team's `LLMSkill` rows, then auto-registers a `SignalScoutConfig` for any scout skill missing one (`scout_harness/config_registry.register_missing_configs`; the `signals-scout-config-create` endpoint is the explicit upsert counterpart, so a freshly authored scout is configurable without waiting for a tick). Failures here are logged and the tick continues — a stale skill is preferable to a dead tick.
2. For each enabled config, the coordinator computes how overdue the scout is: due when `last_run_at is None`, or `now - last_run_at >= run_interval_minutes`. There is no sampling — every due scout is planned.
3. Due runs are sorted most-overdue-first and truncated at `MAX_RUNS_PER_TICK` (50 per tick; the cost bound — overflow catches up next tick). `last_run_at` is advanced via `.update()` for everything dispatched (bypasses `save()`, so the per-tick write never hits the activity log). Planned runs are re-sorted by `(team_id, skill_name)` for stable child IDs.
4. Each `PlannedRun` becomes a child `RunSignalsScoutWorkflow` started with `ParentClosePolicy.ABANDON` and a deterministic workflow ID per `(team_id, skill_name, tick_id)` so retried coordinators can't double-launch within a tick.

The coordinator's lifetime is seconds regardless of fan-out width; throttling happens at the Temporal task queue + worker concurrency layer. Pausing a scout is `enabled=False` on its config; slowing it is a larger `run_interval_minutes` — both tunable via the `signals-scout-config-update` MCP tool.

**Per-scout holdback (`withheld_skills`).** The same flag payload carries a hard denylist for keeping an unreleased scout off the fleet while dogfooding it on a single project. A `withheld_skills` list (a `default_team_config` fleet-wide default, overridable per team via `team_configs[<id>].withheld_skills` with replace-not-merge semantics — set `[]` to release the full fleet to one team) names scouts that, for a held-back team, are never seeded into its `LLMSkill` rows (`sync_canonical_skills` skips them), never get a `SignalScoutConfig` (`register_missing_configs` drops them from its return), and are never dispatched. Resolved by `_resolve_withheld_skills`, most-specific-layer-first like the run caps. Unlike the soft `enabled_skills` seed allowlist (a default a user can still toggle on), this is a hard gate at the seed + dispatch layer — e.g. `default_team_config.withheld_skills = ["signals-scout-error-tracking"]` with `team_configs["2"].withheld_skills = []` dogfoods error tracking on project 2 only.

### `RunSignalsScoutWorkflow`

Child workflow per planned run. Defined in `backend/temporal/agentic/scout_scheduler.py`.

Thin wrapper around `run_signals_scout_activity`, which delegates to
`scout_harness.runner.arun_signals_scout`. The activity inserts the `SignalScoutRun`
bridge row at the start of the run; status, timing, and chat log live on the linked
`tasks.TaskRun` via `MultiTurnSession`, not on the bridge row. The workflow's only
job is to spawn the activity with `start_to_close_timeout=WORKFLOW_HARD_CEILING_S`,
a 2-minute heartbeat, and `RetryPolicy(maximum_attempts=1)` — the spec calls for "fail
safe and silent": a bad run does not retry blindly; the next scheduled tick will try
again. Single-flight is a best-effort app-layer guard: `_has_running_run` skips
dispatch when a prior run for the same `(team, skill_name)` has
`task_run.status = IN_PROGRESS`. An earlier partial unique constraint on
`(team, skill_name) WHERE status='running'` was dropped together with the bridge
model's own status column; active recovery of stranded `IN_PROGRESS` task runs
(`_self_heal_stale_runs` is a no-op today) is a tracked follow-up.

Findings emitted during the run go through the harness's `emit_signal_*` tools,
which call `emit_signal()` with `source_product="signals_scout"` and
`source_type="cross_source_issue"` — from there the signal flows through the same
emitter → buffer → grouping v2 path as any other source.

See `backend/scout_harness/AGENTS.md` for the harness internals (runner, prompt
assembly, scratchpad + profile + run-history reads, lazy seed) and
`skills/AGENTS.md` for the scout fleet convention.

---

## Django Models (Postgres)

Defined in `backend/models.py`.

### `SignalReport`

The core model. Status machine:

```text
potential → candidate → in_progress → ready
                                    → pending_input
                                    → failed
                                    → potential (reset by actionability judge)

# Re-promotion: READY reports are re-promoted to candidate on each new matching signal,
# triggering a new summary run that reuses the previous repo selection and findings for
# already-seen signals. Suppressed once signal_count > RERESEARCH_MAX_SIGNALS (see Re-research cap).
ready → candidate

# Transitions enforced by SignalReport.transition_to():
# - deleted is terminal (no transitions out; excluded from API via queryset)
# - suppressed only transitions back to potential
# - any non-deleted status can transition to deleted or suppressed
# - snooze = transition to potential with snooze_for=N (sets signals_at_run = signal_count + N)
suppressed → potential
any (except deleted) → deleted
any (except deleted) → suppressed
```

| Field                         | Type                | Description                                                                                                                                                                                                                                                                                                                                                                                                               |
| ----------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`                        | FK → Team           | Owning team                                                                                                                                                                                                                                                                                                                                                                                                               |
| `status`                      | CharField           | One of: `potential`, `candidate`, `in_progress`, `pending_input`, `ready`, `failed`, `deleted`, `suppressed`                                                                                                                                                                                                                                                                                                              |
| `total_weight`                | Float               | Sum of all assigned signal weights (reset to 0 if deemed not actionable)                                                                                                                                                                                                                                                                                                                                                  |
| `signal_count`                | Int                 | Number of signals assigned                                                                                                                                                                                                                                                                                                                                                                                                |
| `title`                       | Text (nullable)     | LLM-generated title (set during matching or summarization)                                                                                                                                                                                                                                                                                                                                                                |
| `summary`                     | Text (nullable)     | LLM-generated summary                                                                                                                                                                                                                                                                                                                                                                                                     |
| `error`                       | Text (nullable)     | Error message if failed, or reason if pending input / reset to potential                                                                                                                                                                                                                                                                                                                                                  |
| `signals_at_run`              | Int                 | **Forward-looking promotion threshold.** A `potential` or `ready` report will not be (re-)promoted to `candidate` until `signal_count >= signals_at_run`. Defaults to 0, so fresh reports always pass immediately. Advanced by 3 each time a summary run starts, preventing the report from immediately re-promoting. Snoozing sets this to `signal_count + N`, pushing the threshold forward by an additional N signals. |
| `run_count`                   | Int                 | How many times the summary workflow has run for this report. Incremented on each `candidate → in_progress` transition. Used in the Temporal workflow ID to give re-promoted reports a unique execution ID.                                                                                                                                                                                                                |
| `promoted_at`                 | DateTime (nullable) | When report was promoted to `candidate` (cleared on reset to potential)                                                                                                                                                                                                                                                                                                                                                   |
| `last_run_at`                 | DateTime (nullable) | When summary workflow last ran                                                                                                                                                                                                                                                                                                                                                                                            |
| `conversation`                | **DEPRECATED**      | Was: FK → Conversation. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                                                    |
| `relevant_user_count`         | **DEPRECATED**      | Was: Int for relevant user count. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                                          |
| `cluster_centroid`            | **DEPRECATED**      | Was: ArrayField(Float) for video segment clustering. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                       |
| `cluster_centroid_updated_at` | **DEPRECATED**      | Was: DateTime for centroid freshness. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                                      |

**Indexes:** `(team, status, promoted_at)`, `(team, created_at)`

### `SignalReportArtefact`

An **append-only, attributed, schema-validated log of the work done on a report**. A report reads as a living document: the evidence the research agent gathered, the commits it pushed, the task runs that executed, and free-form notes, accumulating over time. Producers never mutate in place — re-assessing appends a new row.

| Field        | Type                             | Description                                          |
| ------------ | -------------------------------- | ---------------------------------------------------- |
| `team`       | FK → Team                        | Owning team                                          |
| `report`     | FK → SignalReport                | Parent report (`related_name="artefacts"`)           |
| `type`       | CharField                        | Artefact type (see `ArtefactType` enum)              |
| `content`    | TextField                        | JSON content stored as text                          |
| `created_at` | DateTime                         | Auto-set; rows are ordered newest-first              |
| `updated_at` | DateTime (nullable, `auto_now`)  | Log entries are editable in place                    |
| `created_by` | FK → User (`SET_NULL`, nullable) | Attribution — the user who produced the row, if any  |
| `task`       | FK → Task (`SET_NULL`, nullable) | Attribution — the task that produced the row, if any |

`created_by` / `task` are nullable: legacy rows and explicit system writes carry NULLs.

**Status vs log.** Everything is append-only; the `STATUS_ARTEFACT_TYPES` / `LOG_ARTEFACT_TYPES` sets classify what an entry _means_:

- **status** — the report's current state (`safety_judgment`, `actionability_judgment`, `priority_judgment`, `repo_selection`, `suggested_reviewers`). Each (re)assessment appends a row; the current status is the **latest row of that type** (serializers derive priority/actionability/reviewers via `order_by("-created_at")[:1]`).
- **log** — discrete work (`code_reference`, `commit`, `task_run`, `note`); these accumulate and are addressable by UUID (PATCH/DELETE).
- `signal_finding` is in neither set: its identity is `(report, content.signal_id)`, latest per signal wins. `dismissal` entries stack.

**Artefact types** (`SignalReportArtefact.ArtefactType` enum):

| Type                     | Content                                                                                                                                                         |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `video_segment`          | Video segment data from session clustering                                                                                                                      |
| `safety_judgment`        | `{"choice": bool, "explanation": "..."}` — true = safe                                                                                                          |
| `actionability_judgment` | `{"actionability": "immediately_actionable" \| "requires_human_input" \| "not_actionable", "explanation": "...", "already_addressed": bool}`                    |
| `priority_judgment`      | `{"priority": "P0"\|"P1"\|"P2"\|"P3"\|"P4", "explanation": "..."}`                                                                                              |
| `signal_finding`         | `{"signal_id": "...", "relevant_code_paths": [...], "relevant_commit_hashes": {"abc1234": "reason"}, "data_queried": "...", "verified": bool}`                  |
| `repo_selection`         | `{"repository": "owner/repo" \| null, "reason": "...", "task_id"?: "..."}`                                                                                      |
| `suggested_reviewers`    | `[{"github_login": "...", "github_name": "...", "relevant_commits": [...]}]` — enriched with current PostHog user data at serializer read time                  |
| `dismissal`              | `{"reason"?, "note"?, "user_id"?, "user_uuid"?, "slack_user_id"?}` — stacking dismissal entries                                                                 |
| `code_reference`         | `{"file_path": "...", "start_line": int, "end_line": int, "contents": "...", "relevance_note": "..."}` — a span of source lines (single line = equal start/end) |
| `commit`                 | `{"repository": "owner/repo", "branch": "...", "commit_sha": "...", "message": "...", "note"?: "..."}` — one pushed commit                                      |
| `task_run`               | `{"task_id": "...", "run_id"?: "...", "product": "...", "type": "..."}` — a task run associated with the report (see below)                                     |
| `note`                   | `{"note": "...", "author"?: "..."}` — free-form note (markdown allowed)                                                                                         |

**Content schemas.** `artefact_schemas.py` is the canonical, pydantic-only home of every content shape, collected in `ARTEFACT_CONTENT_SCHEMAS` (one model per type; a test asserts exact coverage). Raw payloads become typed models once, at the boundaries (`parse_artefact_content`); the model helpers derive a row's type from the content model's class (`artefact_type_for`), so a type can never mismatch its content. `repo_selection` reuses the tasks product's `RepoSelectionResult` DTO directly (kept in the dependency-light leaf module `repo_selection/types.py` so importing the schema registry doesn't pull in the sandbox runtime). Reads of legacy rows stay tolerant — parse failures are skipped or degraded, never raised.

**Attribution.** Every write helper (`append_status` / `add_log` / `append_finding` / `append_dismissal`) requires an `ArtefactAttribution` — exactly one of `from_user(user_id)` / `from_task(task_id)` / `system()` — so no write site can silently skip it. Agent writes are attributed deterministically: sandbox provisioning bakes the agent's task id into an `X-PostHog-Task-Id` header on its MCP config, forwarded by the MCP server on every API call; the LLM never handles its own task id. The header is attribution metadata, not an authorization boundary (the token is team-scoped and the named task must belong to the same team).

**Write surface.** `SignalReportArtefactViewSet` exposes POST / PATCH / DELETE for any type (a status write appends a new latest-wins row), the bespoke `suggested_reviewers` PUT, and a `diff` action that renders a `commit` artefact's branch against the repository default branch via `GitHubIntegration.get_diff` (GitHub compare API, validated repo/ref/sha). All gated by `scope_object = "task"` (`task:write`). Custom agents queue artefacts during a run via `CustomSignalAgent.register_artefact`, persisted in the report's transaction and attributed to the agent's task — except `commit` (written automatically by the signed-commit harness) and `task_run` (written by report persistence), which never need registering there.

**Task↔report association.** A `task_run` artefact _is_ the association (no link table): its `task` FK is the task it records. Associating is just POSTing a `task_run` (its `content.task_id` defaults from the header — "associate me"); the reports list accepts `?task_id=`. Auto-start idempotency does **not** key on this freeform, API-mutable log — it uses a legacy `SignalReportTask` implementation row, which auto-start dual-writes alongside the `task_run` artefact (see Autonomy & Auto-Start).

Notes:

- The serializer still supports legacy `actionability_judgment` payloads that used `choice` instead of `actionability`.

**Indexes:** `(report)` (`signals_sig_report__idx`) plus a latest-wins `(report, type, -created_at)` index backing status derivation.

### `SignalTeamConfig`

Per-team singleton config for Signals settings, including the default autonomy priority threshold.

| Field                        | Type            | Description                                                                  |
| ---------------------------- | --------------- | ---------------------------------------------------------------------------- |
| `id`                         | UUID (PK)       | Primary key (UUIDModel)                                                      |
| `team`                       | OneToOne → Team | Owning team (`related_name="signal_team_config"`)                            |
| `default_autostart_priority` | CharField       | Default severity threshold for auto-start (`P0`–`P4`, where `P0` is highest) |
| `created_at`                 | DateTime        | Auto-set on creation                                                         |
| `updated_at`                 | DateTime        | Auto-set on save                                                             |

Notes:

- Auto-created as a team extension via `register_team_extension_signal`
- `default_autostart_priority` defaults to `P4` (every report priority auto-starts). The threshold is no longer user-configurable in the inbox UI; everyone runs on this default.
- `SignalUserAutonomyConfig.autostart_priority` can still hold a per-user override at the data layer (`null` = use the team default), but there is no UI to set it.

### `SignalUserAutonomyConfig`

Per-user opt-in config for Signals autonomy. Existence of a row means the user is opted in.

| Field                | Type                 | Description                                                                              |
| -------------------- | -------------------- | ---------------------------------------------------------------------------------------- |
| `id`                 | UUID (PK)            | Primary key (UUIDModel)                                                                  |
| `user`               | OneToOne → User      | The opted-in user (`related_name="signal_autonomy_config"`)                              |
| `autostart_priority` | CharField (nullable) | Per-user priority override (`P0`–`P4`); `null` = use team's `default_autostart_priority` |
| `created_at`         | DateTime             | Auto-set on creation                                                                     |
| `updated_at`         | DateTime             | Auto-set on save                                                                         |

Notes:

- One row per user (enforced by `OneToOneField`)
- User is not scoped to a team — the autostart logic resolves team membership at runtime
- Managed via `PUT /api/users/@me/signal_autonomy/` (opt in / update) and `DELETE` (opt out)

### `SignalReportTask` (legacy — implementation gate only)

The legacy report↔task link table. General task↔report association has moved to `task_run` artefacts (a `task_run` artefact's `task` FK is the association; purpose comes from its `(product, type)`). This table survives for **one** job: it's the auto-start idempotency gate. `record_implementation_task` dual-writes a `relationship="implementation"` row here **and** the `task_run` artefact; auto-start checks this table (not the freeform, API-mutable artefact log) when deciding whether an implementation has already started. Once `backfill_task_run_artefacts` has converted every legacy row into a `task_run` artefact, the gate can move to the artefact log and this table can be dropped.

### `SignalSourceConfig`

Per-team configuration for which signal sources are enabled.

| Field            | Type      | Description                                                                                                                                                                            |
| ---------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`           | FK → Team | Owning team (`related_name="signal_source_configs"`)                                                                                                                                   |
| `source_product` | CharField | One of: `session_replay`, `llm_analytics`, `github`, `linear`, `zendesk`, `conversations`, `error_tracking`, `signals_scout` (`SourceProduct` enum)                                    |
| `source_type`    | CharField | One of: `session_analysis_cluster`, `evaluation`, `evaluation_report`, `issue`, `ticket`, `issue_created`, `issue_reopened`, `issue_spiking`, `cross_source_issue` (`SourceType` enum) |
| `enabled`        | Boolean   | Whether this source is active (default `True`)                                                                                                                                         |
| `config`         | JSONField | Source-specific configuration                                                                                                                                                          |
| `created_by`     | FK → User | User who created the config (nullable)                                                                                                                                                 |

**Behavioral notes:**

- `llm_analytics` signals go through the standard enabled-row check like every other source. Per-result `evaluation` signals are additionally filtered by the per-evaluation `evaluation_ids` allowlist in the row's `config`, enforced upstream in the eval workflows; `evaluation_report` signals are gated by their own `(llm_analytics, evaluation_report)` row (the inbox "AI observability" toggle).
- For session replay configs, serializer validation enforces that `config.recording_filters` is a JSON object when present.
- The serializer exposes a computed `status` field:
  - `session_analysis_cluster` derives status from the Temporal clustering workflow
  - data-import-backed sources (`github`, `linear`, `zendesk`) derive status from `ExternalDataSchema`
- The `signals_scout` source variant pairs with `source_type=cross_source_issue` and is the emission channel used by the headless Signals agent's `emit_signal_*` tools. It is the only `(source_product, source_type)` pair the agent emits today.

**Constraints:** Unique on `(team, source_product, source_type)`

### `SignalScoutConfig`

Per-scout binding for the headless **Signals agent**: one row per `(team, skill_name)`. The coordinator auto-creates a row when it discovers a `signals-scout-*` skill on a participating team. Changes are activity-logged (they drive spend); team-level participation is gated by the `signals-scout` flag at the coordinator, not here. See `backend/scout_harness/AGENTS.md` for the harness internals.

| Field                  | Type                 | Description                                                                                                                                                                                                                                     |
| ---------------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`                 | FK → Team            | Owning team (`related_name="signal_scout_configs"`). `unique_together(team, skill_name)`.                                                                                                                                                       |
| `skill_name`           | CharField            | The `signals-scout-*` skill this row controls. Auto-registered by the coordinator when it finds the skill on a participating team.                                                                                                              |
| `enabled`              | Boolean              | Per-scout switch; defaults `True`. `False` pauses just this scout.                                                                                                                                                                              |
| `emit`                 | Boolean              | Dry-run vs emit. Defaults `True`: a freshly authored scout is live from its first tick. Flip to `False` for dry-run — the scout runs and logs but `emit_finding` writes nothing — to validate it on a team before its findings reach the inbox. |
| `run_interval_minutes` | PositiveSmallInt     | Minutes between runs. The coordinator dispatches when `last_run_at is None or now - last_run_at >= run_interval_minutes`. Default `1440` (daily). Validated `30 <= N <= 43200`.                                                                 |
| `last_run_at`          | DateTime (nullable)  | Stamped after each dispatch; drives the due-check. Excluded from activity logging (written every run).                                                                                                                                          |
| `created_by`           | FK → User (nullable) | Audit pointer                                                                                                                                                                                                                                   |
| `enabled_by`           | FK → User (nullable) | Who last flipped `enabled` — tracked because enablement drives spend.                                                                                                                                                                           |

### `SignalScoutRun`

Thin bridge from a Tasks `TaskRun` to the scout skill that ran inside it: one scout-domain row per scheduled agent run that links its `TaskRun` to the skill it executed. Status, timing, error context, and the full chat log live on the `TaskRun`; emitted findings are `Signal` / `SignalReport` rows written by `emit_signal()`. This row carries only the scout-specific fields that need to be queryable as real columns.

| Field           | Type                              | Description                                                                                                                                                        |
| --------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `team`          | FK → Team                         | Owning team (`related_name="signal_scout_runs"`). Denormalised tenant boundary; canonical value is `task_run.task.team`.                                           |
| `task_run`      | OneToOne → tasks.TaskRun          | The `TaskRun` the scout span ran inside (`related_name="signal_scout_run"`, CASCADE — bridge row goes when the `TaskRun` is purged).                               |
| `scout_config`  | FK → SignalScoutConfig (SET_NULL) | Audit pointer; `SET_NULL` so deleting and recreating a config doesn't destroy run history.                                                                         |
| `skill_name`    | CharField(200)                    | The `signals-scout-*` skill the run executed.                                                                                                                      |
| `skill_version` | Int                               | The `LLMSkill.version` snapshot at run start.                                                                                                                      |
| `summary`       | TextField                         | One-paragraph close-out the agent writes at end-of-run. Searchable via ILIKE on the list endpoint so future runs can dedupe even when no `Signal` row was emitted. |
| `created_at`    | DateTime                          | Auto-set on creation.                                                                                                                                              |

**Status, timing, and chat log live on the linked `TaskRun`.** The bridge row carries no `status` / `started_at` / `completed_at` / `findings` / `run_metrics` / `metadata` of its own — those moved to `tasks.TaskRun` so the LLM-analytics token / cost roll-up, the Tasks UI, and the harness all see one canonical record. `MultiTurnSession` owns the `TaskRun` lifecycle; the `on_task_run_created` hook attaches the `TaskRun` to the bridge row before the agent's first turn.

**Tasks UI cross-link.** Run serializers expose a computed `task_url` field on `signals-scout-runs-list` and `signals-scout-runs-retrieve` MCP responses — `/project/{team_id}/tasks/{task_run.task_id}?runId={task_run_id}`. `task_url` is `null` for rows whose `task_run` link is missing (rows aborted before `MultiTurnSession.start()` returned).

**Indexes:** `(team, skill_name)`.

**Constraints:** None at the DB level today. Single-flight is a best-effort app-layer guard (`_has_running_run` against `task_run.status = IN_PROGRESS`). An earlier partial unique constraint on `(team, skill_name) WHERE status='running'` was dropped together with the bridge model's own status column; a `task_run.status`-based constraint plus active recovery of stranded `IN_PROGRESS` task runs (`_self_heal_stale_runs` is a no-op today) is a tracked follow-up.

### `SignalScratchpad`

Narrow per-team scratchpad surface the scout fleet writes during runs and reads back on future runs (known issues, false positives, dedupe fingerprints, learned team quirks). Distinct from `SignalProjectProfile`: profile is _deterministic ground truth_, scratchpad is the _scout's inferred learnings_ (possibly wrong). MCP-readable across agents so PostHog AI and other scouts can see what the fleet has learned about a team.

| Field            | Type                           | Description                                                                               |
| ---------------- | ------------------------------ | ----------------------------------------------------------------------------------------- |
| `team`           | FK → Team                      | Owning team (`related_name="signal_scratchpads"`)                                         |
| `key`            | CharField(300)                 | Semantic key, agent-chosen; unique per team                                               |
| `content`        | TextField                      | Prose for prompt injection — the agent reads this verbatim                                |
| `created_by_run` | FK → SignalScoutRun (SET_NULL) | The run that wrote this entry; `SET_NULL` so deleting a run row doesn't destroy the entry |
| `created_at`     | DateTime                       | Auto-set on creation                                                                      |
| `updated_at`     | DateTime                       | Auto-set on save                                                                          |

**Constraints:** Unique on `(team, key)`.

`authority`, `tags`, and `expires_at` (with their backing GIN / expiry indexes) were dropped in the PR2 review simplification — retrieval is now plain ILIKE over `key` + `content`, and every entry is durable per-team scratchpad.

### `SignalProjectProfile`

Deterministic snapshot of "what's true about this project" — the agent's orientation surface. Time-series so future phases can diff a new profile against the previous row to populate `payload.deltas`. Computed by `scout_harness/profile/builders.py` from authoritative tables; v1 writes 10 inventory sections (events, properties, cohorts, feature flags, experiments, surveys, dashboards, insights, data warehouse sources, integrations).

| Field            | Type          | Description                                                                                                                                               |
| ---------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`           | FK → Team     | Owning team (`related_name="signal_project_profiles"`)                                                                                                    |
| `computed_at`    | DateTime      | Auto-set on creation                                                                                                                                      |
| `expires_at`     | DateTime      | Soft TTL — `get_project_profile` treats rows past expiry as cache misses and recomputes (~36h gives a safety margin against the daily refresh).           |
| `source_version` | CharField(40) | Bumps when the inventory schema changes meaningfully so `get_project_profile` can invalidate stale rows without a manual backfill                         |
| `payload`        | JSONField     | `{inventory: {...}}` in v1; `deltas`, `activity_notes`, `narrative` slots reserved for later phases. Inline jsonb is fine — even a rich profile is small. |

**Indexes:** `(team, -computed_at)` — supports the `ORDER BY computed_at DESC LIMIT 1` lookup used by `get_project_profile`.

### `SignalEmissionRecord`

Tracks which source records have been emitted as signals. Owned by the signals app so source models (e.g. `Ticket`) stay decoupled. One row per source record, upserted on emission.

| Field            | Type           | Description                                  |
| ---------------- | -------------- | -------------------------------------------- |
| `team`           | FK → Team      | Owning team                                  |
| `source_product` | CharField(100) | Mirror of `SignalSourceConfig.SourceProduct` |
| `source_type`    | CharField(100) | Mirror of `SignalSourceConfig.SourceType`    |
| `source_id`      | CharField(200) | Source-side primary key                      |
| `emitted_at`     | DateTime       | When this record was last emitted            |

**Constraints:** Unique on `(team, source_product, source_type, source_id)`
**Indexes:** `(team, source_product, source_type)`

---

## ClickHouse Storage

Signals are stored in the **`posthog_document_embeddings`** table, which is shared across products (error tracking, session replay, AI observability, etc.).

### Table Schema

Defined in `products/error_tracking/backend/embedding.py`:

| Column          | Type                   | Description                                                                                                                      |
| --------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `team_id`       | Int64                  | Team identifier                                                                                                                  |
| `product`       | LowCardinality(String) | Product bucket — signals uses `'signals'`                                                                                        |
| `document_type` | LowCardinality(String) | Document type — signals uses `'signal'`                                                                                          |
| `model_name`    | LowCardinality(String) | Embedding model name (e.g., `text-embedding-3-small-1536`)                                                                       |
| `rendering`     | LowCardinality(String) | How content was rendered — signals uses `'plain'`                                                                                |
| `document_id`   | String                 | Unique signal ID (UUID)                                                                                                          |
| `timestamp`     | DateTime64(3, 'UTC')   | Document creation time                                                                                                           |
| `inserted_at`   | DateTime64(3, 'UTC')   | When the embedding was inserted (used for dedup)                                                                                 |
| `content`       | String                 | The signal description text                                                                                                      |
| `metadata`      | String                 | JSON string containing `report_id`, `source_product`, `source_type`, `source_id`, `weight`, `extra`, `match_metadata`, `deleted` |
| `embedding`     | Array(Float64)         | The embedding vector                                                                                                             |

**Engine:** `ReplacingMergeTree` (sharded), partitioned by `toMonday(timestamp)`, 3-month TTL.

**Ordering:** `(team_id, toDate(timestamp), product, document_type, model_name, rendering, cityHash64(document_id))`

### Data Flow

```text
emit_embedding_request() → Kafka (document_embeddings_input topic)
    → Kafka table → Materialized View → Writable Distributed table → Sharded ReplacingMergeTree
```

### Soft Deletion

Signals are soft-deleted by re-emitting the embedding row with `metadata.deleted = true`, preserving the original `timestamp` so it lands in the same partition and replaces the original via `ReplacingMergeTree`. Most read queries filter with `NOT JSONExtractBool(metadata, 'deleted')`; the exception is `wait_for_signal_in_clickhouse_activity`, which deliberately includes deleted rows (it only cares that the row landed, not whether it's visible).

### HogQL Queries

The canonical ClickHouse / HogQL helpers live in `backend/temporal/signal_queries.py` and use the HogQL alias `document_embeddings`. Most read queries share a dedup subquery that uses `argMax(..., inserted_at)` grouped by `document_id`, which makes reads stable despite `ReplacingMergeTree` merge timing.

All Signals queries filter to `product = 'signals'` and `document_type = 'signal'`. Key queries:

1. **Fetch signal type examples** (`fetch_signal_type_examples_activity`): fetches one example signal per unique `(source_product, source_type)` pair from the last month, selecting the most recent example per type. Used to give the search-query generation LLM context about heterogeneous signal types.
2. **Semantic search** (`run_signal_semantic_search_activity`): uses `cosineDistance(embedding, {embedding})` to find nearest neighbors with a non-empty `report_id`, limited to the last month.
3. **Fetch for report** (`fetch_signals_for_report_activity`): fetches all non-deleted signals for a report, ordered by timestamp ascending.
4. **Wait for ClickHouse** (`wait_for_signal_in_clickhouse_activity`): polls for all emitted `document_id`s within a widened timestamp range (`min(timestamp)-2m` to `max(timestamp)+2m`) and `inserted_at >= now() - 30 minutes`, which avoids matching stale earlier emissions of the same IDs while tolerating precision loss and queueing delay. This query intentionally does **not** filter on `deleted`.
5. **Filter reports by source product** (`fetch_report_ids_for_source_products`): used by the list API’s `source_product` filter. Note that it currently has a hard `LIMIT 300`.

`execute_hogql_query_with_retry()` in `backend/temporal/clickhouse.py` wraps transient ClickHouse failures with heartbeat-safe retry behavior for activities.

### Soft Deletion Caveat

`soft_delete_report_signals()` lives in `backend/temporal/signal_queries.py` (with a compatibility re-export in `backend/utils.py`), not in `backend/api.py`.

It soft-deletes report signals by re-emitting the same `document_id` and original `timestamp` with `metadata.deleted = true`, across all embedding models, so the new row replaces the original in the same `ReplacingMergeTree` partition.

One implementation caveat: the helper currently fetches report signals with `limit=5000`. So while the intent is “delete all signals for the report”, very large reports can currently leave undeleted rows beyond that cap.

---

## API Layer

### Entry Point: `emit_signal()` (`backend/api.py`)

The primary programmatic entry point. Called by other PostHog products and Signals-related workflows to emit signals.

Current behavior:

1. Verifies org-level AI data processing approval
2. Checks `SignalSourceConfig.is_source_enabled()`
3. Validates the payload against `posthog.schema.SignalInput`
4. Idempotently starts `BufferSignalsWorkflow`
5. Fire-and-forget starts `SignalEmitterWorkflow`

So `emit_signal()` now feeds the **buffer + emitter + grouping v2** path rather than signaling the legacy v1 grouping workflow directly.

**Guards / validation:**

- The team’s organization must have `is_ai_data_processing_approved`
- The source must be enabled by `SignalSourceConfig.is_source_enabled()`
- Description length is capped at `MAX_SIGNAL_DESCRIPTION_TOKENS` (currently 8000 tokens)
- The input must validate against the shared `SignalInput` schema

### Utility: `soft_delete_report_signals()`

The canonical helper lives in `backend/temporal/signal_queries.py` (with a compatibility re-export in `backend/utils.py`), not in `backend/api.py`.

It soft-deletes report signals by re-emitting them with `metadata.deleted = true` while preserving original timestamps so rows replace originals via `ReplacingMergeTree`. It intentionally includes already-deleted rows for idempotency, but currently fetches at most 5000 signals per report.

### REST Endpoints

All signals endpoints live under the `projects/:team_id/signals/` path, registered on the `projects_router` in `posthog/api/__init__.py`.

#### `SignalViewSet` (DEBUG only)

| Method | Path            | Description                                 |
| ------ | --------------- | ------------------------------------------- |
| POST   | `signals/emit/` | Manually emit a signal (debug/testing only) |

#### `InternalSignalViewSet`

Internal-only service-to-service endpoint authenticated via `X-Internal-Api-Secret`.

| Method | Path                                            | Description                       |
| ------ | ----------------------------------------------- | --------------------------------- |
| POST   | `/api/projects/{team_id}/internal/signals/emit` | Emit a signal for a specific team |

#### `SignalSourceConfigViewSet`

Full CRUD for per-team signal source configurations. Uses `IsAuthenticated` + `APIScopePermission` with scope object **`task`**.

| Method | Path                           | Description               |
| ------ | ------------------------------ | ------------------------- |
| GET    | `signals/source_configs/`      | List configs for the team |
| POST   | `signals/source_configs/`      | Create a new config       |
| GET    | `signals/source_configs/{id}/` | Retrieve a config         |
| PATCH  | `signals/source_configs/{id}/` | Update a config           |
| DELETE | `signals/source_configs/{id}/` | Delete a config           |

Important side effects:

- Creating or enabling a `session_analysis_cluster` config starts the clustering workflow
- Creating an enabled `error_tracking / issue_created` config starts the error-tracking backfill workflow
- Enabling data-import-backed sources can trigger external data syncs
- Disabling a clustering config cancels the clustering workflow

#### `SignalTeamConfigViewSet`

Team-scoped singleton config for the default autonomy priority threshold. Uses `IsAuthenticated` + `APIScopePermission` (scope: `task`). Returns 404 if no config exists for the team.

| Method | Path              | Description                            |
| ------ | ----------------- | -------------------------------------- |
| GET    | `signals/config/` | Retrieve the team's `SignalTeamConfig` |
| POST   | `signals/config/` | Update `default_autostart_priority`    |

#### User Autonomy Config (action on `UserViewSet`)

Per-user autonomy opt-in, registered as an action on the root `UserViewSet` at `api/users/:uuid/signal_autonomy/`.

| Method | Path                         | Description                                          |
| ------ | ---------------------------- | ---------------------------------------------------- |
| GET    | `users/@me/signal_autonomy/` | Get own autonomy config (404 if not opted in)        |
| PUT    | `users/@me/signal_autonomy/` | Opt in / update `autostart_priority`                 |
| DELETE | `users/@me/signal_autonomy/` | Opt out (deletes the `SignalUserAutonomyConfig` row) |

Notes:

- Non-staff users can only access `@me`; staff can access any user by UUID
- `PUT` body: `{"autostart_priority": "P2"}` or `{"autostart_priority": null}` (use team default)
- Inherits auth/permissions from `UserViewSet` (scope: `user`)

#### `SignalReportViewSet`

Read + delete + state transitions. Uses `IsAuthenticated` + `APIScopePermission` (scope: `task`). Composed from `RetrieveModelMixin`, `ListModelMixin`, `DestroyModelMixin`, and `GenericViewSet`. Deleted reports are excluded from all endpoints via `safely_get_queryset`.

| Method | Path                                   | Description                                                                                                                                                                                                                                                                                                                         |
| ------ | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `signals/reports/`                     | List reports. Excludes `deleted` always and excludes `suppressed` by default. Supports `?status=`, `?search=`, `?source_product=`, `?suggested_reviewers=`, `?task_id=` (resolved through `task_run` artefacts), and `?ordering=`.                                                                                                  |
| GET    | `signals/reports/{id}/`                | Retrieve a single report                                                                                                                                                                                                                                                                                                            |
| DELETE | `signals/reports/{id}/`                | Soft-delete a report and its signals. Starts `SignalReportDeletionWorkflow`. On success returns `202`. If the workflow is already running, returns `200 {"status": "already_running"}`. The API immediately transitions the Postgres report to `deleted` to hide it from list results while ClickHouse cleanup runs asynchronously. |
| POST   | `signals/reports/{id}/state/`          | Transition report state. Body: `{ "state": "suppressed" \| "potential", ...transition_to kwargs }`. Only `suppressed` and `potential` are exposed via API. Returns `409` on invalid transitions and `400` on invalid arguments.                                                                                                     |
| POST   | `signals/reports/{id}/reingest/`       | Delete a report and re-ingest its signals. Starts `SignalReportReingestionWorkflow`. On success returns `202`. If already running, returns `200 {"status": "already_running"}`. Same team access as other report endpoints; personal API keys need `task:write`.                                                                    |
| GET    | `signals/reports/{id}/artefacts/`      | List **all** artefacts for a report, ordered by `-created_at`                                                                                                                                                                                                                                                                       |
| GET    | `signals/reports/{id}/signals/`        | Fetch all signals for a report from ClickHouse, including full metadata                                                                                                                                                                                                                                                             |
| GET    | `signals/reports/available_reviewers/` | List available suggested reviewers for the team                                                                                                                                                                                                                                                                                     |

**Ordering:** Configurable via `?ordering=` with comma-separated fields. Supported fields: `status`, `is_suggested_reviewer`, `signal_count`, `total_weight`, `priority`, `created_at`, `updated_at`, `id`.

The `status` clause sorts by annotated `pipeline_status_rank` (not lexicographic `status` text). Ascending rank lists earlier pipeline stages first. Ranks:

- `0` — `ready` and actionable (includes reports with no actionability judgment yet)
- `1` — `ready` and latest actionability judgment is `not_actionable`
- `2` — `pending_input`
- `3` — `in_progress`
- `4` — `candidate`
- `5` — `potential`
- `6` — `failed`
- `7` — `suppressed`
- `8` — `deleted` (deleted rows are not returned by the API; rank exists for queryset consistency)

So with `ordering=status`, **`failed` sorts after actionable `ready`**. With `ordering=-status`, **`failed` sorts before actionable `ready`**.

Default ordering is **`-is_suggested_reviewer,status,-updated_at,id`**.

#### `SignalReportArtefactViewSet`

The artefact log read/write surface, nested under the reports router (`environment_signal_report_artefacts`). Team-scoped via `safely_get_queryset` (report id from the URL + `self.team`); gated by `scope_object = "task"`.

| Method | Path                                         | Description                                                                                            |
| ------ | -------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| GET    | `signals/reports/{id}/artefacts/`            | List all artefacts for a report, ordered by `-created_at`                                              |
| GET    | `signals/reports/{id}/artefacts/{aid}/`      | Retrieve one artefact                                                                                  |
| POST   | `signals/reports/{id}/artefacts/`            | Append an artefact of any type (status types append a new latest-wins row); per-type schema validation |
| PATCH  | `signals/reports/{id}/artefacts/{aid}/`      | Edit a log/status row's content in place                                                               |
| DELETE | `signals/reports/{id}/artefacts/{aid}/`      | Delete an artefact row                                                                                 |
| GET    | `signals/reports/{id}/artefacts/{aid}/diff/` | Render a `commit` artefact's branch against the repo default branch via `GitHubIntegration.get_diff`   |

POSTing a `task_run` artefact is the "associate me" operation: `content.task_id` defaults from the `X-PostHog-Task-Id` header, `product`/`type` default to `tasks`/`agent_run`, the named task must belong to the team, and re-association is idempotent. The bespoke `suggested_reviewers` PUT (reviewer enrichment) also lives here. Writes are attributed to the header's task when present, else the requesting user.

#### `SignalProcessingViewSet`

View + control API for the v2 grouping pipeline. Uses scope object `INTERNAL`.

| Method | Path                        | Description                            |
| ------ | --------------------------- | -------------------------------------- |
| GET    | `signals/processing/`       | Return current pause state             |
| PUT    | `signals/processing/pause/` | Pause grouping until a given timestamp |
| DELETE | `signals/processing/pause/` | Clear the paused state                 |

#### Signals Agent endpoints (`backend/scout_harness/views.py`)

The harness exposes three viewsets routed under `environment_signals_scout_*` basenames in `posthog/api/__init__.py`. They are surfaced to MCP callers as `signals-scout-*` tools via `products/signals/mcp/tools.yaml`. Reads are scoped to the team; writes (scratchpad remember / forget, signal emit) require the matching MCP scope.

- **`SignalScoutRunViewSet`** — list / retrieve scout run rows; nested action `runs/{id}/emit-signal/` for the harness to push findings during a run.
- **`SignalScratchpadViewSet`** — search / remember / forget `SignalScratchpad` rows for the team. The `signals-scout-scratchpad-search` tool is the agent's primary "what do I already know" read at prompt-assembly time.
- **`SignalProjectProfileViewSet`** — `GET .../current/` returns the freshest non-expired `SignalProjectProfile` row for the team (recomputes if the cache is stale).

Generated MCP tool names:

| Tool                                | Purpose                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------------ |
| `signals-scout-runs-list`           | List scout runs (filterable by skill / status / time)                          |
| `signals-scout-runs-retrieve`       | Fetch a single run row including the full findings payload                     |
| `signals-scout-emit-signal`         | Push a finding from inside a run (used by the harness's `emit_signal_*` tools) |
| `signals-scout-scratchpad-search`   | Search durable scratchpad entries for the team                                 |
| `signals-scout-scratchpad-remember` | Create or update a scratchpad entry                                            |
| `signals-scout-scratchpad-forget`   | Remove a scratchpad entry                                                      |
| `signals-scout-project-profile-get` | Read the current `SignalProjectProfile` snapshot                               |

### Serializers (`backend/serializers.py`)

- **`SignalSourceConfigSerializer`**
  - Exposes `id`, `source_product`, `source_type`, `enabled`, `config`, `created_at`, `updated_at`, `status`
  - Validates that `recording_filters` in config is a JSON object for `session_replay`
  - Computes `status` from the clustering workflow or external data import state depending on the source
- **`SignalTeamConfigSerializer`**
  - ModelSerializer for `SignalTeamConfig`
  - Exposes `id`, `default_autostart_priority`, `created_at`, `updated_at`
- **`SignalUserAutonomyConfigSerializer`**
  - ModelSerializer for `SignalUserAutonomyConfig`
  - Exposes `id`, `user` (nested with `id`, `uuid`, `first_name`, `last_name`, `email`), `autostart_priority`, `created_at`, `updated_at`
- **`SignalUserAutonomyConfigCreateSerializer`**
  - Plain Serializer for PUT requests on the user autonomy action
  - Accepts `autostart_priority` (optional, nullable)
- **`SignalReportSerializer`**
  - Exposes `id`, `title`, `summary`, `status`, `total_weight`, `signal_count`, `signals_at_run`, `created_at`, `updated_at`, `artefact_count`, `priority`, `actionability`, `already_addressed`, `is_suggested_reviewer`
  - `priority` comes from the latest `PRIORITY_JUDGMENT` artefact
  - `actionability` comes from the latest `ACTIONABILITY_JUDGMENT` artefact and supports both current (`actionability`) and legacy (`choice`) payloads
  - `already_addressed` also comes from the latest actionability artefact
  - `is_suggested_reviewer`: list/detail annotate from the requesting user’s linked GitHub login against the `suggested_reviewers` artefact. Always **`false`** when there is nothing to review: `failed` reports, or `ready` with latest actionability `not_actionable` (even if the artefact names the user)
- **`SignalReportArtefactSerializer`**
  - Exposes `id`, `type`, `content`, `created_at`
  - Parses JSON text into structured content
  - For `suggested_reviewers`, enriches the stored GitHub-only payload with fresh PostHog org-member data at read time

---

## Analytics Events

All events use `distinct_id = team.uuid` and `groups(organization, team)`. Per-signal events carry `source_product`, `source_type`, `source_id` — pivot on `source_id` to trace one signal.

**Lifecycle (in order):**

- `signal_data_source_entered` / `signal_data_source_summarized` / `signal_data_source_filtered` — data-source pipeline only (`pipeline.py`)
- `signal_emission_started` — `emit_signal()` past validation
- `signal_emitted` — `emit_signal()` after Temporal dispatch succeeds
- `signal_assigned_to_report` — grouping assigned the signal (+ `report_id`, `is_new_report`, `promoted`)
- `signal_report_reresearch_skipped` — signal hit an already-researched report past the re-research cap, so no new run spawned (+ `report_id`, `signal_count`, `status`, `threshold`). Fires per suppressed signal
- `signal_report_started` — report run began (+ `report_id`, `signal_count`, `run_count`, `source_products`)
- `signals_repo_research_started` / `signals_repo_research_completed` — repo selection stage (+ `report_id`, `result`: `reused` | `selected` | `no_repo` | `failed`, optional `failure_reason`: `no_github_integration` | `agentic_activity_error`)
- `signal_report_completed` — terminal per run (+ `result`: `ready` | `failed` | `pending_input` | `not_actionable`, optional `failure_reason`)

**Tracing one signal:** filter on `properties.source_id = <id>` to follow it through the funnel, then pivot to `properties.report_id` from `signal_assigned_to_report` to see the report's lifecycle.

Telemetry is best-effort; failures are logged, not raised.

---

## LLM Integration

Most direct LLM calls use Anthropic via the shared `call_llm()` helper in `backend/temporal/llm.py`, with model selection driven by `SIGNAL_MATCHING_LLM_MODEL` (default: `claude-sonnet-4-5`).

That said, **not all “LLM-ish” behavior in Signals goes through `call_llm()` anymore**:

- Grouping-time query generation / matching / specificity checks use `call_llm()`
- The buffer safety filter uses `call_llm()`
- The report safety judge uses `call_llm()`
- Eval-signal summarization uses `call_llm()`
- **Repository selection** runs via the sandbox agent flow, not `call_llm()`
- **Agentic report research** runs via `MultiTurnSession` in `report_generation/research.py`, not `call_llm()`

### `call_llm()` (`backend/temporal/llm.py`)

A generic helper that abstracts the retry / validate / append-errors pattern used by direct LLM calls. It takes a system prompt, user prompt, validation function, and options like `thinking`, `temperature`, and retries.

Key behaviors:

- **Retry with conversational self-correction:** on validation failure, the full response content is appended as an assistant message, followed by the validation error as a user message
- **JSON enforcement:** for non-thinking calls, the helper pre-fills the assistant response with `{` to discourage markdown fences; for thinking calls it strips common fenced-JSON wrappers
- **Extended thinking:** when `thinking=True` and the selected model supports it, enables Anthropic extended thinking with increased token budgets
- **Debug logging:** in `DEBUG`, logs raw failed responses to help tune prompts / validators

### Grouping-time LLM calls

The architecture doc previously attributed these functions to `backend/temporal/llm.py`, but that file is only the helper. The grouping-specific call sites live in `backend/temporal/grouping.py`.

#### Search-query generation

Generates 1–3 cross-source search queries for a signal from different angles (feature/component, behavior/issue, impact), using recent signal type examples as context. Queries are truncated before embedding.

#### Match-to-report decision

Chooses between:

- matching the signal to an existing report candidate
- creating a new report candidate with title + summary

The validator ensures the returned `signal_id` and `query_index` are valid for the candidate set given to the model.

#### Match-specificity verification

A second grouping-time LLM check used before broadening an existing report too aggressively.
It writes a PR title covering the whole group including the new signal and rejects the match if no single pull request could plausibly cover it.

#### Combined match + specificity (single call)

For teams with the `signals-combined-match-specificity` feature flag enabled, the match-to-report decision and the specificity check are collapsed into one LLM call (`match_and_verify_signal_activity`).
The flag is evaluated with the team id as the distinct id, once per batch, inside `check_combined_match_enabled_activity`.
The result is recorded in workflow history, so flag flips replay deterministically for in-flight runs and take effect on subsequent batches — no worker redeploy or workflow drain needed.
The check fails closed: any flag evaluation error falls back to the two-call path.
The prompt is the matching prompt plus the PR-test rules, with each candidate group's most recent member signals inlined (up to 8 per report, content truncated to 500 chars, fetched in one ClickHouse query via `fetch_signals_for_reports_activity`).
An existing-report match carries a required `pr_title` and is recorded with `specific_enough=true`; a group that fails the PR test simply comes back as a new-report decision, so there are no post-hoc specificity rejections on this path.

### Safety filter (`backend/temporal/safety_filter.py`)

Per-signal safety classifier that runs in the buffer workflow before signals are flushed to object storage.

It classifies raw signal descriptions against a threat taxonomy including prompt injection, hidden instructions, encoded payloads, security weakening, data exfiltration, social engineering, and code injection.

Returns:

- `{"safe": true, "threat_type": "", "explanation": ""}`
- `{"safe": false, "threat_type": "...", "explanation": "..."}`

If the provider returns an empty response, the signal is treated as unsafe with threat type `provider_safety_filter`.

This is the first line of defense; it prevents adversarial signals from consuming embedding / search / matching work.

### Report safety judge (`backend/temporal/report_safety_judge.py`)

Report-level safety review that runs **before** repository selection and agentic research. It evaluates the underlying grouped signals for prompt injection or manipulation attempts that could steer a downstream coding agent toward malicious actions.

Returns `{"choice": bool, "explanation": "..."}` and stores the result as a `safety_judgment` artefact. Extended thinking is enabled.

Importantly, this judge currently assesses the **signals**, not a generated title/summary — those do not exist yet when the judge runs.

### Agentic research outputs (`backend/report_generation/research.py`)

The old standalone summary / actionability judge files referenced in earlier docs no longer exist. Their responsibilities now live inside the multi-turn research flow and its persisted output models.

The research flow produces:

- **`SignalFinding`**
  - `signal_id`
  - `relevant_code_paths`
  - `relevant_commit_hashes`
  - `data_queried`
  - `verified`
- **`ActionabilityAssessment`**
  - `explanation`
  - `actionability`
  - `already_addressed`
- **`PriorityAssessment`**
  - `explanation`
  - `priority`
- **`ReportPresentationOutput`**
  - `title`
  - `summary`

These are assembled into `ReportResearchOutput`, then persisted by `run_agentic_report_activity`.

A `task_run` artefact (`type=research`) is appended immediately after the `MultiTurnSession` starts (before any research turns), associating the sandbox `Task` with the report and attributing it to that task.

---

## Autonomy & Auto-Start

The autonomy system allows Signals to automatically start a Tasks coding run when a report is immediately actionable.

### Configuration

Autonomy is configured at two levels:

1. **Team level** (`SignalTeamConfig`): Sets the `default_autostart_priority` threshold (`P0`–`P4`). Auto-created as a team extension via `register_team_extension_signal`. Managed via `GET/POST /api/projects/:team_id/signals/config/`.

2. **User level** (`SignalUserAutonomyConfig`): Per-user opt-in. A row existing means the user is opted in. Each user can optionally override the team priority threshold with `autostart_priority`. Managed via `GET/PUT/DELETE /api/users/@me/signal_autonomy/`.

The management command `enable_signals_autonomy` can set both in one shot:

```text
python manage.py enable_signals_autonomy <team_id> <priority> <emails>
```

### Auto-Start Flow

Runs inside `maybe_autostart_implementation_task()` in `backend/auto_start.py`, called after artefact persistence in both `run_agentic_report_activity` (the signals pipeline) and `run_custom_signal_agent_activity` (custom agents).

**Guard clause** — all must pass:

- Report actionability is `immediately_actionable`
- Report has a `priority_judgment`
- Report has suggested reviewers
- No legacy `SignalReportTask` implementation row exists for the report (checked inside a `select_for_update` on the report row, so concurrent evaluations can't double-start)

**User selection** via `_resolve_autostart_assignee()` in `backend/auto_start.py`:

1. Map reviewer GitHub logins to PostHog user IDs via social auth (preserving reviewer relevance order)
2. Single query: fetch `User` objects whose ID is in that list **and** who have a `SignalUserAutonomyConfig` row (joined via `select_related`)
3. Walk candidates in reviewer order. For each user:
   a. Verify team membership via `user.teams.filter(id=team_id).exists()`
   b. Resolve their effective priority threshold: personal `autostart_priority` if set, otherwise the team's `default_autostart_priority`
   c. If `report_priority_rank <= threshold_rank` → return that user
4. If no user matches → skip

**Task creation:**

1. `Task.create_and_run(origin_product=SIGNAL_REPORT, ...)`
2. `record_implementation_task` writes the legacy `SignalReportTask` implementation gate row (in the same transaction) and appends an `implementation` `task_run` artefact
3. Errors are caught and logged but do not fail the report workflow

### Priority Rank

`P0` is the highest severity (rank 0), `P4` is the lowest (rank 4). A report auto-starts only if `report_priority_rank <= user_threshold_rank`. So a team with `default_autostart_priority=P4` will auto-start on any priority, while `P0` will only auto-start for the most critical reports.

### Task Tracking

Report ↔ task relationships are recorded as `task_run` artefacts (see `SignalReportArtefact`), one per associated run, with the run's purpose carried in the artefact's `(product, type)`. The built-in pipeline writes `product="signals"` with `type` in `{research, implementation, repo_selection}`; custom agents supply their own `identifier()` pair.

Auto-start dedup is separate from this freeform log: `maybe_autostart_implementation_task()` (`backend/auto_start.py`) gates on a legacy `SignalReportTask` implementation row, checked inside the report-row `select_for_update`, so concurrent evaluations can't double-start. Both the auto-start and the manual tasks-API path go through `record_implementation_task`, which dual-writes that gate row and the `implementation` `task_run` artefact — the transitional arrangement until the backfill lets the gate move to artefacts (see `SignalReportTask`).

### Eval-signal summarization (`backend/temporal/emit_eval_signal.py`)

Separate from report generation, the `emit-eval-signal` workflow uses `call_llm()` with extended thinking to turn an LLMA evaluation result into a signal-sized description plus significance score. Low-significance eval results are dropped before calling `emit_signal()`.

### Resetting self-driving state for local re-testing

The self-driving wizard (`npx @posthog/wizard … self-driving`) enables signal sources, materializes and enables the scout fleet, and creates custom `signals-scout-*` skills for the project. To re-test a run from a clean slate without manually undoing each change, use the dev-only `reset_signals_self_driving` command (the practical inverse of `enable_signals_autonomy`; `DEBUG`-gated like `cleanup_signals`):

```text
python manage.py reset_signals_self_driving --team-id 1 --yes \
    --install-dir /path/to/your/test/project
```

For a fresh team the signals config tables are empty, so the reset **deletes** rather than disables — the next wizard run's `sync` call re-creates the canonical fleet (enabled) exactly as it would for a brand-new team. (Disabling instead would leave the fleet off on the next run, since the wizard's scout step only _disables_ misfits and relies on the fresh default being enabled.)

Cleared for the team:

| What               | Tables / artifacts                                                                                                                                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Signal sources     | `SignalSourceConfig` (all rows)                                                                                                                                                                                                                         |
| Scout fleet config | `SignalScoutConfig` (all rows)                                                                                                                                                                                                                          |
| Custom scouts      | `LLMSkill` rows whose `name` starts `signals-scout-` and are **not** seeded — i.e. not in the set of names carrying `metadata.seeded_by == "signals_scout_harness"` (covers the common case where the key is absent entirely) (cascades `LLMSkillFile`) |
| Scout run-state    | `SignalScratchpad`, `SignalProjectProfile`, `SignalScoutRun`, `SignalEmissionRecord`                                                                                                                                                                    |
| Emitted findings   | `SignalReport` + artefacts + ClickHouse rows + Temporal workflows (delegates to `cleanup_signals`; skip with `--keep-findings`)                                                                                                                         |
| Wizard report      | `<install-dir>/posthog-self-driving-report.md` (only if `--install-dir` is given)                                                                                                                                                                       |
| Wizard log         | `/tmp/posthog-wizard.log` → backed up to `/tmp/posthog-wizard-previous-<timestamp>.log` then removed (override `--wizard-log`, skip `--keep-log`)                                                                                                       |

Preserved: canonical scouts and the `authoring-scouts` companion, identified by `metadata.seeded_by == "signals_scout_harness"`. That tag is the practical marker this DEBUG reset uses; it is not a perfect canonical test on its own — `_scout_origin` also requires the name to ship on disk, since `duplicate_skill` copies the tag verbatim — but the wizard authors custom scouts via `llma-skill-create` with no tag, so tag-only suffices here. The command does **not** touch `SignalTeamConfig` or `SignalUserAutonomyConfig` (autostart / per-user opt-in are set by `enable_signals_autonomy`, not the wizard); `llm_analytics` sources are gated by their `SignalSourceConfig` rows like any other source.

---

## Data Types (`backend/temporal/types.py`)

| Type                                    | Description                                                                                                                          |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `EmitSignalInputs`                      | Workflow input: `team_id`, `source_product`, `source_type`, `source_id`, `description`, `weight`, `extra`                            |
| `BufferSignalsInput`                    | Buffer workflow input: `team_id`, `pending_signals: list[EmitSignalInputs]` (carried over on `continue_as_new`)                      |
| `TeamSignalGroupingV2Input`             | Grouping v2 workflow input: `team_id`, `pending_batch_keys: list[str]` (carried over on `continue_as_new`)                           |
| `TeamSignalGroupingInput`               | Legacy v1 entity workflow input: `team_id`, `pending_signals: list[EmitSignalInputs]` (carried over on `continue_as_new`)            |
| `ReadSignalsFromS3Input`                | Activity input: `object_key`                                                                                                         |
| `ReadSignalsFromS3Output`               | Activity output: `signals: list[EmitSignalInputs]`                                                                                   |
| `SignalCandidate`                       | Search result: `signal_id`, `report_id`, `content`, `source_product`, `source_type`, `distance`                                      |
| `MatchedMetadata`                       | Metadata when matched to existing report: `parent_signal_id`, `match_query`, `reason`                                                |
| `NoMatchMetadata`                       | Metadata when no match found: `reason`, `rejected_signal_ids`                                                                        |
| `MatchMetadata`                         | Union type: `MatchedMetadata \| NoMatchMetadata`                                                                                     |
| `ExistingReportMatch`                   | LLM decided signal matches existing report: `report_id`, `match_metadata: MatchedMetadata`                                           |
| `NewReportMatch`                        | LLM decided signal needs new group: `title`, `summary`, `match_metadata: NoMatchMetadata`                                            |
| `MatchResult`                           | Union: `ExistingReportMatch \| NewReportMatch`                                                                                       |
| `SignalReportSummaryWorkflowInputs`     | Summary workflow input: `team_id`, `report_id`                                                                                       |
| `SignalReportDeletionWorkflowInputs`    | Deletion workflow input: `team_id`, `report_id`                                                                                      |
| `SignalReportReingestionWorkflowInputs` | Reingestion workflow input: `team_id`, `report_id`                                                                                   |
| `SignalTypeExample`                     | One example per `(source_product, source_type)` pair: `source_product`, `source_type`, `content`, `timestamp`, `extra`               |
| `SignalData`                            | Signal fetched from ClickHouse: `signal_id`, `content`, `source_product`, `source_type`, `source_id`, `weight`, `timestamp`, `extra` |

### Rendering Helpers

`render_signal_to_text(signal, index=None)` and `render_signals_to_text(signals)` in `types.py` provide a canonical text representation of signals for LLM prompts. All signal rendering in prompts goes through these helpers to ensure consistency. Each signal renders as:

```text
Signal {index}:
- Source: {source_product} / {source_type}
- Weight: {weight}
- Timestamp: {timestamp}
- Description: {content}
```

---

## Key Configuration

| Setting                                  | Default                       | Description                                                                                                                                                          |
| ---------------------------------------- | ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SIGNAL_WEIGHT_THRESHOLD`                | `1.0`                         | Total weight needed to promote a report to candidate                                                                                                                 |
| `SIGNAL_MATCHING_LLM_MODEL`              | `claude-sonnet-4-5`           | LLM model for all signal operations                                                                                                                                  |
| `signals-combined-match-specificity`     | off (feature flag)            | Feature flag (distinct id = team id) enabling the combined single-call match + specificity path; checked per batch via activity, fail-closed, flips need no redeploy |
| `MAX_RESPONSE_TOKENS`                    | `4096`                        | Base max tokens for LLM responses (thinking uses 3× for max_tokens, 2× for budget)                                                                                   |
| Embedding model                          | `text-embedding-3-small-1536` | OpenAI embedding model used for signal content                                                                                                                       |
| Task queue                               | `VIDEO_EXPORT_TASK_QUEUE`     | Temporal task queue for all workflows                                                                                                                                |
| `BUFFER_MAX_SIZE`                        | `20`                          | Max signals buffered in memory before flush to S3                                                                                                                    |
| `BUFFER_FLUSH_TIMEOUT_SECONDS`           | `5`                           | Max seconds to wait for buffer to fill before flushing                                                                                                               |
| S3 prefix                                | `signals/signal_batches/`     | Object storage path for signal batch files (cleaned up by S3 lifecycle policies)                                                                                     |
| `COORDINATOR_INTERVAL_MINUTES`           | `30`                          | Signals agent coordinator poll cadence (Temporal schedule, `SKIP` overlap policy)                                                                                    |
| `MAX_RUNS_PER_TICK`                      | `50`                          | Hard cap on planned runs per coordinator tick (most-overdue-first, truncated after sort)                                                                             |
| `SignalScoutConfig.run_interval_minutes` | `1440`                        | Per-scout default schedule in minutes (daily); due-check, no sampling (`10`–`43200`)                                                                                 |
| `SignalScoutConfig.emit`                 | `True`                        | Per-scout emit gate — defaults emit-on; flip to `False` for dry-run (scout runs and logs, but `emit_finding` writes nothing)                                         |

---

## File Map

```text
products/signals/
├── ARCHITECTURE.md                  # This file
├── backend/
│   ├── admin.py                     # Django admin for SignalReport + SignalReportArtefact
│   ├── api.py                       # emit_signal() entry point + source/org guards
│   ├── apps.py                      # Django app config
│   ├── models.py                    # SignalReport, SignalReportArtefact, SignalTeamConfig, SignalUserAutonomyConfig, SignalReportTask, SignalSourceConfig, SignalScoutConfig, SignalScoutRun, SignalScratchpad, SignalProjectProfile, SignalEmissionRecord
│   ├── serializers.py               # DRF serializers for source configs, reports, artefacts, team config, user autonomy config
│   ├── utils.py                     # Compatibility re-exports for signal query helpers
│   ├── views.py                     # SignalViewSet, InternalSignalViewSet, SignalSourceConfigViewSet, SignalTeamConfigViewSet, SignalReportViewSet, SignalReportArtefactViewSet, SignalProcessingViewSet
│   ├── scout_harness/               # Headless Signals agent — see scout_harness/AGENTS.md
│   │   ├── AGENTS.md
│   │   ├── __init__.py              # Public re-exports (LoadedSkill, sync helpers, …)
│   │   ├── runner.py                # Per-run entrypoint; owns SignalScoutRun lifecycle + sandbox loop
│   │   ├── prompt.py                # System prompt assembly (skill + scratchpad + profile + run history)
│   │   ├── skill_loader.py          # Resolves signals-scout-* LLMSkill rows for a run
│   │   ├── lazy_seed.py             # Canonical SKILL.md → LLMSkill sync (sync_canonical_skills)
│   │   ├── limits.py                # DEFAULT_MAX_RUNTIME_S + ACTIVITY_SLACK_S + WORKFLOW_HARD_CEILING_S
│   │   ├── serializers.py           # DRF serializers for runs / scratchpad / project profile
│   │   ├── views.py                 # SignalScoutRunViewSet, SignalScratchpadViewSet, SignalProjectProfileViewSet
│   │   ├── profile/
│   │   │   ├── builders.py          # Deterministic builders for SignalProjectProfile inventory
│   │   │   └── schema.py            # Dataclasses for the inventory payload shape
│   │   └── tools/                   # Harness-internal tools the agent calls inside a run
│   │       ├── emit.py              # emit_signal_* — pushes findings as cross_source_issue signals
│   │       ├── scratchpad.py        # remember / forget / search_scratchpad — read/write/delete SignalScratchpad
│   │       ├── profile.py           # project_profile_* — read SignalProjectProfile snapshot
│   │       └── runs.py              # runs_* — read past SignalScoutRun rows for dedupe
│   ├── github_issues/               # Placeholder directory
│   ├── management/
│   │   ├── AGENTS.md
│   │   └── commands/
│   │       ├── analyze_report.py
│   │       ├── cleanup_signals.py
│   │       ├── clear_eval_data.py
│   │       ├── delete_all_signal_reports_for_team.py
│   │       ├── enable_signals_autonomy.py  # Sets team default priority + opts in users by email
│   │       ├── export_session_video.py
│   │       ├── ingest_signals_json.py
│   │       ├── ingest_video_segments.py
│   │       ├── list_signal_reports.py
│   │       ├── parse_sandbox_log.py
│   │       ├── reingest_team_signals.py   # Starts TeamSignalReingestionWorkflow for a team
│   │       ├── reset_signals_self_driving.py  # Dev-only: undo a self-driving wizard run (configs, custom scouts, run-state)
│   │       ├── run_signals_scout.py       # One-shot scout run; bypasses the coordinator
│   │       ├── select_repo.py
│   │       ├── signal_pipeline_status.py
│   │       ├── summarize_single_session.py
│   │       └── sync_signals_scout_skills.py  # Force a canonical SKILL.md sync to LLMSkill rows
│   ├── report_generation/
│   │   ├── AGENTS.md                # Documentation for the agentic report generation flow
│   │   ├── research.py              # Multi-turn sandbox research orchestration + output schemas + research task_run artefact creation
│   │   ├── resolve_reviewers.py     # Suggested-reviewer resolution and enrichment helpers
│   │   └── select_repo.py           # Repository selection sandbox flow
│   ├── test/
│   │   ├── test_agentic_report_activity.py
│   │   ├── test_api.py
│   │   ├── test_resolve_user_id.py
│   │   ├── test_signal_report_api.py
│   │   └── test_signal_source_config_api.py
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   ├── 0002_signalreport_clustering_fields.py
│   │   ├── 0003_alter_signalreport_status_and_more.py
│   │   ├── 0004_alter_content_type.py
│   │   ├── 0005_signalreportartefact_report_idx.py
│   │   ├── 0006_signal_source_config.py
│   │   ├── 0007_backfill_signal_source_config.py
│   │   ├── 0008_alter_signalsourceconfig_source_product_and_more.py
│   │   ├── 0009_add_new_signal_report_statuses.py
│   │   ├── 0010_add_data_import_signal_source_choices.py
│   │   ├── 0011_add_error_tracking_signal_types.py
│   │   ├── 0012_signalreport_run_count_and_more.py
│   │   ├── 0013_signalreport_suggested_reviewers.py
│   │   ├── 0014_signalreportartefact_report_type_idx.py
│   │   ├── 0015_alter_signalsourceconfig_source_product_and_more.py
│   │   ├── 0016_signalautonomyconfig_alter_signalreportartefact_type.py  # SignalTeamConfig, SignalUserAutonomyConfig, SignalReportTask
│   │   ├── 0017_add_resolved_signal_report_status.py
│   │   ├── 0018_alter_signalreportartefact_type.py
│   │   ├── 0019_alter_signalsourceconfig_source_product_and_more.py
│   │   ├── 0020_signaluserautonomyconfig_slack_notification_fields.py
│   │   ├── 0021_add_signals_scout_source.py        # cross_source_issue source variant
│   │   ├── 0022_add_signal_scout_models.py         # SignalScoutConfig, SignalScoutRun, SignalScratchpad
│   │   ├── 0023_signalscoutrun_summary.py          # SignalScoutRun.summary
│   │   ├── 0024_signalprojectprofile.py            # SignalProjectProfile
│   │   └── 0027_reshape_scout_config_per_scout.py  # per-(team, skill) config + per-scout schedules (drops runs_per_tick/enabled_skill_names)
│   └── temporal/
│       ├── __init__.py              # Registers Signals workflows and activities
│       ├── agentic/
│       │   ├── __init__.py          # Sandbox env / user-resolution helpers
│       │   ├── scout_coordinator.py # SignalsScoutCoordinatorWorkflow + per-tick due-check activity
│       │   ├── scout_scheduler.py   # RunSignalsScoutWorkflow + run_signals_scout_activity
│       │   ├── schedule.py          # Temporal Schedule definition (cadence + SKIP overlap policy)
│       │   ├── report.py            # Agentic report activity + artefact persistence
│       │   └── select_repository.py # Repository selection activity
│       ├── backfill_error_tracking.py # Backfill recent error tracking issues as signals
│       ├── buffer.py                # BufferSignalsWorkflow + object-storage flush/backpressure activities
│       ├── clickhouse.py            # Retry wrapper for HogQL / ClickHouse activity queries
│       ├── deletion.py              # SignalReportDeletionWorkflow
│       ├── emit_eval_signal.py      # EmitEvalSignalWorkflow — eval result → signal
│       ├── emitter.py               # SignalEmitterWorkflow — per-signal backpressure bridge
│       ├── grouping.py              # Legacy v1 workflow + active shared grouping implementation
│       ├── grouping_v2.py           # Active grouping v2 workflow + pause/unpause support
│       ├── llm.py                   # Shared Anthropic helper + token limits / thinking config
│       ├── reingestion.py           # SignalReportReingestionWorkflow + TeamSignalReingestionWorkflow
│       ├── report_safety_judge.py   # Report-level safety judge activity
│       ├── safety_filter.py         # Per-signal safety classifier activity
│       ├── signal_queries.py        # Canonical HogQL helpers for fetch/search/soft-delete/wait
│       ├── summary.py               # SignalReportSummaryWorkflow + report state transition activities
│       └── types.py                 # Shared dataclasses + signal rendering helpers
├── skills/                          # Signals skills — see skills/AGENTS.md
│   ├── AGENTS.md
│   ├── signals/                     # Official PostHog skill (published via posthog_ai/dist): querying signals data
│   ├── inbox-exploration/           # Official PostHog skill (published via posthog_ai/dist): browsing the inbox
│   ├── signals-scout-general/       # Scout fleet: cross-product generalist (SKILL.md + emit.md + conventions.md)
│   ├── signals-scout-ai-observability/ # Scout fleet: AI observability anomaly watcher
│   ├── signals-scout-logs/          # Scout fleet: logs anomaly watcher
│   ├── signals-scout-error-tracking/         # Scout fleet: error tracking anomaly watcher
│   ├── signals-scout-revenue-analytics/      # Scout fleet: revenue anomaly watcher
│   ├── signals-scout-surveys/                # Scout fleet: surveys anomaly + theme-aggregation watcher
│   ├── signals-scout-observability-gaps/     # Scout fleet: structural-gap watcher (P3 recommendations)
│   └── signals-scout-csp-violations/         # Scout fleet: CSP violation watcher
└── frontend/                        # Frontend components (not covered here)
```
