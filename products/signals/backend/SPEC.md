# Signals System Specification

## Overview

The signals system allows PostHog products to emit "signals" (e.g., "experiment reached significance") that get clustered together. When sufficient related signals accumulate, a **Report** is created and a deep research run is triggered via the AI chat agent to analyze and summarize the findings.

## Core Concepts

### Signal (ClickHouse only)

Signals are stored in the `document_embeddings` table in ClickHouse - NOT in Django. They use the existing embedding infrastructure.

**Storage Schema** (in `document_embeddings`):

- `team_id`: int
- `product`: "signals"
- `document_type`: "signal"
- `document_id`: UUID of the signal
- `model_name`: embedding model used
- `rendering`: "plain"
- `timestamp`: when the signal was created
- `content`: plaintext description of the signal (what gets embedded)
- `metadata`: JSON containing:
  - `source_product`: string (e.g., "experiments", "feature_flags", "web_analytics")
  - `source_type`: string (e.g., "experiment_significance", "funnel_drop_off")
  - `source_id`: string (e.g., experiment ID)
  - `weight`: float (0.0-1.0) - importance/confidence of the signal
  - `report_id`: UUID | null - linked report once assigned
  - `extra`: dict - product-specific metadata

### Report (Django)

Reports aggregate signals and track the lifecycle of research runs.

**Lifecycle States:**

```text
potential → candidate → in_progress → ready
    │           │           │
    └───────────┴───────────┴──→ failed (terminal)
```

- **potential**: Report exists, collecting signals, below weight threshold
- **candidate**: Weight threshold met, waiting in queue for research run (may wait hours/days)
- **in_progress**: Research run actively processing
- **ready**: Research complete, report available
- **failed**: Research run failed (can be retried)

### ReportArtefact (Django)

Simple artifact storage for report outputs.

## Django Models

**Location:** `products/signals/backend/models.py`

### SignalReport

```python
class SignalReport(UUIDModel):
    class Status(models.TextChoices):
        POTENTIAL = "potential"
        CANDIDATE = "candidate"
        IN_PROGRESS = "in_progress"
        READY = "ready"
        FAILED = "failed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POTENTIAL)

    total_weight = models.FloatField(default=0.0)
    signal_count = models.IntegerField(default=0)

    conversation = models.ForeignKey("ee.Conversation", null=True, blank=True, on_delete=models.SET_NULL)
    signals_at_run = models.IntegerField(default=0)  # snapshot at last research run

    # LLM-generated during signal matching
    title = models.TextField(null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "status", "promoted_at"]),
            models.Index(fields=["team", "created_at"]),
        ]
```

### SignalReportArtefact

```python
class SignalReportArtefact(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    report = models.ForeignKey(SignalReport, on_delete=models.CASCADE, related_name="artefacts")
    type = models.CharField(max_length=100)
    content = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)
```

## Signal Emission Interface

Products emit signals via a simple async function:

```python
async def emit_signal(
    team_id: int,
    source_product: str,      # e.g., "experiments"
    source_type: str,         # e.g., "experiment_significance"
    source_id: str,           # e.g., experiment UUID
    description: str,         # plaintext, will be embedded
    weight: float = 0.5,      # 0.0-1.0
    extra: dict | None = None # product-specific metadata
) -> None:  # fire-and-forget, returns nothing
```

This is a **fire-and-forget Temporal workflow**. The `workflow_id = f"{team_id}:{source_product}:{source_type}:{source_id}"` prevents the same signal from being processed simultaneously, but does NOT prevent re-running for the same source_id (will create duplicates).

Controlled by `EMIT_SIGNALS_ENABLED` env var (default: false).

The flow:

1. Generates UUID for signal
2. Calls `generate_embedding()` synchronously to get embedding in-memory for immediate use
3. Proceeds with matching/assignment using the in-memory embedding
4. **After** matching completes and we know the `report_id`, emits to `KAFKA_DOCUMENT_EMBEDDINGS_INPUT_TOPIC` for async ClickHouse storage (so metadata includes correct `report_id`)

## Signal Processing Flow

### 1. Signal Ingestion

When a new signal arrives:

```python
async def process_new_signal(
    team_id: int,
    signal_id: str,
    embedding: list[float],
    weight: float,
    metadata: dict
) -> Report | None:
```

