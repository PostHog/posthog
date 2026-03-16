# Signals System Architecture

## Overview

The **Signals** product is a signal clustering and summarization pipeline. Signals from various PostHog products (experiments, web analytics, error tracking, session replay) get grouped into **SignalReports** via embedding similarity + LLM matching. When a group accumulates enough weight, a summary workflow summarizes the group, runs safety and actionability judges, and either marks the report as ready for a coding agent, defers to a human, or rejects it.

---

## Temporal Workflows

Signal ingestion uses a three-stage pipeline: **emitter → buffer → grouping v2**. The emitter and buffer workflows are defined in `backend/temporal/emitter.py` and `backend/temporal/buffer.py`. The grouping v2 workflow is in `backend/temporal/grouping_v2.py` and delegates to `_process_signal_batch()` in `backend/temporal/grouping.py`. The summary workflow is defined in `backend/temporal/summary.py`, with its LLM activities split across dedicated files.

The original `TeamSignalGroupingWorkflow` (v1) in `backend/temporal/grouping.py` is still registered but no longer used by `emit_signal()`.

All workflows and activities are registered in `backend/temporal/__init__.py` and wired into the `VIDEO_EXPORT_TASK_QUEUE` worker via `posthog/temporal/ai/__init__.py`.

### Signal Ingestion Pipeline (v2)

The v1 `TeamSignalGroupingWorkflow` buffered raw `EmitSignalInputs` in memory and carried them over on `continue_as_new`. Under high signal volume the `continue_as_new` payload grew too large and failed. The v2 pipeline solves this by flushing buffered signals to S3, passing only lightweight object keys between workflows.

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
     │                                     │                           activity: flush to S3                     │
     │                                     │                                  ├──► S3: signals/signal_batches/<uuid>
     │                                     │                                  │                                  │
     │                                     │                           activity: signal-with-start               │
     │                                     │                                  ├─ submit_batch(object_key) ──────►│
     │                                     │                                  │                                  │
     │                                     │                           continue_as_new                    activity: read from S3
     │                                     │                                  │                                  ├──► S3
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
   a. **Query** the buffer workflow's `get_buffer_size` query
   b. If buffer is full (`>= BUFFER_MAX_SIZE`), **poll with jittered sleep** until space is available (heartbeating to stay alive)
   c. **Signal** the buffer workflow's `submit_signal` handler with the signal

This keeps `emit_signal()` fire-and-forget while the emitter workflow absorbs backpressure. The activity has a 1-hour `start_to_close_timeout` and 2-minute `heartbeat_timeout` to accommodate long waits under pressure.

### `BufferSignalsWorkflow` (`buffer-signals`)

Buffers incoming signals in memory and periodically flushes them to S3. One instance per team, with workflow ID `buffer-signals-{team_id}`.

Defined in `backend/temporal/buffer.py`.

**Architecture:**

- New signals arrive via `@workflow.signal` (`submit_signal`), sent by `SignalEmitterWorkflow` instances.
- Exposes `@workflow.query` (`get_buffer_size`) so emitters can implement backpressure by polling buffer occupancy before sending.
- The main loop waits for signals, then waits until either the buffer reaches `BUFFER_MAX_SIZE` (20) or `BUFFER_FLUSH_TIMEOUT_SECONDS` (60s) elapses since the first signal arrived.
- On flush: drains the buffer, writes all signals to S3 at `signals/signal_batches/<uuid>` via `flush_signals_to_s3_activity`, then sends the object key to the grouping v2 workflow via `signal_with_start_grouping_v2_activity` (which creates the grouping workflow if not already running).
- If the buffer is already full again after flushing (signals arrived during the flush activities), loops immediately to flush again rather than `continue_as_new` (avoids losing throughput to workflow restart).
- Otherwise calls `continue_as_new`, carrying over any signals that arrived between drain and now via `BufferSignalsInput.pending_signals`.
- S3 objects are cleaned up by S3 lifecycle policies, not by the workflows.

### `TeamSignalGroupingV2Workflow` (`team-signal-grouping-v2`)

Long-running entity workflow that processes batches of signals from S3. One instance per team, with workflow ID `team-signal-grouping-v2-{team_id}`.

Defined in `backend/temporal/grouping_v2.py`.

**Architecture:**

