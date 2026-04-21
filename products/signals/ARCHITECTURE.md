# Signals System Architecture

## Overview

The **Signals** product is a signal grouping and report-generation pipeline. Signals from multiple products and integrations — including session replay, LLM analytics, error tracking, GitHub, Linear, and Zendesk — are emitted into a shared ClickHouse embeddings table, grouped into **SignalReports** via embedding similarity + LLM matching, and then optionally promoted into an agentic report-research flow.

Today the active ingestion path is **emitter → buffer → grouping v2**. The summary path is no longer a simple "summarize signals" LLM step: it runs a report-level safety judge, selects a repository, then performs sandbox-backed multi-turn research that produces findings, actionability, priority, title, summary, and suggested reviewers. Reports that are immediately actionable can automatically start a Tasks coding run via the **autonomy** system.

---

## Temporal Workflows

Signals ingestion uses a three-stage pipeline: **emitter → buffer → grouping v2**. The emitter and buffer workflows are defined in `backend/temporal/emitter.py` and `backend/temporal/buffer.py`. The grouping v2 workflow is in `backend/temporal/grouping_v2.py` and delegates to the shared `_process_signal_batch()` implementation in `backend/temporal/grouping.py`. The report summary workflow is defined in `backend/temporal/summary.py`.

The original `TeamSignalGroupingWorkflow` (v1) in `backend/temporal/grouping.py` is still registered but is no longer started by `emit_signal()`. Its shared activities and `_process_signal_batch()` implementation are still actively used by v2.

Signals workflows and activities are registered in `backend/temporal/__init__.py` and wired into the `VIDEO_EXPORT_TASK_QUEUE` worker by `posthog/management/commands/start_temporal_worker.py`.
If you add or remove a Signals workflow/activity from `backend/temporal/__init__.py`, you also need to update `posthog/temporal/tests/ai/test_module_integrity.py` (`TestSignalsProductModuleIntegrity`). That test intentionally snapshots the registered workflow/activity lists and will fail until its expected names are updated.

Two additional Signals workflows also exist but are not part of the main report pipeline:

- `backfill-error-tracking` (`backend/temporal/backfill_error_tracking.py`) — backfills recent error tracking issues as signals
- `emit-eval-signal` (`backend/temporal/emit_eval_signal.py`) — converts LLMA evaluation results into Signals inputs on the Signals worker queue

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
5. **LLM match** — decide whether the signal belongs to an existing report or needs a new one
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
   - Persists `repo_selection`, `signal_finding`, `actionability_judgment`, `priority_judgment`, and `suggested_reviewers` artefacts atomically on success
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

#### Re-promotion

Reports are re-promoted when new evidence arrives, but not on every single signal forever. `signals_at_run` is advanced when a run starts, and the grouping logic only re-promotes when `signal_count >= signals_at_run`.

On re-promotion:

- **Repo selection** reuses the previous `repo_selection` artefact when possible
- **Agentic research** reconstructs previous findings / actionability / priority from artefacts and reuses prior work signal-by-signal when still valid
- **Agentic artefacts** from the previous run are deleted and replaced atomically before writing the new run’s artefacts
- **`SignalReportTask` rows are not deleted** on re-promotion; they are historical records of research and auto-started coding runs
- **Auto-start is deduplicated per report** by checking for an existing `SignalReportTask` with `relationship=implementation`
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

# Re-promotion: READY reports are re-promoted to candidate when enough new signals
# accumulate (signal_count >= signals_at_run), triggering a new summary run that
# reuses the previous repo selection and findings for already-seen signals.
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

JSON artefacts attached to reports. Used for video segments, safety / actionability judgments, research findings, repo selection, and suggested reviewers.

| Field     | Type              | Description                                |
| --------- | ----------------- | ------------------------------------------ |
| `team`    | FK → Team         | Owning team                                |
| `report`  | FK → SignalReport | Parent report (`related_name="artefacts"`) |
| `type`    | CharField         | Artefact type (see `ArtefactType` enum)    |
| `content` | TextField         | JSON content stored as text                |

**Artefact types** (`SignalReportArtefact.ArtefactType` enum):

