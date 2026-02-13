# Signals System Architecture

## Overview

The **Signals** product is a signal clustering and research pipeline. Signals from various PostHog products (experiments, web analytics, error tracking, session replay) get grouped into **SignalReports** via embedding similarity + LLM matching. When a group accumulates enough weight, a research workflow summarizes them and optionally creates a GitHub coding task.

---

## Temporal Workflows

There are two Temporal workflows defined in `backend/temporal/workflow.py`, with activities in `backend/temporal/activities.py`.

### `EmitSignalWorkflow` (`emit-signal`)

Processes a single incoming signal and assigns it to a report group.

**Flow:**

1. **Embed** the signal description → `get_embedding_activity`
2. **Generate 1-3 search queries** via LLM → `generate_search_queries_activity`
3. **Embed each query** → parallel `get_embedding_activity` calls
4. **Semantic search** ClickHouse `document_embeddings` for nearest neighbors per query → `run_signal_semantic_search_activity` (uses `cosineDistance()`)
5. **LLM match** — decides if signal belongs to an existing report or needs a new group → `llm_match_signal_activity`
6. **Assign** signal to a `SignalReport` in Postgres, increment weight/count, check promotion threshold → `assign_signal_to_report_activity`
7. **Emit to ClickHouse** via Kafka (embedding worker) → `emit_to_clickhouse_activity`
8. If promoted (weight ≥ `WEIGHT_THRESHOLD`, default `1.0`), **spawn child** `SignalResearchWorkflow`

Steps 1+2 run in parallel. Step 3 fans out in parallel for each query. Step 4 fans out in parallel for each query embedding.

### `SignalResearchWorkflow` (`signal-research`)

Runs when a report is promoted to `candidate` status. Summarizes the signal group.

**Flow:**

1. **Fetch signals** for the report from ClickHouse → `fetch_signals_for_report_activity` (max 100 signals)
2. **Mark in-progress** in Postgres → `mark_report_in_progress_activity`
3. **Summarize** via LLM → `summarize_signals_activity`
4. **Mark ready** with title/summary → `mark_report_ready_activity` (or `mark_report_failed_activity` on error)

Both workflows use the `VIDEO_EXPORT_TASK_QUEUE` task queue with 30-minute execution timeouts and 3-attempt retry policies on individual activities.

---

## Django Models (Postgres)

Defined in `backend/models.py`.

### `SignalReport`

The core model. Status machine:

```text
potential → candidate → in_progress → ready
                                    → failed
```

| Field                         | Type                         | Description                                                        |
| ----------------------------- | ---------------------------- | ------------------------------------------------------------------ |
| `team`                        | FK → Team                    | Owning team                                                        |
| `status`                      | CharField                    | One of: `potential`, `candidate`, `in_progress`, `ready`, `failed` |
| `total_weight`                | Float                        | Sum of all assigned signal weights                                 |
| `signal_count`                | Int                          | Number of signals assigned                                         |
| `title`                       | Text (nullable)              | LLM-generated title (set during matching or summarization)         |
| `summary`                     | Text (nullable)              | LLM-generated summary                                              |
| `error`                       | Text (nullable)              | Error message if status is `failed`                                |
| `conversation`                | FK → Conversation (nullable) | Optional linked conversation                                       |
| `signals_at_run`              | Int                          | Snapshot of signal count when research started                     |
| `promoted_at`                 | DateTime (nullable)          | When report was promoted to `candidate`                            |
| `last_run_at`                 | DateTime (nullable)          | When research workflow last ran                                    |
| `relevant_user_count`         | Int (nullable)               | Number of relevant users                                           |
| `cluster_centroid`            | ArrayField(Float) (nullable) | Embedding centroid for video segment clustering                    |
| `cluster_centroid_updated_at` | DateTime (nullable)          | When centroid was last updated                                     |

**Indexes:** `(team, status, promoted_at)`, `(team, created_at)`

### `SignalReportArtefact`

Binary artefacts attached to reports (e.g., `video_segment` type).

