from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Default number of records to request per page. Langfuse defaults to 50; the legacy
# page-based endpoints and v3 scores cap `limit` at 100 (larger values 400).
DEFAULT_PAGE_SIZE = 100

# The v2 observations endpoint supports up to 1,000 rows per page. Langfuse's legacy read
# APIs are rate limited as low as 15 requests/minute on the Hobby plan, so max out the page
# size on the endpoint that allows it.
OBSERVATIONS_PAGE_SIZE = 1000

# Langfuse's list filters are creation/start-time based (there is no updated-at cursor), so
# rows updated after first sync — traces whose aggregated metrics change as observations
# arrive, observations that gain an endTime on completion — would be missed by a pure
# watermark. Re-read a trailing hour on each incremental run; merge dedupes on the primary key.
DEFAULT_INCREMENTAL_LOOKBACK_SECONDS = 60 * 60


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class LangfuseEndpointConfig:
    name: str
    # Path appended to the API host (e.g. `/api/public/traces`).
    path: str
    # Legacy endpoints paginate by page number (`page`/`limit` + `meta.totalPages`); the v2
    # observations and v3 scores endpoints use an opaque cursor returned in `meta.cursor`.
    pagination: Literal["page", "cursor"]
    # Server-side incremental filter param (`fromTimestamp` / `fromStartTime`), or None for
    # full-refresh-only endpoints.
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable, immutable datetime field to partition by. Never a mutable field.
    partition_key: Optional[str] = None
    # Order rows actually arrive in. "asc" only where we control the sort (traces via
    # `orderBy=timestamp.asc`); everywhere else Langfuse returns newest-first or the order is
    # undocumented, so "desc" keeps the watermark from checkpointing mid-sync.
    sort_mode: Literal["asc", "desc"] = "desc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = DEFAULT_PAGE_SIZE
    # Static query params sent on every request (e.g. `orderBy`, `fields`).
    extra_params: dict[str, str] = field(default_factory=dict)


# Top-level list endpoints only. Per-dataset fan-out endpoints (`/datasets/{name}/runs`,
# dataset run items) are intentionally excluded for now — they require a fan-out whose
# pagination/order semantics we cannot verify against the live API without credentials.
LANGFUSE_ENDPOINTS: dict[str, LangfuseEndpointConfig] = {
    "traces": LangfuseEndpointConfig(
        name="traces",
        path="/api/public/traces",
        pagination="page",
        incremental_param="fromTimestamp",
        incremental_fields=[_datetime_field("timestamp")],
        partition_key="timestamp",
        sort_mode="asc",
        # Ascending order makes new rows append past the current page, so page-number
        # pagination and per-batch watermark checkpointing both stay stable.
        extra_params={"orderBy": "timestamp.asc"},
    ),
    "observations": LangfuseEndpointConfig(
        name="observations",
        path="/api/public/v2/observations",
        pagination="cursor",
        incremental_param="fromStartTime",
        incremental_fields=[_datetime_field("startTime")],
        partition_key="startTime",
        page_size=OBSERVATIONS_PAGE_SIZE,
        # Only `core` and `basic` field groups are returned by default; request everything.
        extra_params={"fields": "core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context"},
    ),
    "scores": LangfuseEndpointConfig(
        name="scores",
        path="/api/public/v3/scores",
        pagination="cursor",
        incremental_param="fromTimestamp",
        incremental_fields=[_datetime_field("timestamp")],
        partition_key="timestamp",
        # Core fields are always returned; request the optional groups too.
        extra_params={"fields": "details,subject,annotation"},
    ),
    "sessions": LangfuseEndpointConfig(
        name="sessions",
        path="/api/public/sessions",
        pagination="page",
        incremental_param="fromTimestamp",
        incremental_fields=[_datetime_field("createdAt")],
        partition_key="createdAt",
    ),
    "prompts": LangfuseEndpointConfig(
        name="prompts",
        path="/api/public/v2/prompts",
        pagination="page",
        # Returns one row per prompt *name* (with a `versions` array), so `name` is the key.
        # `fromUpdatedAt` exists but filters on a mutable field — full refresh keeps this
        # small catalog table correct.
        primary_keys=["name"],
    ),
    "models": LangfuseEndpointConfig(
        name="models",
        path="/api/public/models",
        pagination="page",
    ),
    "datasets": LangfuseEndpointConfig(
        name="datasets",
        path="/api/public/v2/datasets",
        pagination="page",
        partition_key="createdAt",
    ),
    "dataset_items": LangfuseEndpointConfig(
        name="dataset_items",
        path="/api/public/dataset-items",
        pagination="page",
        partition_key="createdAt",
    ),
}

ENDPOINTS = tuple(LANGFUSE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LANGFUSE_ENDPOINTS.items()
}