- Receives S3 object keys via `@workflow.signal` (`submit_batch`), sent by `BufferSignalsWorkflow`.
- Pending object keys are buffered in memory as a `list[str]` — lightweight compared to the v1 approach of buffering full `EmitSignalInputs` objects.
- The main loop waits for a batch key, downloads the signals from S3 via `read_signals_from_s3_activity`, then processes the full batch via `_process_signal_batch()` from `grouping.py`.
- Caches type examples across batches with a TTL (`TYPE_EXAMPLES_CACHE_TTL`, 5 minutes).
- Calls `continue_as_new` after each batch, carrying over any pending keys that arrived during processing.
- Errors processing a batch are caught and logged — the workflow continues to the next batch.

### `TeamSignalGroupingWorkflow` (`team-signal-grouping`) — v1, legacy

A long-running entity workflow that serializes all signal grouping for a single team. Exactly one instance per team, with workflow ID `team-signal-grouping-{team_id}`. **No longer used by `emit_signal()` — superseded by the v2 pipeline above.**

**Architecture:**

- New signals arrive via `@workflow.signal` (`submit_signal`). The workflow maintains an internal `signal_buffer: list[EmitSignalInputs]` as a FIFO queue.
- The main loop waits for buffered signals, processes them via `_process_signal_batch()` (with debouncing), and calls `continue_as_new` after `CONTINUE_AS_NEW_THRESHOLD` (20) signals to keep Temporal history bounded. Unprocessed signals in the buffer are carried over as workflow input.
- Sequential processing eliminates race conditions where concurrent workflows could assign related signals to different reports (stale semantic search results, duplicate LLM matching decisions).
- Errors processing a single signal are caught and logged — the workflow continues to the next signal.

**Signal processing flow** (per batch, in `_process_signal_batch()`):

1. **Embed** all signal descriptions + **fetch signal type examples** from ClickHouse (parallel) → `get_embedding_activity`, `fetch_signal_type_examples_activity`
2. **Generate 1-3 search queries** per signal via LLM (receives type examples for context) → `generate_search_queries_activity`
3. **Embed each query** → parallel `get_embedding_activity` calls
4. **Semantic search** ClickHouse `document_embeddings` for nearest neighbors per query → `run_signal_semantic_search_activity` (uses `cosineDistance()`)
5. **LLM match** — decides if signal belongs to an existing report or needs a new group → `match_signal_to_report_activity`
6. **Assign** signal to a `SignalReport` in Postgres, increment weight/count, check promotion threshold, **and emit to ClickHouse** via Kafka (embedding worker) — all in a single atomic operation → `assign_and_emit_signal_activity`
7. **Wait for ClickHouse** — poll ClickHouse until the last emitted signal appears so subsequent batches can find it during semantic search → `wait_for_signal_in_clickhouse_activity`
8. If promoted (weight ≥ `WEIGHT_THRESHOLD`, default `1.0`), **spawn child** `SignalReportSummaryWorkflow` (with `ALLOW_DUPLICATE_FAILED_ONLY` reuse policy, `ParentClosePolicy.ABANDON` so it survives `continue_as_new`, silently ignores `WorkflowAlreadyStartedError`)

Steps 1-4 run in parallel across all signals in the batch. Steps 5-7 run sequentially per signal, with earlier batch signals injected into later signals' candidate sets via local cosine distance.

### `SignalReportSummaryWorkflow` (`signal-report-summary`)

Runs when a report is promoted to `candidate` status. Summarizes the signal group, then runs judges to determine the report's fate.

**Flow:**

1. **Fetch signals** for the report from ClickHouse → `fetch_signals_for_report_activity` (no hard limit — fetches all signals for the report)
2. **Mark in-progress** in Postgres and advance `signals_at_run` by `SIGNALS_AT_RUN_INCREMENT` (3), so the report must accumulate that many new signals before it can be promoted and re-summarised again → `mark_report_in_progress_activity`
3. **Summarize** signals into a title + summary via LLM → `summarize_signals_activity` (`summarize_signals.py`)
4. **Safety judge** + **Actionability judge** — run **concurrently** via `asyncio.gather`:
   - **Safety judge** → `safety_judge_activity` (`safety_judge.py`) — assess for prompt injection / manipulation
   - **Actionability judge** → `actionability_judge_activity` (`actionability_judge.py`) — assess whether actionable by a coding agent
