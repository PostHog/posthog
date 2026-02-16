# Signals System Architecture

## Overview

The **Signals** product is a signal clustering and summarization pipeline. Signals from various PostHog products (experiments, web analytics, error tracking, session replay) get grouped into **SignalReports** via embedding similarity + LLM matching. When a group accumulates enough weight, a summary workflow summarizes the group, runs safety and actionability judges, and either marks the report as ready for a coding agent, defers to a human, or rejects it.

---

## Temporal Workflows

There are two Temporal workflows. The grouping workflow is defined in `backend/temporal/grouping.py`. The summary workflow is defined in `backend/temporal/summary.py`, with its LLM activities split across dedicated files.

Both workflows and all activities are registered in `backend/temporal/__init__.py` and wired into the `VIDEO_EXPORT_TASK_QUEUE` worker via `posthog/temporal/ai/__init__.py`.

### `EmitSignalWorkflow` (`emit-signal`)

Processes a single incoming signal and assigns it to a report group.

**Flow:**

1. **Embed** the signal description + **fetch signal type examples** from ClickHouse (parallel) → `get_embedding_activity`, `fetch_signal_type_examples_activity`
2. **Generate 1-3 search queries** via LLM (receives type examples for context) → `generate_search_queries_activity`
3. **Embed each query** → parallel `get_embedding_activity` calls
4. **Semantic search** ClickHouse `document_embeddings` for nearest neighbors per query → `run_signal_semantic_search_activity` (uses `cosineDistance()`)
5. **LLM match** — decides if signal belongs to an existing report or needs a new group → `llm_match_signal_activity`
6. **Assign** signal to a `SignalReport` in Postgres, increment weight/count, check promotion threshold → `assign_signal_to_report_activity`
7. **Emit to ClickHouse** via Kafka (embedding worker) → `emit_to_clickhouse_activity`
8. If promoted (weight ≥ `WEIGHT_THRESHOLD`, default `1.0`), **spawn child** `SignalReportSummaryWorkflow` (with `ALLOW_DUPLICATE_FAILED_ONLY` reuse policy, silently ignores `WorkflowAlreadyStartedError`)

Step 1 runs two activities in parallel. Step 2 depends on step 1 (needs the type examples). Steps 3+4 fan out in parallel for each query/embedding.

> **TODO:** Currently, multiple `EmitSignalWorkflow` instances can race for the same team. We should refactor to a single long-running "entity workflow" per team that receives signals via `@workflow.signal`, processes them sequentially, and uses `continue_as_new` to keep history bounded. `emit_signal()` would use `signal_with_start` to lazily create the workflow on first signal. This serializes grouping per team and gives a natural place to batch/debounce in the future.

### `SignalReportSummaryWorkflow` (`signal-report-summary`)

Runs when a report is promoted to `candidate` status. Summarizes the signal group, then runs judges to determine the report's fate.

**Flow:**

1. **Fetch signals** for the report from ClickHouse → `fetch_signals_for_report_activity` (max 100 signals)
2. **Mark in-progress** in Postgres → `mark_report_in_progress_activity`
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

