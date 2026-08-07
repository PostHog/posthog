from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class LangfuseEndpointConfig:
    name: str
    path: str
    # "page" endpoints use ?page=N with a meta.totalPages envelope; "cursor" endpoints
    # (v2 observations, v3 scores) return an opaque meta.cursor for the next page.
    pagination: Literal["page", "cursor"]
    page_size: int
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Server-side lower-bound query param for the incremental field (e.g. fromTimestamp).
    incremental_filter_param: Optional[str] = None
    # Extra query params sent on every request (orderBy, fields selection, ...).
    extra_params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    # The order rows are emitted in. Only traces accepts an explicit orderBy, which we pin
    # ascending; the other list endpoints return newest-first, so they are "desc".
    sort_mode: Literal["asc", "desc"] = "desc"
    # Safety overlap subtracted from the incremental watermark each run. Langfuse's time filters
    # are on event/creation time, so rows that arrive late (ingestion lag) would otherwise be
    # skipped forever. Re-pulled rows are deduped on the primary key by merge.
    incremental_lookback: Optional[timedelta] = None


_DEFAULT_LOOKBACK = timedelta(hours=1)

# Observation field groups: everything the v2 endpoint can return. Without this the API only
# returns the `core` and `basic` groups (no io/usage/cost columns).
_OBSERVATION_FIELDS = "core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context"

# Score field groups added on top of the always-returned core fields.
_SCORE_FIELDS = "details,subject,annotation"

# Endpoints cover the resources a user most commonly wants to analyze from an LLM observability
# platform: traces, observations, scores, sessions, prompts, datasets, and model pricing.
# Incremental support is only declared where the API documents a server-side timestamp filter.
LANGFUSE_ENDPOINTS: dict[str, LangfuseEndpointConfig] = {
    "traces": LangfuseEndpointConfig(
        name="traces",
        path="/api/public/traces",
        pagination="page",
        page_size=50,
        incremental_fields=[_datetime_incremental_field("timestamp")],
        default_incremental_field="timestamp",
        incremental_filter_param="fromTimestamp",
        # Pin a stable ascending order so pages don't shift as new traces arrive mid-sync,
        # and so the pipeline's incremental watermark advances safely per batch.
        extra_params={"orderBy": "timestamp.asc"},
        partition_key="timestamp",
        sort_mode="asc",
        incremental_lookback=_DEFAULT_LOOKBACK,
    ),
    "observations": LangfuseEndpointConfig(
        name="observations",
        path="/api/public/v2/observations",
        pagination="cursor",
        page_size=1000,  # documented maximum for the v2 bulk endpoint
        incremental_fields=[_datetime_incremental_field("startTime")],
        default_incremental_field="startTime",
        incremental_filter_param="fromStartTime",
        extra_params={"fields": _OBSERVATION_FIELDS},
        partition_key="startTime",
        # v2 observations return newest-first (startTime descending) and accept no orderBy.
        sort_mode="desc",
        incremental_lookback=_DEFAULT_LOOKBACK,
    ),
    "scores": LangfuseEndpointConfig(
        name="scores",
        path="/api/public/v3/scores",
        pagination="cursor",
        page_size=100,  # documented maximum for the v3 scores endpoint
        incremental_fields=[_datetime_incremental_field("timestamp")],
        default_incremental_field="timestamp",
        incremental_filter_param="fromTimestamp",
        extra_params={"fields": _SCORE_FIELDS},
        partition_key="timestamp",
        sort_mode="desc",
        incremental_lookback=_DEFAULT_LOOKBACK,
    ),
    "sessions": LangfuseEndpointConfig(
        name="sessions",
        path="/api/public/sessions",
        pagination="page",
        page_size=50,
        incremental_fields=[_datetime_incremental_field("createdAt")],
        default_incremental_field="createdAt",
        incremental_filter_param="fromTimestamp",
        partition_key="createdAt",
        sort_mode="desc",
        incremental_lookback=_DEFAULT_LOOKBACK,
    ),
    "prompts": LangfuseEndpointConfig(
        name="prompts",
        path="/api/public/v2/prompts",
        pagination="page",
        page_size=50,
        incremental_fields=[_datetime_incremental_field("lastUpdatedAt")],
        default_incremental_field="lastUpdatedAt",
        incremental_filter_param="fromUpdatedAt",
        # One row per prompt name (with a versions array); no stable creation field to partition on.
        primary_keys=["name"],
        sort_mode="desc",
    ),
    "datasets": LangfuseEndpointConfig(
        name="datasets",
        path="/api/public/v2/datasets",
        pagination="page",
        page_size=50,
        # No server-side timestamp filter -> full refresh only.
    ),
    "dataset_items": LangfuseEndpointConfig(
        name="dataset_items",
        path="/api/public/dataset-items",
        pagination="page",
        page_size=50,
        # Only filterable by datasetName/version, not by time -> full refresh only.
        partition_key="createdAt",
    ),
    "models": LangfuseEndpointConfig(
        name="models",
        path="/api/public/models",
        pagination="page",
        page_size=50,
        # No server-side timestamp filter -> full refresh only.
    ),
}

ENDPOINTS = tuple(LANGFUSE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LANGFUSE_ENDPOINTS.items()
}
