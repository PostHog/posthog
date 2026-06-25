from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class LemlistEndpointConfig:
    name: str
    path: str
    # offset/limit pagination. Some lemlist endpoints (team, team/senders) return the full
    # result in a single response and expose no offset param, so they're fetched in one request.
    paginate: bool = True
    # lemlist's newer response shapes require `version=v2` on a couple of list endpoints.
    requires_version_v2: bool = False
    # `/team` returns a single object rather than an array; wrap it into a one-row table.
    single_object: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    partition_key: Optional[str] = None  # stable creation-time field for datetime partitioning
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side time filter param (minDate) is honoured only on /activities, so it's the one
    # endpoint that can sync incrementally. Everything else is full refresh.
    supports_incremental: bool = False
    # /activities returns newest-first and exposes no sort param, so its watermark must be
    # finalised at end-of-run (sort_mode="desc"); the paginated full-refresh endpoints request
    # createdAt ascending for stable page boundaries.
    sort_mode: SortMode = "asc"
    request_sort_by: Optional[str] = None
    request_sort_order: Optional[str] = None
    # Bound the first incremental sync so we don't pull the entire activity history at once.
    default_lookback_days: Optional[int] = None
    should_sync_default: bool = True


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


LEMLIST_ENDPOINTS: dict[str, LemlistEndpointConfig] = {
    "campaigns": LemlistEndpointConfig(
        name="campaigns",
        path="/campaigns",
        requires_version_v2=True,
        partition_key="createdAt",
        request_sort_by="createdAt",
        request_sort_order="asc",
    ),
    "activities": LemlistEndpointConfig(
        name="activities",
        path="/activities",
        requires_version_v2=True,
        partition_key="createdAt",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("createdAt")],
        sort_mode="desc",
        default_lookback_days=365,
    ),
    "team": LemlistEndpointConfig(
        name="team",
        path="/team",
        paginate=False,
        single_object=True,
        partition_key="createdAt",
    ),
    "team_senders": LemlistEndpointConfig(
        name="team_senders",
        path="/team/senders",
        paginate=False,
        primary_keys=["userId"],
    ),
    # lemlist marks Get Many Unsubscribes as legacy/deprecated, but it's the only documented list
    # endpoint that returns a flat array with a stable `_id`, so it's the practical choice for a
    # full-refresh table. Partitioning is left off because the docs disagree on the timestamp field
    # name (createdAt vs unsubscribedAt) — see canonical_descriptions for the documented shape.
    "unsubscribes": LemlistEndpointConfig(
        name="unsubscribes",
        path="/unsubscribes",
    ),
}

ENDPOINTS = tuple(LEMLIST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LEMLIST_ENDPOINTS.items()
}