### 2. Report Matching

Find an existing report for a new signal:

```python
async def find_matching_report(
    team_id: int,
    signal: SignalData,  # full signal including description, embedding, metadata, etc.
) -> Report | None:
```

**LLM-based matching:**

Rather than using a naive cosine similarity threshold, we use an LLM to determine if a new signal belongs to an existing report. This is a one-shot call, not agentic. **The LLM always runs**, even if there are zero candidates - it handles both "match to existing" and "create new report" cases.

1. **ClickHouse lookup**: Find the 10 nearest signals that already have a report
   - Query `document_embeddings` for signals WITH a `report_id` set
   - Order by `cosineDistance(embedding, query_embedding)` ascending
   - Return top 10 candidates (may be empty)

2. **LLM decides**: Pass candidates (possibly empty) + the new signal to an LLM
   - Ask: "Which of these signals (if any) is describing the same thing as the new signal?"
   - **If match found**: LLM returns the matching signal's index → use that signal's report
   - **If no match**: LLM returns "none" + generates a title/summary for a new report

> **Note**: We currently assume no ingestion lag between the workflow and ClickHouse. In the future, we'll add a constraint that only one "new signal" workflow can run per team at a time, which will eliminate race conditions where duplicate reports could be created due to lag. For now, we accept this limitation.

```python
async def find_matching_report(
    team_id: int,
    signal: SignalData,  # full signal including description, embedding, metadata, etc.
) -> tuple[Report | None, str, str]:
    """
    Returns: (matching_report, title, summary)
    - If match found: (report, existing_title, existing_summary)
    - If no match: (None, new_title, new_summary) for creating a new report
    """
    # 1. ClickHouse: get 10 nearest signals WITH reports
    candidate_signals = await get_nearest_assigned_signals_ch(team_id, signal.embedding, limit=10)

    # 2. LLM decides - always runs, even with empty candidates
    match, title, summary = await llm_match_signal(signal, candidate_signals)

    if match:
        report = await Report.objects.aget(id=match.report_id)
        return (report, report.title, report.summary)

    return (None, title, summary)


async def llm_match_signal(
    signal: SignalData,
    candidates: list[SignalCandidate]  # may be empty
) -> tuple[SignalCandidate | None, str, str]:
    """
    One-shot LLM call to determine if new signal matches any candidate.
    Always runs, even with empty candidates list.

    Returns:
    - If match found: (matching_candidate, "", "") - will use existing report's title/summary
    - If no match: (None, new_title, new_summary) - for creating a new report
    """
    pass
```

### 3. Report Creation/Update

```python
async def assign_signal_to_report(
    team_id: int,
    signal_id: str,
    embedding: list[float],
    weight: float,
    metadata: dict,
    existing_report: Report | None
) -> Report:
```

If no matching report:

- Create new `Report` with `status=potential`, `total_weight = weight`

If matching report:

- Update signal's metadata with `report_id` in ClickHouse
- Add signal weight to `total_weight`
- **Run promotion check** (see below)

### 4. Promotion Check

```python
async def check_report_promotion(
    report: Report,
    weight_threshold: float = 1.0  # configurable
) -> bool:
```

If `total_weight >= weight_threshold` and `status == potential`:

- Promote to `candidate`
- Set `promoted_at = now()`

## Research Run Integration

### Triggering Research

Candidate reports are processed by a **cron job** that runs continuously (e.g., every 5 minutes):

```python
# Environment variable for configuration
SIGNAL_REPORT_CANDIDATE_WAIT_HOURS = float(os.getenv("SIGNAL_REPORT_CANDIDATE_WAIT_HOURS", "3"))

async def process_candidate_reports() -> list[Report]:
    """
    Cron job to find and process candidate reports.
    Run every 5 minutes via Celery beat.
    """
```

Finds reports where:

- `status == candidate`
- `promoted_at < now() - SIGNAL_REPORT_CANDIDATE_WAIT_HOURS`

For each, triggers research run and sets:

- `status = in_progress`
- `last_run_at = now()`
- `signals_at_run` = count of signals for this report (queried from ClickHouse)

### Research Workflow

Uses existing `ChatAgentWorkflow` infrastructure:

