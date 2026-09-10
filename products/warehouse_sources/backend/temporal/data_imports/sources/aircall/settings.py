from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Aircall caps list pages at 50 items.
PAGE_SIZE = 50


# frozen=False: the shared FanoutEndpointLike protocol declares mutable attributes, which a
# frozen dataclass cannot satisfy. The instances are treated as immutable by convention.
@dataclass(frozen=False)
class AircallEndpointConfig:
    name: str
    path: str
    # For a list endpoint, the key the objects are nested under (e.g. {"calls": [...]}). For a
    # per-call Conversation Intelligence sub-resource, "$" — the whole body is the single row.
    data_key: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # When set, the transport re-anchors the `from` query param to the latest value of this
    # field once a page chain ends, to page around Aircall's hard 10k-record-per-query cap on
    # calls/contacts. Must be the same stable creation-time field the API's `from` filter
    # applies to.
    reanchor_field: Optional[str] = None
    page_size: int = PAGE_SIZE
    # Unused by the full-refresh CI children; kept so the config satisfies FanoutEndpointLike.
    default_incremental_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None


# The Conversation Intelligence sub-resources (transcription, sentiments, topics, evaluations)
# are all fetched per call, so they fan out over the calls list. The fan-out shape is identical
# for every one — only the path and table name differ — so a single shared config drives them.
# A call with no AI data (or a call deleted between the parent listing and this fetch) answers
# 404; ignoring it keeps the fan-out going instead of failing the whole table.
_CI_404_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]
_CALL_CI_FANOUT = DependentEndpointConfig(
    parent_name="calls",
    resolve_param="call_id",
    resolve_field="id",
    # Inject the parent call's id as `call_id` so the primary key is always present and unique
    # (one CI object per call), regardless of what the sub-resource body itself carries.
    include_from_parent=["id"],
    parent_field_renames={"id": "call_id"},
    # Walk the parent calls list ascending so its paginator can page past Aircall's 10k cap.
    parent_params={"order": "asc"},
    child_response_actions=_CI_404_IGNORE,
)


# Aircall timestamps are UNIX epoch seconds, so candidate incremental fields are stored as
# integers even though the UI presents them as datetimes. The `from`/`to` list filters take
# UNIX timestamps and filter on the resource's creation date, so incremental sync is only
# enabled where the cursor field lines up with what `from` actually filters on (calls ->
# started_at, contacts -> created_at). Everything else is full refresh.
AIRCALL_ENDPOINTS: dict[str, AircallEndpointConfig] = {
    "calls": AircallEndpointConfig(
        name="calls",
        path="/calls",
        data_key="calls",
        partition_key="started_at",
        reanchor_field="started_at",
        incremental_fields=[
            {
                "label": "started_at",
                "type": IncrementalFieldType.DateTime,
                "field": "started_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "contacts": AircallEndpointConfig(
        name="contacts",
        path="/contacts",
        data_key="contacts",
        partition_key="created_at",
        reanchor_field="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "users": AircallEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        partition_key="created_at",
    ),
    "teams": AircallEndpointConfig(
        name="teams",
        path="/teams",
        data_key="teams",
    ),
    "numbers": AircallEndpointConfig(
        name="numbers",
        path="/numbers",
        data_key="numbers",
        partition_key="created_at",
    ),
    "tags": AircallEndpointConfig(
        name="tags",
        path="/tags",
        data_key="tags",
    ),
    # Conversation Intelligence sub-resources, one object per call, fanned out over calls. Each
    # returns a flat per-call object, so "$" selects the whole body as the single row. These need
    # the AI Assist add-on on the account; without it every fetch is denied, which surfaces as an
    # auth error rather than an empty table.
    "call_transcriptions": AircallEndpointConfig(
        name="call_transcriptions",
        path="/calls/{call_id}/transcription",
        data_key="$",
        primary_key="call_id",
        fanout=_CALL_CI_FANOUT,
    ),
    "call_sentiments": AircallEndpointConfig(
        name="call_sentiments",
        path="/calls/{call_id}/sentiments",
        data_key="$",
        primary_key="call_id",
        fanout=_CALL_CI_FANOUT,
    ),
    "call_topics": AircallEndpointConfig(
        name="call_topics",
        path="/calls/{call_id}/topics",
        data_key="$",
        primary_key="call_id",
        fanout=_CALL_CI_FANOUT,
    ),
    "call_evaluations": AircallEndpointConfig(
        name="call_evaluations",
        path="/calls/{call_id}/evaluations",
        data_key="$",
        primary_key="call_id",
        fanout=_CALL_CI_FANOUT,
    ),
}

ENDPOINTS = tuple(AIRCALL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AIRCALL_ENDPOINTS.items() if config.incremental_fields
}