5. **Evaluate results** (safety checked first):
   - If **unsafe** → `mark_report_failed_activity` with error, **stop**
   - If **not actionable** → `reset_report_to_potential_activity` (weight → 0, status → `potential`), **stop**
   - If **requires human input** → `mark_report_pending_input_activity` (status → `pending_input`, stores draft title/summary), **stop**
   - If **immediately actionable** → continue
6. **Mark ready** with the generated title and summary → `mark_report_ready_activity`

On any unhandled exception, the workflow catches and calls `mark_report_failed_activity`.

The grouping workflow uses a 1-hour `run_timeout` (resets on each `continue_as_new`). The summary workflow uses a 30-minute `execution_timeout`. Both use 3-attempt retry policies on individual activities.

### `SignalReportReingestionWorkflow` (`signal-report-reingestion`)

Deletes a report and re-ingests its signals through the grouping pipeline. Useful when grouping decisions need to be re-evaluated (e.g., after improving LLM prompts, or when signals were incorrectly grouped).

Defined in `backend/temporal/reingestion.py`. Workflow ID: `signal-report-reingestion-{team_id}-{report_id}`.

**Flow:**

1. **Fetch signals** for the report from ClickHouse → `fetch_signals_for_report_activity` (reused from summary workflow). If no signals found, skips to step 3 (delete-only).
2. **Soft-delete signals** in ClickHouse → `soft_delete_report_signals_activity` — wraps the existing `soft_delete_report_signals()` helper from `api.py`, re-emitting each signal row with `metadata.deleted = true`.
   2b. **Wait for ClickHouse** → `wait_for_signal_in_clickhouse_activity` (reused from grouping workflow) — polls until the last soft-deleted signal lands, so re-ingested signals don't find stale rows during semantic search.
3. **Delete report** in Postgres → `delete_report_activity` — transitions the report to `deleted` status via `SignalReport.transition_to()`. Idempotent (no-ops if already deleted).
4. **Re-ingest signals** → `reingest_signals_activity` — converts each `SignalData` to an `emit_signal()` call, which handles org guards and `signal_with_start` into the per-team `TeamSignalGroupingWorkflow`. Signals go through the full grouping pipeline (embed → search → LLM match → assign) and may end up in different reports.

All activities use 3-attempt retry policies. The soft-delete activity (step 2) is idempotent by design.

### `SignalReportDeletionWorkflow` (`signal-report-deletion`)

Soft-deletes a report and all its signals. Triggered by the `DELETE /signal_reports/{id}/` endpoint.

Defined in `backend/temporal/deletion.py`. Workflow ID: `signal-report-deletion-{team_id}-{report_id}`.

**Flow:**

1. **Fetch signals** for the report from ClickHouse → `fetch_signals_for_report_activity`. If no signals found, skips to step 3 (delete-only).
2. **Soft-delete signals** in ClickHouse → `soft_delete_report_signals_activity`.
   2b. **Wait for ClickHouse** → `wait_for_signal_in_clickhouse_activity` — polls until the last soft-deleted signal lands.
3. **Delete report** in Postgres → `delete_report_activity`.

Shares all activities with the reingestion workflow — the only difference is that it stops after deletion (no re-ingestion step).

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

