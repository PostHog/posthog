from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class CapsuleCRMEndpointConfig:
    name: str
    path: str
    # Wrapper key the list response nests its array under (e.g. {"parties": [...]}).
    data_key: str
    incremental_fields: list[IncrementalField]
    # True only when Capsule exposes the server-side `?since=<ISO8601>` change filter for this
    # list endpoint (parties, opportunities, kases). Every other endpoint is full refresh.
    supports_since: bool = False
    # Stable creation timestamp used for datetime partitioning. None for small metadata
    # endpoints with no creation timestamp / not worth partitioning.
    partition_key: Optional[str] = None
    # Comma-separated `embed` values folded into each request to pull related data in one round-trip.
    embed: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # `?since` filters by change date, so `updatedAt` is the only meaningful cursor.
    return [
        {
            "label": "updatedAt",
            "type": IncrementalFieldType.DateTime,
            "field": "updatedAt",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


CAPSULE_CRM_ENDPOINTS: dict[str, CapsuleCRMEndpointConfig] = {
    "parties": CapsuleCRMEndpointConfig(
        name="parties",
        path="/parties",
        data_key="parties",
        supports_since=True,
        partition_key="createdAt",
        embed="tags,fields,organisation",
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "opportunities": CapsuleCRMEndpointConfig(
        name="opportunities",
        path="/opportunities",
        data_key="opportunities",
        supports_since=True,
        partition_key="createdAt",
        embed="tags,fields",
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "kases": CapsuleCRMEndpointConfig(
        name="kases",
        path="/kases",
        data_key="kases",
        supports_since=True,
        partition_key="createdAt",
        embed="tags,fields",
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "tasks": CapsuleCRMEndpointConfig(
        name="tasks",
        path="/tasks",
        data_key="tasks",
        partition_key="createdAt",
        incremental_fields=[],
    ),
    "users": CapsuleCRMEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        incremental_fields=[],
    ),
    "milestones": CapsuleCRMEndpointConfig(
        name="milestones",
        path="/milestones",
        data_key="milestones",
        incremental_fields=[],
    ),
    "pipelines": CapsuleCRMEndpointConfig(
        name="pipelines",
        path="/pipelines",
        data_key="pipelines",
        incremental_fields=[],
    ),
    "categories": CapsuleCRMEndpointConfig(
        name="categories",
        path="/categories",
        data_key="categories",
        incremental_fields=[],
    ),
    "lost_reasons": CapsuleCRMEndpointConfig(
        name="lost_reasons",
        path="/lostreasons",
        data_key="lostReasons",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(CAPSULE_CRM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CAPSULE_CRM_ENDPOINTS.items()
}
