from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class FulcrumEndpointConfig:
    name: str
    path: str  # e.g. "/records.json"
    data_key: str  # response wrapper key holding the array (e.g. "records")
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None  # stable creation-time field for datetime partitioning
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side `updated_since`-style time filter. Only records exposes one; everything
    # else is full-refresh only.
    supports_incremental: bool = False
    page_size: int = 1000  # Fulcrum caps per_page at 20000; keep pages small to bound memory
    should_sync_default: bool = True


def _updated_at_field() -> list[IncrementalField]:
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


FULCRUM_ENDPOINTS: dict[str, FulcrumEndpointConfig] = {
    # Records are the primary, high-volume stream. The list endpoint defaults to ordering by
    # updated_at ascending and exposes a genuine server-side `updated_since` filter (epoch
    # seconds), so it syncs incrementally on updated_at. Partition on created_at (stable).
    "records": FulcrumEndpointConfig(
        name="records",
        path="/records.json",
        data_key="records",
        partition_key="created_at",
        incremental_fields=_updated_at_field(),
        supports_incremental=True,
    ),
    # The resources below have no documented server-side time filter, so they're full refresh.
    "forms": FulcrumEndpointConfig(
        name="forms",
        path="/forms.json",
        data_key="forms",
        partition_key="created_at",
    ),
    "choice_lists": FulcrumEndpointConfig(
        name="choice_lists",
        path="/choice_lists.json",
        data_key="choice_lists",
        partition_key="created_at",
    ),
    "classification_sets": FulcrumEndpointConfig(
        name="classification_sets",
        path="/classification_sets.json",
        data_key="classification_sets",
        partition_key="created_at",
    ),
    "projects": FulcrumEndpointConfig(
        name="projects",
        path="/projects.json",
        data_key="projects",
        partition_key="created_at",
    ),
    "memberships": FulcrumEndpointConfig(
        name="memberships",
        path="/memberships.json",
        data_key="memberships",
        partition_key="created_at",
    ),
    "roles": FulcrumEndpointConfig(
        name="roles",
        path="/roles.json",
        data_key="roles",
    ),
    "changesets": FulcrumEndpointConfig(
        name="changesets",
        path="/changesets.json",
        data_key="changesets",
        partition_key="created_at",
    ),
    "webhooks": FulcrumEndpointConfig(
        name="webhooks",
        path="/webhooks.json",
        data_key="webhooks",
        partition_key="created_at",
    ),
    # Media metadata list endpoints. The identifier is `access_key` (a UUID), not `id`.
    "photos": FulcrumEndpointConfig(
        name="photos",
        path="/photos.json",
        data_key="photos",
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
    "signatures": FulcrumEndpointConfig(
        name="signatures",
        path="/signatures.json",
        data_key="signatures",
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
    "videos": FulcrumEndpointConfig(
        name="videos",
        path="/videos.json",
        data_key="videos",
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
    "audio": FulcrumEndpointConfig(
        name="audio",
        path="/audio.json",
        data_key="audio",  # note: singular wrapper key, not "audios"
        primary_keys=["access_key"],
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(FULCRUM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FULCRUM_ENDPOINTS.items()
}
