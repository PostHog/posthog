from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# US cloud host. EU-region accounts use https://eu.api.smith.langchain.com and self-hosted
# deployments use their own host — the user overrides via the source's `host` field.
DEFAULT_BASE_URL = "https://api.smith.langchain.com"

# Fields requested from POST /runs/query via `select`. The default select pulls heavyweight
# internals (manifest, serialized, events, S3 URL variants) that bloat every page and slow the
# tight run-query rate limits, so we ask only for the analytics-relevant columns.
RUNS_SELECT_FIELDS = [
    "id",
    "name",
    "run_type",
    "start_time",
    "end_time",
    "status",
    "error",
    "extra",
    "inputs",
    "outputs",
    "parent_run_id",
    "session_id",
    "reference_example_id",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_cost",
    "prompt_cost",
    "completion_cost",
    "first_token_time",
    "trace_id",
    "dotted_order",
    "tags",
    "thread_id",
    "feedback_stats",
]


@dataclass
class LangSmithEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # runs/query is a POST whose cursor lives in the JSON body; every other list endpoint is a
    # GET paginated with offset/limit query params.
    pagination: Literal["cursor", "offset"] = "offset"
    # Stable creation-style timestamp to partition by (never a mutable `modified_at` field).
    partition_key: Optional[str] = None
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Name of the server-side lower-bound time filter (`start_time` in the runs/query body,
    # `min_created_at` query param on feedback). None means no server-side window — full
    # refresh only.
    window_param: Optional[str] = None
    # Floor the first incremental backfill to the last N days instead of the entire retention
    # window, bounding the initial pull against the tight runs/query rate limits.
    default_lookback_days: Optional[int] = None
    # Trailing overlap re-subtracted from the watermark on every incremental run, re-pulling a
    # window of rows so runs whose fields mutate after creation (end_time, outputs, feedback
    # stats land when the run finishes) are re-read; the delta merge dedupes on the primary key.
    incremental_lookback: Optional[timedelta] = None
    # We request `order=asc` on runs/query, but we can't rely on response ordering across every
    # LangSmith deployment (offset endpoints document no ordering at all), so every incremental
    # endpoint declares `desc`: the pipeline then persists the watermark (max value seen) only at
    # successful job end instead of checkpointing per batch, which is correct under any actual
    # ordering. Mid-run recovery comes from the resumable cursor/offset state instead.
    sort_mode: Literal["asc", "desc"] = "asc"


_START_TIME_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "start_time",
        "type": IncrementalFieldType.DateTime,
        "field": "start_time",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


LANGSMITH_ENDPOINTS: dict[str, LangSmithEndpointConfig] = {
    # Traces and their nested spans (LLM calls, chains, tools, retrievers) across every tracing
    # project. The flagship table: one row per run, filtered server-side by start_time.
    "runs": LangSmithEndpointConfig(
        name="runs",
        path="/api/v1/runs/query",
        pagination="cursor",
        partition_key="start_time",
        incremental_fields=_START_TIME_INCREMENTAL_FIELDS,
        window_param="start_time",
        default_lookback_days=365,
        # end_time/outputs/feedback_stats land after the run starts; the start_time cursor alone
        # would freeze a run at its first-synced (possibly still-running) state.
        incremental_lookback=timedelta(hours=1),
        sort_mode="desc",
    ),
    # Tracing projects ("sessions" in the LangSmith API), with rolled-up run counts, costs, and
    # latency percentiles. Small list; no server-side time filter, so full refresh only.
    "projects": LangSmithEndpointConfig(
        name="projects",
        path="/api/v1/sessions",
        incremental_fields=[],
    ),
    "datasets": LangSmithEndpointConfig(
        name="datasets",
        path="/api/v1/datasets",
        incremental_fields=[],
    ),
    # Dataset examples across all datasets. The API versions examples via `as_of` snapshots
    # rather than a created/modified filter, so full refresh only.
    "examples": LangSmithEndpointConfig(
        name="examples",
        path="/api/v1/examples",
        incremental_fields=[],
    ),
    # Human and programmatic feedback scores attached to runs. `min_created_at` is a genuine
    # server-side filter; feedback edits move modified_at (not filterable), so the lookback
    # re-pulls a trailing window and merge dedupes on id.
    "feedback": LangSmithEndpointConfig(
        name="feedback",
        path="/api/v1/feedback",
        partition_key="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL_FIELDS,
        window_param="min_created_at",
        default_lookback_days=365,
        incremental_lookback=timedelta(hours=1),
        sort_mode="desc",
    ),
    "annotation_queues": LangSmithEndpointConfig(
        name="annotation_queues",
        path="/api/v1/annotation-queues",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(LANGSMITH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LANGSMITH_ENDPOINTS.items()
}