| Field     | Type              | Description                                |
| --------- | ----------------- | ------------------------------------------ |
| `team`    | FK → Team         | Owning team                                |
| `report`  | FK → SignalReport | Parent report (`related_name="artefacts"`) |
| `type`    | CharField         | Artefact type (e.g., `"video_segment"`)    |
| `content` | BinaryField       | JSON content stored as bytes               |

---

## ClickHouse Storage

Signals are stored in the **`posthog_document_embeddings`** table, which is shared across products (error tracking, session replay, LLM analytics, etc.).

### Table Schema

Defined in `products/error_tracking/backend/embedding.py`:

| Column          | Type                   | Description                                                                                         |
| --------------- | ---------------------- | --------------------------------------------------------------------------------------------------- |
| `team_id`       | Int64                  | Team identifier                                                                                     |
| `product`       | LowCardinality(String) | Product bucket — signals uses `'signals'`                                                           |
| `document_type` | LowCardinality(String) | Document type — signals uses `'signal'`                                                             |
| `model_name`    | LowCardinality(String) | Embedding model name (e.g., `text-embedding-3-small-1536`)                                          |
| `rendering`     | LowCardinality(String) | How content was rendered — signals uses `'plain'`                                                   |
| `document_id`   | String                 | Unique signal ID (UUID)                                                                             |
| `timestamp`     | DateTime64(3, 'UTC')   | Document creation time                                                                              |
| `inserted_at`   | DateTime64(3, 'UTC')   | When the embedding was inserted (used for dedup)                                                    |
| `content`       | String                 | The signal description text                                                                         |
| `metadata`      | String                 | JSON string containing `report_id`, `source_product`, `source_type`, `source_id`, `weight`, `extra` |
| `embedding`     | Array(Float64)         | The embedding vector                                                                                |

**Engine:** `ReplacingMergeTree` (sharded), partitioned by `toMonday(timestamp)`, 3-month TTL.

**Ordering:** `(team_id, toDate(timestamp), product, document_type, model_name, rendering, cityHash64(document_id))`

### Data Flow

```text
emit_embedding_request() → Kafka (document_embeddings_input topic)
    → Kafka table → Materialized View → Writable Distributed table → Sharded ReplacingMergeTree
```

### HogQL Queries

Activities query via `execute_hogql_query()` using the HogQL alias `document_embeddings`. Two main queries:

1. **Semantic search** (`run_signal_semantic_search_activity`): Uses `cosineDistance(embedding, {embedding})` to find nearest neighbors with a `report_id`, limited to last 1 month.
2. **Fetch for report** (`fetch_signals_for_report_activity`): Fetches all signals for a given `report_id`.

Both use `argMax(..., inserted_at)` grouped by `document_id` to handle deduplication from the `ReplacingMergeTree`.

---

## API Layer

### Entry Point: `emit_signal()` (`backend/api.py`)

The primary programmatic entry point. Called by other PostHog products to emit signals.

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
- Feature flag `product-autonomy` must be enabled for the team

Starts an `EmitSignalWorkflow` via Temporal with `ALLOW_DUPLICATE_FAILED_ONLY` reuse policy.

### REST Endpoints

Registered via `register_signal_report_routes()` in `backend/urls.py`.

#### `SignalViewSet` (DEBUG only)

| Method | Path    | Description                                 |
| ------ | ------- | ------------------------------------------- |
| POST   | `/emit` | Manually emit a signal (debug/testing only) |

#### `SignalReportViewSet` (read-only)

Feature-flagged behind `product-autonomy`.

| Method | Path                                | Description                                                               |
| ------ | ----------------------------------- | ------------------------------------------------------------------------- |
| GET    | `/signal_reports/`                  | List reports (filtered to `READY` status, ordered by `total_weight` desc) |
| GET    | `/signal_reports/{id}/`             | Retrieve a single report                                                  |
| POST   | `/signal_reports/analyze_sessions/` | Trigger video segment clustering workflow (DEBUG only)                    |
| GET    | `/signal_reports/{id}/artefacts/`   | List artefacts for a report                                               |

### Serializers (`backend/serializers.py`)