# Transitions enforced by SignalReport.transition_to():
# - deleted is terminal (no transitions out; excluded from API via queryset)
# - suppressed only transitions back to potential
# - any non-deleted status can transition to deleted or suppressed
# - snooze = transition to potential with snooze_for=N (sets signals_at_run = signal_count + N)
suppressed → potential
any (except deleted) → deleted
any (except deleted) → suppressed
```

| Field                         | Type                | Description                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ----------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `team`                        | FK → Team           | Owning team                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `status`                      | CharField           | One of: `potential`, `candidate`, `in_progress`, `pending_input`, `ready`, `failed`, `deleted`, `suppressed`                                                                                                                                                                                                                                                                                                                             |
| `total_weight`                | Float               | Sum of all assigned signal weights (reset to 0 if deemed not actionable)                                                                                                                                                                                                                                                                                                                                                                 |
| `signal_count`                | Int                 | Number of signals assigned                                                                                                                                                                                                                                                                                                                                                                                                               |
| `title`                       | Text (nullable)     | LLM-generated title (set during matching or summarization)                                                                                                                                                                                                                                                                                                                                                                               |
| `summary`                     | Text (nullable)     | LLM-generated summary                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `error`                       | Text (nullable)     | Error message if failed, or reason if pending input / reset to potential                                                                                                                                                                                                                                                                                                                                                                 |
| `signals_at_run`              | Int                 | **Forward-looking promotion threshold.** A `potential` report will not be promoted to `candidate` until `signal_count >= signals_at_run`. Defaults to 0, so fresh reports always pass immediately. Advanced by 3 each time a summary run starts, preventing the report from immediately re-promoting after being reset to potential. Snoozing sets this to `signal_count + N`, pushing the threshold forward by an additional N signals. |
| `promoted_at`                 | DateTime (nullable) | When report was promoted to `candidate` (cleared on reset to potential)                                                                                                                                                                                                                                                                                                                                                                  |
| `last_run_at`                 | DateTime (nullable) | When summary workflow last ran                                                                                                                                                                                                                                                                                                                                                                                                           |
| `conversation`                | **DEPRECATED**      | Was: FK → Conversation. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                                                                   |
| `relevant_user_count`         | **DEPRECATED**      | Was: Int for relevant user count. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                                                         |
| `cluster_centroid`            | **DEPRECATED**      | Was: ArrayField(Float) for video segment clustering. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                                      |
| `cluster_centroid_updated_at` | **DEPRECATED**      | Was: DateTime for centroid freshness. Wrapped in `deprecate_field()`                                                                                                                                                                                                                                                                                                                                                                     |

**Indexes:** `(team, status, promoted_at)`, `(team, created_at)`

### `SignalReportArtefact`

Binary artefacts attached to reports. Used for video segments and judge results.

| Field     | Type              | Description                                |
| --------- | ----------------- | ------------------------------------------ |
| `team`    | FK → Team         | Owning team                                |
| `report`  | FK → SignalReport | Parent report (`related_name="artefacts"`) |
| `type`    | CharField         | Artefact type (see `ArtefactType` enum)    |
| `content` | TextField         | JSON content stored as text                |

**Artefact types** (`SignalReportArtefact.ArtefactType` enum):

| Type                     | Content                                                                                                    |
| ------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `video_segment`          | Video segment data from session clustering                                                                 |
| `safety_judgment`        | `{"choice": bool, "explanation": "..."}` — true = safe                                                     |
| `actionability_judgment` | `{"choice": "immediately_actionable" \| "requires_human_input" \| "not_actionable", "explanation": "..."}` |

**Indexes:** `(report)` (`signals_sig_report__idx`)

### `SignalSourceConfig`

Per-team configuration for which signal sources are enabled.

| Field            | Type      | Description                                                          |
| ---------------- | --------- | -------------------------------------------------------------------- |
| `team`           | FK → Team | Owning team (`related_name="signal_source_configs"`)                 |
| `source_product` | CharField | One of: `session_replay`, `llm_analytics` (`SourceProduct` enum)     |
| `source_type`    | CharField | One of: `session_analysis_cluster`, `evaluation` (`SourceType` enum) |
| `enabled`        | Boolean   | Whether this source is active (default `True`)                       |
| `config`         | JSONField | Source-specific configuration (e.g., `recording_filters`)            |
| `created_by`     | FK → User | User who created the config (nullable)                               |

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

Activities query via `execute_hogql_query()` using the HogQL alias `document_embeddings`. All queries filter to `product = 'signals'` and `document_type = 'signal'`, and use `argMax(..., inserted_at)` grouped by `document_id` to handle deduplication from the `ReplacingMergeTree`. Key queries:

1. **Fetch signal type examples** (`fetch_signal_type_examples_activity`): Fetches one example signal per unique `(source_product, source_type)` pair from the last month, selecting the most recent example per type via `argMax(content, timestamp)`. Used to give the query generation LLM context about the heterogeneous signal landscape.
2. **Semantic search** (`run_signal_semantic_search_activity`): Uses `cosineDistance(embedding, {embedding})` to find nearest neighbors that have a `report_id`, limited to the last 1 month.
3. **Fetch for report** (`fetch_signals_for_report_activity`): Fetches all signals for a given `report_id`, ordered by timestamp ascending.
4. **Wait for ClickHouse** (`wait_for_signal_in_clickhouse_activity`): Polls for a specific `document_id` by exact `toDate(timestamp)` match and `inserted_at >= (now - 1 minute)`, confirming that _this specific ingestion_ landed before processing the next signal. Does not filter on `deleted` — if a signal was emitted into a deleted report it will still be found.

---

## API Layer

### Entry Point: `emit_signal()` (`backend/api.py`)

The primary programmatic entry point. Called by other PostHog products to emit signals. Ensures the `BufferSignalsWorkflow` is running (idempotent start, catches `WorkflowAlreadyStartedError`), then fires-and-forgets a `SignalEmitterWorkflow` with a unique ID per signal. The emitter handles backpressure — `emit_signal()` itself returns immediately.

### Utility: `soft_delete_report_signals()` (`backend/api.py`)

Centralized sync helper that soft-deletes all ClickHouse signals for a given report by re-emitting them with `metadata.deleted = true`, preserving original timestamps so rows replace originals via `ReplacingMergeTree`. Intentionally fetches all signals (including already-deleted ones) to be idempotent. Called by `soft_delete_report_signals_activity` (used by both deletion and reingestion workflows).

```python
await emit_signal(
    team=team,
    source_product="experiments",
    source_type="significance_reached",
    source_id=str(experiment.id),
    description="Experiment 'Homepage CTA' reached statistical significance...",
    weight=0.8,
    extra={"variant": "B", "p_value": 0.003},
)
```

**Guards:**

- Team must have `is_ai_data_processing_approved` on their organization

Uses `signal_with_start` to atomically create the per-team `TeamSignalGroupingWorkflow` if it doesn't exist, or send a signal to the running instance.

### REST Endpoints

Registered directly in `posthog/api/__init__.py` (imported as `products.signals.backend.views`).

#### `SignalViewSet` (DEBUG only)

| Method | Path    | Description                                 |
| ------ | ------- | ------------------------------------------- |
| POST   | `/emit` | Manually emit a signal (debug/testing only) |

#### `SignalSourceConfigViewSet`

Full CRUD for per-team signal source configurations. Uses `IsAuthenticated` + `APIScopePermission` (scope: `INTERNAL`).

| Method | Path                           | Description               |
| ------ | ------------------------------ | ------------------------- |
| GET    | `/signal_source_configs/`      | List configs for the team |
| POST   | `/signal_source_configs/`      | Create a new config       |
| GET    | `/signal_source_configs/{id}/` | Retrieve a config         |
| PATCH  | `/signal_source_configs/{id}/` | Update a config           |
| DELETE | `/signal_source_configs/{id}/` | Delete a config           |

#### `SignalReportViewSet`

Read + delete + state transitions. Uses `IsAuthenticated` + `APIScopePermission` (scope: `task`). Composed from `RetrieveModelMixin`, `ListModelMixin`, `DestroyModelMixin`, and `GenericViewSet`. Deleted reports are excluded from all endpoints via `safely_get_queryset`.

| Method | Path                              | Description                                                                                                                                                                                                                                                                   |
| ------ | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/signal_reports/`                | List reports (excludes `deleted` always, excludes `suppressed` by default), filterable by `?status=` query param, ordered by `-signal_count` by default                                                                                                                       |
| GET    | `/signal_reports/{id}/`           | Retrieve a single report                                                                                                                                                                                                                                                      |
| DELETE | `/signal_reports/{id}/`           | Soft-delete a report and its signals. Starts `SignalReportDeletionWorkflow` and returns `202 Accepted`.                                                                                                                                                                       |
| POST   | `/signal_reports/{id}/state/`     | Transition report state. Body: `{ "state": "suppressed" \| "potential", ...transition_to kwargs }`. Only `suppressed` and `potential` are exposed via API. Validates transitions via `SignalReport.transition_to()`. Returns 409 on invalid transition, 400 on bad arguments. |
| POST   | `/signal_reports/{id}/reingest/`  | **Staff-only.** Delete a report and re-ingest its signals. Starts `SignalReportReingestionWorkflow` and returns `202 Accepted`. Returns `403` for non-staff users.                                                                                                            |
| GET    | `/signal_reports/{id}/artefacts/` | List video segment artefacts for a report                                                                                                                                                                                                                                     |
| GET    | `/signal_reports/{id}/signals/`   | Fetch all signals for a report from ClickHouse, including full metadata                                                                                                                                                                                                       |

