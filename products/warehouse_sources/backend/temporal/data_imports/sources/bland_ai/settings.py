from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BlandAIEndpointConfig:
    name: str
    primary_keys: list[str]
    # Field used to partition the warehouse table. Must be a stable creation timestamp,
    # never an updated_at-style field that rewrites partitions on every sync.
    partition_key: Optional[str] = None
    # Each page of listed calls is fanned out via GET /v1/calls/{call_id} and the detail's
    # `transcripts` array is emitted as one row per utterance (the list endpoint excludes
    # transcripts for size reasons).
    hydrate_transcripts: bool = False
    # True only when the API exposes a genuine server-side timestamp filter for this endpoint
    # (`start_date` on GET /v1/calls). Pathways have no timestamp filters at all.
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    description: str = ""


# Bland AI's warehouse-relevant resources:
#
# - `calls` — GET /v1/calls. Index-offset pagination (`from` + `limit`, default page size 1000)
#   with `total_count`/`count` in the response. Server-side `start_date` filter (date or full
#   ISO 8601 datetime, interpreted against call creation time) plus `ascending=true&sort_by=created_at`
#   give a genuine incremental cursor on `created_at`. The API also exposes `update_start_date` /
#   `sort_by=updated_at`, but that filter is date-only and the documented call object doesn't
#   list an `updated_at` field we could track a watermark on, so we conservatively key on
#   `created_at` only (post-call analysis edits to old calls require a full refresh to re-sync).
#
# - `call_transcripts` — transcripts are excluded from the list endpoint for size reasons, so this
#   endpoint lists calls (same pagination/filtering as `calls`) and hydrates each via
#   GET /v1/calls/{call_id}, emitting one row per transcript utterance. One extra request per call,
#   so it's off by default. Rows carry the parent `call_id` (utterance ids aren't documented as
#   globally unique, hence the composite key) and `call_created_at`, the parent call's creation
#   time — the incremental/partition field, since utterance timestamps aren't monotonic across
#   calls (a long call's utterances can postdate the next call's creation).
#
# - `pathways` — GET /v1/pathway. Small (name/description/nodes/edges per pathway), no timestamp
#   filters, so full refresh only.
BLAND_AI_ENDPOINTS: dict[str, BlandAIEndpointConfig] = {
    "calls": BlandAIEndpointConfig(
        name="calls",
        primary_keys=["call_id"],
        partition_key="created_at",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description=(
            "Metadata for every call dispatched or received by your account: status, timing, cost, "
            "post-call analysis, and pathway info. Transcripts are excluded — sync call_transcripts for those."
        ),
    ),
    "call_transcripts": BlandAIEndpointConfig(
        name="call_transcripts",
        primary_keys=["call_id", "id"],
        partition_key="call_created_at",
        hydrate_transcripts=True,
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "call_created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "call_created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        should_sync_default=False,
        description=(
            "One row per utterance spoken during a call. Requires one extra API request per call "
            "(transcripts are excluded from the call list endpoint), so syncs are slower than the calls table."
        ),
    ),
    "pathways": BlandAIEndpointConfig(
        name="pathways",
        primary_keys=["id"],
        description=(
            "Your conversational pathways — the node/edge graphs that drive agent conversations. "
            "Full refresh only (the API has no timestamp filters for pathways)."
        ),
    ),
}

ENDPOINTS = tuple(BLAND_AI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BLAND_AI_ENDPOINTS.items()
}