| Type                     | Content                                                                                                                                        |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `video_segment`          | Video segment data from session clustering                                                                                                     |
| `safety_judgment`        | `{"choice": bool, "explanation": "..."}` — true = safe                                                                                         |
| `actionability_judgment` | `{"actionability": "immediately_actionable" \| "requires_human_input" \| "not_actionable", "explanation": "...", "already_addressed": bool}`   |
| `priority_judgment`      | `{"priority": "P0"\|"P1"\|"P2"\|"P3"\|"P4", "explanation": "..."}`                                                                             |
| `signal_finding`         | `{"signal_id": "...", "relevant_code_paths": [...], "relevant_commit_hashes": {"abc1234": "reason"}, "data_queried": "...", "verified": bool}` |
| `repo_selection`         | `{"repository": "owner/repo" \| null, "reason": "..."}`                                                                                        |
| `suggested_reviewers`    | `[{"github_login": "...", "github_name": "...", "relevant_commits": [...]}]` — enriched with current PostHog user data at serializer read time |

Notes:

- The serializer still supports legacy `actionability_judgment` payloads that used `choice` instead of `actionability`.
- Agentic report persistence deletes and replaces only the artefact types owned by the agentic path (`repo_selection`, `signal_finding`, `actionability_judgment`, `priority_judgment`, `suggested_reviewers`). `safety_judgment` is written separately by the safety judge.

**Indexes:** `(report)` (`signals_sig_report__idx`)

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
- `default_autostart_priority` defaults to `P0`
- Individual users can override this threshold via `SignalUserAutonomyConfig.autostart_priority`

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

### `SignalReportTask`

Tracks the relationship between signal reports and tasks (research sandbox runs, auto-started implementation tasks, etc.).

| Field          | Type              | Description                                                            |
| -------------- | ----------------- | ---------------------------------------------------------------------- |
| `id`           | UUID (PK)         | Primary key (UUIDModel)                                                |
| `team`         | FK → Team         | Owning team                                                            |
| `report`       | FK → SignalReport | Parent report (`related_name="report_tasks"`, cascade delete)          |
| `task`         | FK → Task         | The linked task (`related_name="signal_report_tasks"`, cascade delete) |
| `relationship` | CharField(200)    | One of: `repo_selection`, `research`, `implementation`                 |
| `created_at`   | DateTime          | Auto-set on creation                                                   |

Notes:

- `research` rows are created immediately when the multi-turn research sandbox session starts
- `implementation` rows are created when autonomy auto-starts a fix task
- Cascading delete on both `report` and `task` FKs
- Used as the guard against duplicate auto-starts (checks for existing `implementation` row)

### `SignalSourceConfig`

Per-team configuration for which signal sources are enabled.

