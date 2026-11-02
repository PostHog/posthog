from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

MEGAPHONE_HOST = "cms.megaphone.fm"
MEGAPHONE_BASE_URL = f"https://{MEGAPHONE_HOST}/api"

# Megaphone caps `per_page` at 500.
PAGE_SIZE = 500

UPDATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "updatedAt",
    "type": IncrementalFieldType.DateTime,
    "field": "updatedAt",
    "field_type": IncrementalFieldType.DateTime,
}


@frozen
class MegaphoneEndpointConfig:
    name: str
    # `{organization_id}` is filled from the source config before the request is built.
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE
    fanout: Optional[DependentEndpointConfig] = None
    # Query param that carries the organization id, for endpoints scoped by query instead of path.
    organization_param: Optional[str] = None
    full_refresh_params: Optional[dict[str, str]] = None
    incremental_params: Optional[dict[str, str]] = None
    # Query param that takes the incremental watermark.
    incremental_param: Optional[str] = None
    # Stable, never-updated datetime used for partitioning.
    partition_key: Optional[str] = "createdAt"


# Podcasts are only listable per network.
PODCASTS_FANOUT = DependentEndpointConfig(
    parent_name="networks",
    resolve_param="network_id",
    resolve_field="id",
    include_from_parent=[],
)

MEGAPHONE_ENDPOINTS: dict[str, MegaphoneEndpointConfig] = {
    "networks": MegaphoneEndpointConfig(
        name="networks",
        path="/organizations/{organization_id}/networks",
        primary_keys=["id"],
        incremental_fields=[],
    ),
    "podcasts": MegaphoneEndpointConfig(
        name="podcasts",
        path="/networks/{network_id}/podcasts",
        primary_keys=["id"],
        incremental_fields=[],
        fanout=PODCASTS_FANOUT,
    ),
    # The organization-wide episode search avoids a walk over every network and podcast. It always
    # sorts by `orderBy` descending and filters on `filterBy` from `filterMin`, inclusive.
    # A full refresh orders by `pubdate`, which changes only when an episode is rescheduled. Ordering
    # by `updatedAt` would move an episode edited mid-walk onto a page already read, so the
    # replaced table would miss it.
    "episodes": MegaphoneEndpointConfig(
        name="episodes",
        path="/search/episodes",
        primary_keys=["id"],
        incremental_fields=[UPDATED_AT_INCREMENTAL_FIELD],
        default_incremental_field="updatedAt",
        organization_param="organizationId",
        full_refresh_params={"orderBy": "pubdate"},
        incremental_params={"orderBy": "updatedAt", "filterBy": "updatedAt"},
        incremental_param="filterMin",
    ),
}

ENDPOINTS = tuple(MEGAPHONE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in MEGAPHONE_ENDPOINTS.items() if config.incremental_fields
}
