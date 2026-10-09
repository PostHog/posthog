from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class TwelveLabsEndpointConfig:
    name: str
    # `path` may contain an `{index_id}` or `{asset_id}` placeholder for fan-out endpoints.
    path: str
    incremental_fields: list[IncrementalField]
    # Field to partition by. Must be a STABLE creation-time field so partitions don't rewrite
    # on every sync (never `updated_at`).
    partition_key: Optional[str] = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    should_sync_default: bool = True
    # Fan out one request per parent index or asset. `path` is then a template with the parent's
    # placeholder, and the parent id is injected into every row.
    fan_out_over: Optional[Literal["indexes", "assets"]] = None
    # The child returns one object per parent instead of a paginated `data` list.
    single_object: bool = False
    # Extra static query params sent with every request to this endpoint.
    params: dict[str, Any] = field(default_factory=dict)


# Twelve Labs list endpoints all use page-number pagination (page + page_limit, max 50) and expose
# `created_at` / `updated_at` RFC 3339 filters with `sort_by` + `sort_option`. See
# https://docs.twelvelabs.io/v1.3/api-reference for the current (v1.3) API.
TWELVE_LABS_ENDPOINTS: dict[str, TwelveLabsEndpointConfig] = {
    # Indexes group uploaded videos and carry the model config, video_count and total_duration.
    # `updated_at` bumps whenever an index or its contents change, so it is a reliable incremental
    # cursor.
    "indexes": TwelveLabsEndpointConfig(
        name="indexes",
        path="/indexes",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
    ),
    # Video indexing tasks track the upload/indexing lifecycle (pending/indexing/ready/failed).
    # `updated_at` advances on each status transition, so incremental sync picks up progress.
    "tasks": TwelveLabsEndpointConfig(
        name="tasks",
        path="/tasks",
        incremental_fields=[_datetime_field("updated_at"), _datetime_field("created_at")],
    ),
    # Videos are nested under an index, so this fans out one paginated request per index. Shipped as
    # full refresh: the `updated_at` filter only advances for videos edited via the PUT method (per
    # the API docs), so it can't be trusted as an incremental cursor for a fan-out we cannot
    # curl-verify. Full refresh re-pulls every index's videos each sync; merge replaces on the
    # [index_id, _id] key. Off by default to avoid the extra per-index API cost on free plans.
    "videos": TwelveLabsEndpointConfig(
        name="videos",
        path="/indexes/{index_id}/videos",
        incremental_fields=[],
        primary_keys=["index_id", "_id"],
        should_sync_default=False,
        fan_out_over="indexes",
    ),
    # One transcription per video or audio asset, fetched with one request per asset. The endpoint
    # has no list form and no time filter, so it ships as full refresh, which also picks up
    # transcriptions that move from pending/processing to ready. Assets without a transcription 404
    # and are skipped. Partitioned on the parent asset's creation time, the only stable timestamp.
    # Word-level segmentation is left out: it multiplies row size for little analytical value over
    # sentences and speaker turns. Off by default because of the per-asset API cost.
    "asset_transcriptions": TwelveLabsEndpointConfig(
        name="asset_transcriptions",
        path="/assets/{asset_id}/transcription",
        incremental_fields=[],
        partition_key="asset_created_at",
        primary_keys=["asset_id"],
        should_sync_default=False,
        fan_out_over="assets",
        single_object=True,
        params={"include": "sentences,utterances"},
    ),
}

ENDPOINTS = tuple(TWELVE_LABS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TWELVE_LABS_ENDPOINTS.items()
}