```python
@dataclass
class SignalResearchWorkflowInputs:
    team_id: int
    report_id: UUID
    signal_ids: list[str]  # fetched from document_embeddings
```

The workflow:

1. Creates a new `Conversation` with `type=DEEP_RESEARCH`
2. Constructs a research prompt from signal descriptions and metadata
3. Runs the chat agent with research-focused system prompt
4. Stores results in `ReportArtefact`
5. Updates `Report.status = ready`

### Temporal Workflow

```python
@workflow.defn(name="signal-research")
class SignalResearchWorkflow(AgentBaseWorkflow):
    # workflow_id = f"signals-report:{team_id}:{report_id}"

    @workflow.run
    async def run(self, inputs: SignalResearchWorkflowInputs) -> None:
        # 1. Fetch signals from ClickHouse
        # 2. Build research context
        # 3. Execute chat agent activity
        # 4. Store artifacts
        # 5. Update report status
```

## ClickHouse Queries

### Find Nearest Assigned Signals (for LLM matching)

```sql
SELECT
    document_id,
    content,
    JSONExtractString(metadata, 'report_id') as report_id,
    JSONExtractString(metadata, 'source_product') as source_product,
    JSONExtractString(metadata, 'source_type') as source_type,
    cosineDistance(embedding, {query_embedding}) as distance
FROM document_embeddings
WHERE team_id = {team_id}
  AND product = 'signals'
  AND document_type = 'signal'
  AND JSONExtractString(metadata, 'report_id') != ''  -- only signals already assigned to a report
ORDER BY distance ASC
LIMIT 10
```

### Fetch Signals for Report

```sql
SELECT
    document_id,
    content,
    metadata,
    timestamp
FROM document_embeddings
WHERE team_id = {team_id}
  AND product = 'signals'
  AND document_type = 'signal'
  AND JSONExtractString(metadata, 'report_id') = {report_id}
ORDER BY timestamp ASC
```

## Configuration

```python
# Environment variables with defaults
EMIT_SIGNALS_ENABLED = os.getenv("EMIT_SIGNALS_ENABLED", "false").lower() == "true"  # master switch
SIGNAL_WEIGHT_THRESHOLD = float(os.getenv("SIGNAL_WEIGHT_THRESHOLD", "1.0"))
SIGNAL_REPORT_CANDIDATE_WAIT_HOURS = float(os.getenv("SIGNAL_REPORT_CANDIDATE_WAIT_HOURS", "3"))
SIGNAL_MATCHING_LLM_MODEL = os.getenv("SIGNAL_MATCHING_LLM_MODEL", "gpt-4o-mini")  # for signal/report matching
# Embedding model: uses EmbeddingModelName.TEXT_EMBEDDING_3_SMALL_1536 from posthog.schema
```

## Example Usage

### Experiments Product

```python
# In experiments/signals.py
async def on_experiment_significance(experiment: Experiment, variant: str, p_value: float):
    await emit_signal(
        team_id=experiment.team_id,
        source_product="experiments",
        source_type="significance_reached",
        source_id=str(experiment.id),
        description=f"Experiment '{experiment.name}' reached statistical significance. "
                    f"Variant '{variant}' shows p-value of {p_value:.4f}. "
                    f"Goal: {experiment.goal_description}",
        weight=0.8 if p_value < 0.01 else 0.5,
        extra={
            "experiment_name": experiment.name,
            "variant": variant,
            "p_value": p_value,
        }
    )
```

### Web Analytics Product

```python
async def on_significant_traffic_change(team_id: int, page: str, change_pct: float):
    await emit_signal(
        team_id=team_id,
        source_product="web_analytics",
        source_type="traffic_anomaly",
        source_id=f"page:{page}",
        description=f"Significant traffic change detected on '{page}': {change_pct:+.1f}% "
                    f"compared to baseline.",
        weight=min(abs(change_pct) / 100, 1.0),
        extra={"page": page, "change_pct": change_pct}
    )
```

## Open Questions

(None remaining - all resolved in Q&A below)

## Q&A / Decisions

**Q: Should potential reports expire if they never reach the weight threshold?**