**Ordering:** Configurable via query params. Supported fields: `signal_count`, `total_weight`, `created_at`, `updated_at`. Default: `-signal_count`.

### Serializers (`backend/serializers.py`)

- **`SignalSourceConfigSerializer`** — Exposes `id`, `source_product`, `source_type`, `enabled`, `config`, `created_at`, `updated_at`. Validates that `recording_filters` in config is a dict when `source_product` is `session_replay`.
- **`SignalReportSerializer`** — Exposes `id`, `title`, `summary`, `status`, `total_weight`, `signal_count`, `signals_at_run`, `created_at`, `updated_at`, `artefact_count`.
- **`SignalReportArtefactSerializer`** — Exposes `id`, `type`, `content` (parsed from JSON text), `created_at`.

---

## LLM Integration

All LLM calls use **Claude Sonnet 4.5** (`claude-sonnet-4-5`) via the Anthropic SDK, wrapped with PostHog analytics tracking. Shared configuration and the generic `call_llm()` helper live in `backend/temporal/llm.py`.

### `call_llm()` (`backend/temporal/llm.py`)

A generic helper that abstracts the retry-validate-append-errors pattern used by all LLM calls. Takes a system prompt, user prompt, a `validate` function, and options for thinking, temperature, and retries. Returns the output of the validation function (generic over return type `T`).