- **`SignalReportSerializer`** — Exposes `id`, `title`, `summary`, `status`, `total_weight`, `signal_count`, `relevant_user_count`, `created_at`, `updated_at`, `artefact_count`.
- **`SignalReportArtefactSerializer`** — Exposes `id`, `type`, `content` (parsed from JSON binary), `created_at`.

---

## LLM Integration (`backend/temporal/llm.py`)

Uses **Claude Sonnet 4.5** (`claude-sonnet-4-5`) via the Anthropic SDK, wrapped with PostHog analytics tracking.

### `generate_search_queries()`

Generates 1-3 search queries from different angles (feature/component, behavior/issue, business impact). Queries are truncated to 2048 tokens for embedding. Temperature: 0.7.

### `match_signal_with_llm()`

Discriminated union response:

- `{"match_type": "existing", "signal_id": "<id>"}` → looked up to get `report_id` → `ExistingReportMatch`
- `{"match_type": "new", "title": "...", "summary": "..."}` → `NewReportMatch`

Temperature: 0.2 (more deterministic).

### `summarize_signals()`

Takes a list of signals and produces a title (max 100 chars) + 2-4 sentence summary. Temperature: 0.3.

All LLM calls have a 3-attempt retry loop with conversation-style error correction (failed responses and error messages are appended as context for the next attempt).

---

## Django Signal Hook (`backend/signals.py`)

When a `SignalReport` is **created** (post-save), `create_task_for_signal_report` fires via `transaction.on_commit`:

1. Checks if the team has a GitHub integration
2. Gets the top-starred repository
3. Creates a `Task` (from the Tasks product) with origin `SESSION_SUMMARIES`
4. Executes a task processing workflow (coding agent)

---

## Data Types (`backend/temporal/types.py`)

| Type                           | Description                                                                                                                          |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| `EmitSignalInputs`             | Workflow input: `team_id`, `source_product`, `source_type`, `source_id`, `description`, `weight`, `extra`                            |
| `SignalCandidate`              | Search result: `signal_id`, `report_id`, `content`, `source_product`, `source_type`, `distance`                                      |
| `ExistingReportMatch`          | LLM decided signal matches existing report: `report_id`                                                                              |
| `NewReportMatch`               | LLM decided signal needs new group: `title`, `summary`                                                                               |
| `MatchResult`                  | Union: `ExistingReportMatch \| NewReportMatch`                                                                                       |
| `SignalResearchWorkflowInputs` | Research workflow input: `team_id`, `report_id`                                                                                      |
| `SignalData`                   | Signal fetched from ClickHouse: `signal_id`, `content`, `source_product`, `source_type`, `source_id`, `weight`, `timestamp`, `extra` |

---

## Key Configuration

| Setting                     | Default                       | Description                                          |
| --------------------------- | ----------------------------- | ---------------------------------------------------- |
| `SIGNAL_WEIGHT_THRESHOLD`   | `1.0`                         | Total weight needed to promote a report to candidate |
| `SIGNAL_MATCHING_LLM_MODEL` | `claude-sonnet-4-5`           | LLM model for all signal operations                  |
| Embedding model             | `text-embedding-3-small-1536` | OpenAI embedding model used for signal content       |
| Task queue                  | `VIDEO_EXPORT_TASK_QUEUE`     | Temporal task queue for both workflows               |

---

## File Map

```text
products/signals/
├── backend/
│   ├── admin.py              # Django admin for SignalReport + SignalReportArtefact
│   ├── api.py                # emit_signal() entry point + feature flag checks
│   ├── models.py             # SignalReport, SignalReportArtefact Django models
│   ├── serializers.py        # DRF serializers
│   ├── signals.py            # Django post-save hook → creates Task for GitHub
│   ├── urls.py               # Route registration
│   ├── views.py              # SignalViewSet (debug), SignalReportViewSet (read-only)
│   └── temporal/
│       ├── activities.py     # All Temporal activity definitions
│       ├── llm.py            # Anthropic LLM calls (query gen, matching, summarization)
│       ├── types.py          # Shared dataclasses
│       └── workflow.py       # EmitSignalWorkflow, SignalResearchWorkflow
└── frontend/                 # Frontend components (not covered here)
```