A: No - reports should never expire. The associated signals will eventually be deleted from ClickHouse after 3 months (per the TTL), but we keep the report around so it can match and accumulate new signals that come along later.

**Q: Should we deduplicate signals from the same source (e.g., experiment emits significance signal twice with slightly different p-values)?**

A: No deduplication - let signals stack. Repeated signals from the same source add to the weight of the report, which is the desired behavior. If something keeps firing signals, that's a stronger indication it deserves research attention.

**Q: If a report is `ready` (research complete) and new related signals come in, what happens?**

A: New signals should still be added to sufficiently similar reports regardless of status (including `ready`). The UI will display these new signals, and users will have the option to manually re-run the research if they want updated analysis. No automatic re-run.

**Q: Should we auto-retry failed reports?**

A: No - leave failed reports for manual intervention. The `error` field captures what went wrong for debugging, and users can manually trigger a re-run when ready.

**Q: How/when should users be notified about ready reports?**

A: Out of scope for v1. We'll revisit notifications (in-app, email, Slack, etc.) later.

**Q: How do we construct the research prompt from multiple signals?**

A: The agent receives the report UUID and uses a tool to fetch all related signals. The tool queries the `document_embeddings` table using the metadata column to select all signals where `metadata.report_id` matches. This lets the agent pull signal data as needed rather than stuffing everything into the initial prompt.

**Q: How does the LLM matching step work for clustering signals?**

A: The LLM is given the cosine distances between the new signal and all candidate signals, along with their sources and descriptions. It's instructed that the _meaning_ of the signals must be very similar, not just the category. For example, two "experiment significance" signals from different experiments should NOT match - they need to be about the same underlying thing. Exact prompt to be determined during implementation.

**Q: What's the expected range/meaning for signal weights?**

A: Weights are 0.0-1.0, and the threshold for promotion to candidate is 1.0. The semantics: a weight of 1.0 means "this alone should trigger research." Product teams calibrate accordingly:

- Experiments reaching significance: emit weight ~1.0 (always want research)
- New error tracking exception: emit weight ~0.1 (needs to stack up before research)
- Error frequency spike: might emit 0.5-1.0 depending on severity

Guidance to product teams: "If your signal hits weight 1.0, it becomes a candidate for research."

## Implementation Status

### Phase 1: Django Models [DONE]

- [x] `SignalReport` model at `products/signals/backend/models.py`
- [x] `SignalReportArtefact` model
- [x] Migration
- [x] Register in `INSTALLED_APPS`

### Phase 2: Signal Creation Flow [DONE]

- [x] Implement `emit_signal()` fire-and-forget API at `products/signals/backend/api.py`
- [x] Implement `EmitSignalWorkflow` Temporal workflow at `products/signals/backend/temporal/workflow.py`
- [x] Integrate with embedding worker to generate embeddings (`get_embedding_activity`)
- [x] Implement `get_nearest_assigned_signals_activity` - ClickHouse query for similar signals (last month)
- [x] Implement `llm_match_signal_activity` / `match_signal_with_llm()` - one-shot LLM matching with retries
- [x] Implement `assign_signal_to_report_activity` - creates or updates report, checks promotion
- [x] Implement `emit_to_clickhouse_activity` - emits signal to Kafka with correct report_id

Note: Currently disabled via `EMIT_SIGNALS_ENABLED=false`. Workflow not yet registered with Temporal worker.

### Phase 3: Research Workflow

- [ ] Create Celery beat task to find candidate reports ready for processing
- [ ] Create `SignalResearchWorkflow` Temporal workflow (`workflow_id = f"signals-report:{team_id}:{report_id}"`)
- [ ] Implement tool for agent to fetch signals by report ID
- [ ] Wire up workflow to create Conversation with `type=DEEP_RESEARCH`
- [ ] Handle success: update report status to `ready`, store artefacts
- [ ] Handle failure: update report status to `failed`, store error

### Out of Scope (Future)

- UI for viewing reports and signals
- User notifications
- Manual re-run triggering
- Admin/management commands

## Dependencies

- Existing `document_embeddings` ClickHouse table
- Existing embedding worker API (`emit_embedding_request`)
- Existing `ChatAgentWorkflow` Temporal workflow
- Existing `Conversation` model (with `Type.DEEP_RESEARCH`)