Key behaviours:

- **Retry with conversation-style error correction:** On validation failure, the full response content (including thinking blocks when applicable) is appended as an assistant message, followed by the error as a user message, giving the LLM context to self-correct. For non-thinking calls, the assistant pre-fill `{` is re-appended after each error message.
- **JSON enforcement:** For non-thinking calls, pre-fills the assistant response with `{` to prevent markdown fences. For thinking calls (where pre-fill is not supported), strips ` ```json ... ``` ` fences from the response if present.
- **Extended thinking:** When `thinking=True`, enables Anthropic extended thinking with `budget_tokens = MAX_RESPONSE_TOKENS * 2` and `max_tokens = MAX_RESPONSE_TOKENS * 3`. Temperature is set to 1 (required by thinking). Full response blocks (including `ThinkingBlock`) are preserved in retry conversation history. Thinking is only enabled if the model is in the `ANTHROPIC_THINKING_MODELS` set.
- **Debug logging:** In `DEBUG` mode, logs the raw LLM response text on validation failure.

### Grouping LLM calls (`backend/temporal/llm.py`)

#### `generate_search_queries()`

Generates 1-3 search queries from different angles (feature/component, behavior/issue, business impact). Accepts `signal_type_examples` — one example per `(source_product, source_type)` pair from the last month — which are included in the system prompt to give the LLM context about the heterogeneous signal landscape. The prompt explicitly instructs the LLM to generate queries that search _across_ signal types rather than generating one query per type. Queries are truncated to 2048 tokens for embedding. Temperature: 0.7.

#### `match_signal_to_report()`

Discriminated union response — the LLM must output `reason` as the first key (chain-of-thought before decision):

- `{"reason": "...", "match_type": "existing", "signal_id": "<id>", "query_index": <int>}` → looked up to get `report_id` → `ExistingReportMatch` (with `MatchedMetadata` capturing parent signal, query, and reason)
- `{"reason": "...", "match_type": "new", "title": "...", "summary": "..."}` → `NewReportMatch` (with `NoMatchMetadata` capturing reason and rejected signal IDs)

Validation ensures the `signal_id` exists in the candidates and `query_index` is in range.

Temperature: 0.2 (more deterministic).

### Summary LLM calls (each in its own file with activity + prompt + invocation)

#### `summarize_signals()` (`backend/temporal/summarize_signals.py`)

Takes a list of signals and produces a title (max 75 chars) + 2-4 sentence summary. The report is designed for consumption by both humans and coding agents. Temperature: 0.2.

#### `judge_report_safety()` (`backend/temporal/safety_judge.py`)

Assesses the report title, summary, and underlying signals for prompt injection and manipulation attempts. Checks for injected instructions targeting the coding agent, attempts to exfiltrate data, disable security features, introduce backdoors, or override system prompts.

Returns `{"choice": bool, "explanation": "..."}`. Explanation required when `choice` is `false`. Stores result as a `safety_judgment` artefact on the report. **Extended thinking enabled.**