| Field            | Type      | Description                                                                                                                                 |
| ---------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`           | FK → Team | Owning team (`related_name="signal_source_configs"`)                                                                                        |
| `source_product` | CharField | One of: `session_replay`, `llm_analytics`, `github`, `linear`, `zendesk`, `error_tracking` (`SourceProduct` enum)                           |
| `source_type`    | CharField | One of: `session_analysis_cluster`, `evaluation`, `issue`, `ticket`, `issue_created`, `issue_reopened`, `issue_spiking` (`SourceType` enum) |
| `enabled`        | Boolean   | Whether this source is active (default `True`)                                                                                              |
| `config`         | JSONField | Source-specific configuration                                                                                                               |
| `created_by`     | FK → User | User who created the config (nullable)                                                                                                      |

**Behavioral notes:**

- `SignalSourceConfig.is_source_enabled()` special-cases `llm_analytics`: eval signals are always allowed at the model gate and are then further filtered by the eval workflow’s own config checks.
- For session replay configs, serializer validation enforces that `config.recording_filters` is a JSON object when present.
- The serializer exposes a computed `status` field:
  - `session_analysis_cluster` derives status from the Temporal clustering workflow
  - data-import-backed sources (`github`, `linear`, `zendesk`) derive status from `ExternalDataSchema`

**Constraints:** Unique on `(team, source_product, source_type)`

---

## ClickHouse Storage

Signals are stored in the **`posthog_document_embeddings`** table, which is shared across products (error tracking, session replay, LLM analytics, etc.).

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
| GET    | `signals/reports/`                     | List reports. Excludes `deleted` always and excludes `suppressed` by default. Supports `?status=`, `?search=`, `?source_product=`, `?suggested_reviewers=`, and `?ordering=`.                                                                                                                                                       |
| GET    | `signals/reports/{id}/`                | Retrieve a single report                                                                                                                                                                                                                                                                                                            |
| DELETE | `signals/reports/{id}/`                | Soft-delete a report and its signals. Starts `SignalReportDeletionWorkflow`. On success returns `202`. If the workflow is already running, returns `200 {"status": "already_running"}`. The API immediately transitions the Postgres report to `deleted` to hide it from list results while ClickHouse cleanup runs asynchronously. |
| POST   | `signals/reports/{id}/state/`          | Transition report state. Body: `{ "state": "suppressed" \| "potential", ...transition_to kwargs }`. Only `suppressed` and `potential` are exposed via API. Returns `409` on invalid transitions and `400` on invalid arguments.                                                                                                     |
| POST   | `signals/reports/{id}/reingest/`       | **Staff-only.** Delete a report and re-ingest its signals. Starts `SignalReportReingestionWorkflow`. On success returns `202`. If already running, returns `200 {"status": "already_running"}`. Returns `403` for non-staff users.                                                                                                  |
| GET    | `signals/reports/{id}/artefacts/`      | List **all** artefacts for a report, ordered by `-created_at`                                                                                                                                                                                                                                                                       |
| GET    | `signals/reports/{id}/signals/`        | Fetch all signals for a report from ClickHouse, including full metadata                                                                                                                                                                                                                                                             |
| GET    | `signals/reports/available_reviewers/` | List available suggested reviewers for the team                                                                                                                                                                                                                                                                                     |

**Ordering:** Configurable via `?ordering=` with comma-separated fields. Supported fields: `status`, `is_suggested_reviewer`, `signal_count`, `total_weight`, `priority`, `created_at`, `updated_at`, `id`.

The `status` ordering uses semantic pipeline stage ranking:

- `ready=0`
- `pending_input=1`
- `in_progress=2`
- `candidate=3`
- `potential=4`
- `failed=5`
- `suppressed=6`
- `deleted=7`

Default ordering is **`-is_suggested_reviewer,status,-updated_at,id`**.

#### `SignalReportTaskViewSet`

Read-only list of tasks associated with a signal report. Nested under the reports router.

| Method | Path                          | Description                                  |
| ------ | ----------------------------- | -------------------------------------------- |
| GET    | `signals/reports/{id}/tasks/` | List `SignalReportTask` entries for a report |

Supports ordering via `?ordering=` with fields: `created_at`, `relationship`. Default: `-created_at`. Each item includes `id`, `relationship`, `task_id`, and `created_at`.

#### `SignalProcessingViewSet`

View + control API for the v2 grouping pipeline. Uses scope object `INTERNAL`.

| Method | Path                        | Description                            |
| ------ | --------------------------- | -------------------------------------- |
| GET    | `signals/processing/`       | Return current pause state             |
| PUT    | `signals/processing/pause/` | Pause grouping until a given timestamp |
| DELETE | `signals/processing/pause/` | Clear the paused state                 |

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
- **`SignalReportArtefactSerializer`**
  - Exposes `id`, `type`, `content`, `created_at`
  - Parses JSON text into structured content
  - For `suggested_reviewers`, enriches the stored GitHub-only payload with fresh PostHog org-member data at read time
- **`SignalReportTaskSerializer`**
  - Exposes `id`, `relationship`, `task_id`, `task_title`, `task_status`, `created_at`
  - `task_status` is derived from the latest `TaskRun` via prefetch

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

A `SignalReportTask(relationship=RESEARCH)` row is created immediately after the `MultiTurnSession` starts (before any research turns), linking the sandbox `Task` to the report.

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

Runs inside `_maybe_autostart_task_for_report()` in `temporal/agentic/report.py`, called after artefact persistence in `run_agentic_report_activity`.

**Guard clause** — all must pass:

- Report actionability is `immediately_actionable`
- Report has a `priority_judgment`
- Report has suggested reviewers
- No existing `SignalReportTask` with `relationship=implementation` for this report

**User selection** via `_resolve_autostart_assignee()`:

1. Map reviewer GitHub logins to PostHog user IDs via social auth (preserving reviewer relevance order)
2. Single query: fetch `User` objects whose ID is in that list **and** who have a `SignalUserAutonomyConfig` row (joined via `select_related`)
3. Walk candidates in reviewer order. For each user:
   a. Verify team membership via `user.teams.filter(id=team_id).exists()`
   b. Resolve their effective priority threshold: personal `autostart_priority` if set, otherwise the team's `default_autostart_priority`
   c. If `report_priority_rank <= threshold_rank` → return that user
4. If no user matches → skip

**Task creation:**

1. `Task.create_and_run(origin_product=SIGNAL_REPORT, ...)`
2. Create `SignalReportTask(relationship=IMPLEMENTATION)` linking the task to the report
3. Errors are caught and logged but do not fail the report workflow

### Priority Rank

`P0` is the highest severity (rank 0), `P4` is the lowest (rank 4). A report auto-starts only if `report_priority_rank <= user_threshold_rank`. So a team with `default_autostart_priority=P4` will auto-start on any priority, while `P0` will only auto-start for the most critical reports.

### Task Tracking

All report ↔ task relationships are tracked via `SignalReportTask`:

| Relationship     | Created when                                          | Created where                                                        |
| ---------------- | ----------------------------------------------------- | -------------------------------------------------------------------- |
| `research`       | Immediately after the research sandbox session starts | `run_multi_turn_research()` in `report_generation/research.py`       |
| `implementation` | After auto-starting a coding task                     | `_maybe_autostart_task_for_report()` in `temporal/agentic/report.py` |
| `repo_selection` | Reserved for future use                               | Not yet created anywhere                                             |

Both `report` and `task` FKs cascade on delete — deleting a report or task cleans up the relationship rows automatically.

### Eval-signal summarization (`backend/temporal/emit_eval_signal.py`)

Separate from report generation, the `emit-eval-signal` workflow uses `call_llm()` with extended thinking to turn an LLMA evaluation result into a signal-sized description plus significance score. Low-significance eval results are dropped before calling `emit_signal()`.

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

| Setting                        | Default                       | Description                                                                        |
| ------------------------------ | ----------------------------- | ---------------------------------------------------------------------------------- |
| `SIGNAL_WEIGHT_THRESHOLD`      | `1.0`                         | Total weight needed to promote a report to candidate                               |
| `SIGNAL_MATCHING_LLM_MODEL`    | `claude-sonnet-4-5`           | LLM model for all signal operations                                                |
| `MAX_RESPONSE_TOKENS`          | `4096`                        | Base max tokens for LLM responses (thinking uses 3× for max_tokens, 2× for budget) |
| Embedding model                | `text-embedding-3-small-1536` | OpenAI embedding model used for signal content                                     |
| Task queue                     | `VIDEO_EXPORT_TASK_QUEUE`     | Temporal task queue for all workflows                                              |
| `BUFFER_MAX_SIZE`              | `20`                          | Max signals buffered in memory before flush to S3                                  |
| `BUFFER_FLUSH_TIMEOUT_SECONDS` | `5`                           | Max seconds to wait for buffer to fill before flushing                             |
| S3 prefix                      | `signals/signal_batches/`     | Object storage path for signal batch files (cleaned up by S3 lifecycle policies)   |

---

## File Map

```text
products/signals/
├── ARCHITECTURE.md                  # This file
├── backend/
│   ├── admin.py                     # Django admin for SignalReport + SignalReportArtefact
│   ├── api.py                       # emit_signal() entry point + source/org guards
│   ├── apps.py                      # Django app config
│   ├── models.py                    # SignalReport, SignalReportArtefact, SignalTeamConfig, SignalUserAutonomyConfig, SignalReportTask, SignalSourceConfig
│   ├── serializers.py               # DRF serializers for source configs, reports, artefacts, team config, user autonomy config, report tasks
│   ├── utils.py                     # Compatibility re-exports for signal query helpers
│   ├── views.py                     # SignalViewSet, InternalSignalViewSet, SignalSourceConfigViewSet, SignalTeamConfigViewSet, SignalReportViewSet, SignalReportTaskViewSet, SignalProcessingViewSet
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
│   │       ├── select_repo.py
│   │       ├── signal_pipeline_status.py
│   │       └── summarize_single_session.py
│   ├── report_generation/
│   │   ├── AGENTS.md                # Documentation for the agentic report generation flow
│   │   ├── research.py              # Multi-turn sandbox research orchestration + output schemas + SignalReportTask(RESEARCH) creation
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
│   │   └── 0014_signalautonomyconfig_alter_signalreportartefact_type.py  # SignalTeamConfig, SignalUserAutonomyConfig, SignalReportTask
│   └── temporal/
│       ├── __init__.py              # Registers Signals workflows and activities
│       ├── agentic/
│       │   ├── __init__.py          # Sandbox env / user-resolution helpers
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
└── frontend/                        # Frontend components (not covered here)
```