Both workflows use the `VIDEO_EXPORT_TASK_QUEUE` task queue with 30-minute execution timeouts and 3-attempt retry policies on individual activities.

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
```

| Field                         | Type                         | Description                                                                         |
| ----------------------------- | ---------------------------- | ----------------------------------------------------------------------------------- |
| `team`                        | FK → Team                    | Owning team                                                                         |
| `status`                      | CharField                    | One of: `potential`, `candidate`, `in_progress`, `pending_input`, `ready`, `failed` |
| `total_weight`                | Float                        | Sum of all assigned signal weights (reset to 0 if deemed not actionable)            |
| `signal_count`                | Int                          | Number of signals assigned                                                          |
| `title`                       | Text (nullable)              | LLM-generated title (set during matching or summarization)                          |
| `summary`                     | Text (nullable)              | LLM-generated summary                                                               |
| `error`                       | Text (nullable)              | Error message if failed, or reason if pending input / reset to potential            |
| `conversation`                | FK → Conversation (nullable) | Optional linked conversation                                                        |
| `signals_at_run`              | Int                          | Snapshot of signal count when summary started                                       |
| `promoted_at`                 | DateTime (nullable)          | When report was promoted to `candidate` (cleared on reset to potential)             |
| `last_run_at`                 | DateTime (nullable)          | When summary workflow last ran                                                      |
| `relevant_user_count`         | Int (nullable)               | Number of relevant users                                                            |
| `cluster_centroid`            | ArrayField(Float) (nullable) | Embedding centroid for video segment clustering                                     |
| `cluster_centroid_updated_at` | DateTime (nullable)          | When centroid was last updated                                                      |

**Indexes:** `(team, status, promoted_at)`, `(team, created_at)`

### `SignalReportArtefact`

Binary artefacts attached to reports. Used for video segments and judge results.

| Field     | Type              | Description                                |
| --------- | ----------------- | ------------------------------------------ |
| `team`    | FK → Team         | Owning team                                |
| `report`  | FK → SignalReport | Parent report (`related_name="artefacts"`) |
| `type`    | CharField         | Artefact type (see `ArtefactType` enum)    |
| `content` | BinaryField       | JSON content stored as bytes               |

**Artefact types** (`SignalReportArtefact.ArtefactType` enum):

| Type                     | Content                                                                                                    |
| ------------------------ | ---------------------------------------------------------------------------------------------------------- |
| `video_segment`          | Video segment data from session clustering                                                                 |
| `safety_judgment`        | `{"choice": bool, "explanation": "..."}` — true = safe                                                     |
| `actionability_judgment` | `{"choice": "immediately_actionable" \| "requires_human_input" \| "not_actionable", "explanation": "..."}` |

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

Activities query via `execute_hogql_query()` using the HogQL alias `document_embeddings`. All queries filter to `product = 'signals'` and `document_type = 'signal'`, and use `argMax(..., inserted_at)` grouped by `document_id` to handle deduplication from the `ReplacingMergeTree`. Three main queries:

1. **Fetch signal type examples** (`fetch_signal_type_examples_activity`): Fetches one example signal per unique `(source_product, source_type)` pair from the last month, selecting the most recent example per type via `argMax(content, timestamp)`. Used to give the query generation LLM context about the heterogeneous signal landscape.
2. **Semantic search** (`run_signal_semantic_search_activity`): Uses `cosineDistance(embedding, {embedding})` to find nearest neighbors that have a `report_id`, limited to the last 1 month.
3. **Fetch for report** (`fetch_signals_for_report_activity`): Fetches all signals for a given `report_id`, ordered by timestamp ascending.

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

## LLM Integration

All LLM calls use **Claude Sonnet 4.5** (`claude-sonnet-4-5`) via the Anthropic SDK, wrapped with PostHog analytics tracking. Shared configuration and the generic `call_llm()` helper live in `backend/temporal/llm.py`.

### `call_llm()` (`backend/temporal/llm.py`)

A generic helper that abstracts the retry-validate-append-errors pattern used by all LLM calls. Takes a system prompt, user prompt, a `validate` function, and options for thinking, temperature, and retries. Returns the output of the validation function (generic over return type `T`).

Key behaviours:

- **Retry with conversation-style error correction:** On validation failure, the full response content (including thinking blocks when applicable) is appended as an assistant message, followed by the error as a user message, giving the LLM context to self-correct.
- **JSON enforcement:** For non-thinking calls, pre-fills the assistant response with `{` to prevent markdown fences. For thinking calls (where pre-fill is not supported), strips ` ```json ... ``` ` fences from the response if present.
- **Extended thinking:** When `thinking=True`, enables Anthropic extended thinking with `budget_tokens = MAX_RESPONSE_TOKENS` and `max_tokens = MAX_RESPONSE_TOKENS * 2`. Temperature is set to 1 (required by thinking). Full response blocks (including `ThinkingBlock`) are preserved in retry conversation history.
- **Debug logging:** In `DEBUG` mode, logs the raw LLM response text on validation failure.

### Grouping LLM calls (`backend/temporal/llm.py`)

#### `generate_search_queries()`

Generates 1-3 search queries from different angles (feature/component, behavior/issue, business impact). Accepts `signal_type_examples` — one example per `(source_product, source_type)` pair from the last month — which are included in the system prompt to give the LLM context about the heterogeneous signal landscape. The prompt explicitly instructs the LLM to generate queries that search _across_ signal types rather than generating one query per type. Queries are truncated to 2048 tokens for embedding. Temperature: 0.7.

#### `match_signal_with_llm()`

Discriminated union response:

- `{"match_type": "existing", "signal_id": "<id>"}` → looked up to get `report_id` → `ExistingReportMatch`
- `{"match_type": "new", "title": "...", "summary": "..."}` → `NewReportMatch`

Temperature: 0.2 (more deterministic).

### Summary LLM calls (each in its own file with activity + prompt + invocation)

#### `summarize_signals()` (`backend/temporal/summarize_signals.py`)

Takes a list of signals and produces a title (max 100 chars) + 2-4 sentence summary. The report is designed for consumption by both humans and coding agents. Temperature: 0.2.

#### `judge_report_safety()` (`backend/temporal/safety_judge.py`)

Assesses the report title, summary, and underlying signals for prompt injection and manipulation attempts. Checks for injected instructions targeting the coding agent, attempts to exfiltrate data, disable security features, introduce backdoors, or override system prompts.

Returns `{"choice": bool, "explanation": "..."}`. Explanation required when `choice` is `false`. Stores result as a `safety_judgment` artefact on the report. **Extended thinking enabled.**

#### `judge_report_actionability()` (`backend/temporal/actionability_judge.py`)

Assesses whether the report is actionable by a coding agent with MCP access to PostHog tools and code access to write PRs. Returns one of three outcomes via `ActionabilityChoice` enum:

- **`immediately_actionable`** — The coding agent can take concrete action now (bug fixes, experiment reactions, feature flag cleanup, perf improvements, UX fixes, config changes). Explanation optional.
- **`requires_human_input`** — Potentially actionable but needs human judgment first (business context, trade-offs, multiple valid approaches, significant user-facing impact). Explanation required (3-6 sentences).
- **`not_actionable`** — No useful code action can be derived (purely informational, too vague, requires external systems, expected behavior). Explanation required (3-6 sentences).

When in doubt, the LLM is instructed to defer to humans (`requires_human_input`) rather than making judgment calls or rejecting outright.

Stores result as an `actionability_judgment` artefact on the report. **Extended thinking enabled.**

---

## Data Types (`backend/temporal/types.py`)

| Type                                | Description                                                                                                                          |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `EmitSignalInputs`                  | Workflow input: `team_id`, `source_product`, `source_type`, `source_id`, `description`, `weight`, `extra`                            |
| `SignalCandidate`                   | Search result: `signal_id`, `report_id`, `content`, `source_product`, `source_type`, `distance`                                      |
| `ExistingReportMatch`               | LLM decided signal matches existing report: `report_id`                                                                              |
| `NewReportMatch`                    | LLM decided signal needs new group: `title`, `summary`                                                                               |
| `MatchResult`                       | Union: `ExistingReportMatch \| NewReportMatch`                                                                                       |
| `SignalReportSummaryWorkflowInputs` | Summary workflow input: `team_id`, `report_id`                                                                                       |
| `SignalTypeExample`                 | One example per `(source_product, source_type)` pair: `source_product`, `source_type`, `content`, `timestamp`, `extra`               |
| `SignalData`                        | Signal fetched from ClickHouse: `signal_id`, `content`, `source_product`, `source_type`, `source_id`, `weight`, `timestamp`, `extra` |

### Rendering Helpers

`render_signal_to_text(signal, index=None)` and `render_signals_to_text(signals)` in `types.py` provide a canonical text representation of signals for LLM prompts. All signal rendering in prompts goes through these helpers to ensure consistency. Each signal renders as:

```text
Signal {index}:
- Source: {source_product} / {source_type}
- Weight: {weight}
- Timestamp: {timestamp}
- Description: {content}
- Extra metadata: {extra}  (if present)
```

---

## Key Configuration

| Setting                     | Default                       | Description                                          |
| --------------------------- | ----------------------------- | ---------------------------------------------------- |
| `SIGNAL_WEIGHT_THRESHOLD`   | `1.0`                         | Total weight needed to promote a report to candidate |
| `SIGNAL_MATCHING_LLM_MODEL` | `claude-sonnet-4-5`           | LLM model for all signal operations                  |
| `MAX_RESPONSE_TOKENS`       | `4096`                        | Base max tokens for LLM responses (judges use 2×)    |
| Embedding model             | `text-embedding-3-small-1536` | OpenAI embedding model used for signal content       |
| Task queue                  | `VIDEO_EXPORT_TASK_QUEUE`     | Temporal task queue for both workflows               |

---

## File Map

```text
products/signals/
├── backend/
│   ├── admin.py                    # Django admin for SignalReport + SignalReportArtefact
│   ├── api.py                      # emit_signal() entry point + feature flag checks
│   ├── apps.py                     # Django app config
│   ├── models.py                   # SignalReport, SignalReportArtefact (with ArtefactType enum)
│   ├── serializers.py              # DRF serializers
│   ├── urls.py                     # Route registration
│   ├── views.py                    # SignalViewSet (debug), SignalReportViewSet (read-only)
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   ├── 0002_signalreport_clustering_fields.py
│   │   └── 0003_signalreport_pending_input_status.py
│   └── temporal/
│       ├── __init__.py             # Registers all workflows and activities (WORKFLOWS + ACTIVITIES lists)
│       ├── grouping.py             # EmitSignalWorkflow + grouping activities
│       ├── llm.py                  # call_llm() helper + shared LLM config + grouping LLM calls
│       ├── summary.py              # SignalReportSummaryWorkflow + state management activities
│       ├── summarize_signals.py    # Summarization LLM prompt + activity
│       ├── safety_judge.py         # Safety judge LLM prompt + activity (stores artefact, uses thinking)
│       ├── actionability_judge.py  # Actionability judge LLM prompt + activity (stores artefact, uses thinking)
│       └── types.py                # Shared dataclasses + signal rendering helpers
└── frontend/                       # Frontend components (not covered here)
```