#### `judge_report_actionability()` (`backend/temporal/actionability_judge.py`)

Assesses whether the report is actionable by a coding agent with MCP access to PostHog tools and code access to write PRs. Returns one of three outcomes via `ActionabilityChoice` enum:

- **`immediately_actionable`** — The coding agent can take concrete action now (bug fixes, experiment reactions, feature flag cleanup, perf improvements, UX fixes, config changes, or deep investigation with jumping-off context). Explanation required.
- **`requires_human_input`** — Potentially actionable but needs human judgment first (business context, trade-offs, multiple valid approaches, purely informational). Explanation required.
- **`not_actionable`** — No useful code action can be derived (too vague, contradictory, insufficient evidence, expected behavior). Explanation required.

The prompt is biased toward `immediately_actionable` over `requires_human_input` (if the agent has _any_ unambiguous actions), and toward `not_actionable` over `requires_human_input` (to filter noise).

Stores result as an `actionability_judgment` artefact on the report. **Extended thinking enabled.**

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
| `BUFFER_MAX_SIZE`              | `100`                         | Max signals buffered in memory before flush to S3                                  |
| `BUFFER_FLUSH_TIMEOUT_SECONDS` | `60`                          | Max seconds to wait for buffer to fill before flushing                             |
| S3 prefix                      | `signals/signal_batches/`     | Object storage path for signal batch files (cleaned up by S3 lifecycle policies)   |

---

## File Map

```text
products/signals/
├── ARCHITECTURE.md                 # This file
├── backend/
│   ├── admin.py                    # Django admin for SignalReport + SignalReportArtefact
│   ├── api.py                      # emit_signal() entry point + org-level guard
│   ├── apps.py                     # Django app config
│   ├── models.py                   # SignalReport, SignalReportArtefact, SignalSourceConfig
│   ├── serializers.py              # DRF serializers (report, artefact, source config)
│   ├── views.py                    # SignalViewSet (debug), SignalReportViewSet, SignalSourceConfigViewSet
│   ├── github_issues/              # (empty — placeholder for GitHub issue ingestion)
│   ├── management/
│   │   └── commands/
│   │       ├── cleanup_signals.py
│   │       ├── download_github_issues.py
│   │       ├── ingest_github_issues.py
│   │       └── ingest_video_segments.py
│   ├── test/
│   │   └── test_signal_source_config_api.py
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   ├── 0002_signalreport_clustering_fields.py
│   │   ├── 0003_alter_signalreport_status_and_more.py
│   │   ├── 0004_alter_content_type.py
│   │   ├── 0005_signalreportartefact_report_idx.py
│   │   ├── 0006_signal_source_config.py
│   │   ├── 0007_backfill_signal_source_config.py
│   │   └── 0008_alter_signalsourceconfig_source_product_and_more.py
│   └── temporal/
│       ├── __init__.py             # Registers all workflows and activities (WORKFLOWS + ACTIVITIES lists)
│       ├── emitter.py              # SignalEmitterWorkflow — ephemeral per-signal workflow for backpressure
│       ├── buffer.py               # BufferSignalsWorkflow + S3 flush/read activities + backpressure activity
│       ├── grouping_v2.py          # TeamSignalGroupingV2Workflow — processes S3 batches via _process_signal_batch
│       ├── grouping.py             # TeamSignalGroupingWorkflow (v1, legacy) + _process_signal_batch + grouping activities
│       ├── emit_eval_signal.py     # EmitEvalSignalWorkflow + activity — LLMA eval → signal (fire-and-forget from evals queue)
│       ├── llm.py                  # call_llm() helper + shared LLM config + grouping LLM calls
│       ├── deletion.py             # SignalReportDeletionWorkflow — soft-delete signals + delete report
│       ├── reingestion.py          # SignalReportReingestionWorkflow + soft-delete/delete/reingest activities
│       ├── summary.py              # SignalReportSummaryWorkflow + state management activities
│       ├── summarize_signals.py    # Summarization LLM prompt + activity
│       ├── safety_judge.py         # Safety judge LLM prompt + activity (stores artefact, uses thinking)
│       ├── actionability_judge.py  # Actionability judge LLM prompt + activity (stores artefact, uses thinking)
│       └── types.py                # Shared dataclasses + signal rendering helpers
└── frontend/                       # Frontend components (not covered here)
```
