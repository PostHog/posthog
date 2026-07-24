from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


class SnykScope(Enum):
    """Where an endpoint lives in Snyk's resource hierarchy.

    Every Snyk REST resource except the org inventory itself is scoped under an
    organization, so fetching those tables means walking ``orgs -> <endpoint>``.
    """

    # Top-level collection reachable directly from the token (GET /rest/orgs).
    ORGANIZATION = "organization"
    # Fan out over every organization the token can see (GET /rest/orgs/{org_id}/...).
    PER_ORG = "per_org"


@dataclass
class SnykEndpointConfig:
    name: str
    scope: SnykScope
    # Path template relative to the ``/rest`` prefix. PER_ORG paths contain ``{org_id}``.
    path: str
    # Primary key columns used for merge dedup. Snyk ids are UUIDs, but the REST API only
    # documents uniqueness within a parent org, so fan-out children include the injected
    # ``organization_id`` in their key — a redundant-but-safe composite never seeds duplicates.
    primary_keys: list[str]
    # Stable, creation-time datetime column to partition by. Never ``updated_at`` — that moves
    # and would rewrite partitions every sync. None disables partitioning.
    partition_key: Optional[str] = None
    # The menu of incremental cursor candidates advertised to the user. Empty = full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental field to the server-side filter query param that bounds it
    # (e.g. ``updated_at`` -> ``updated_after``). Only populated when the API genuinely
    # filters server-side — an empty mapping keeps the endpoint full-refresh only.
    incremental_param_by_field: dict[str, str] = field(default_factory=dict)
    default_incremental_field: Optional[str] = None
    # Snyk's documented ``limit`` maximum is 100 for these endpoints (default is 10).
    page_size: int = 100

    @property
    def supports_incremental(self) -> bool:
        return bool(self.incremental_param_by_field)


def _timestamp_incremental_field(field_name: str) -> IncrementalField:
    return {
        "label": field_name,
        "type": IncrementalFieldType.DateTime,
        "field": field_name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Endpoint catalog. Coverage mirrors the canonical Snyk streams (org inventory, projects,
# targets, and the high-value issues/findings table).
#
# Incremental vs full refresh: only the issues endpoint documents genuine server-side
# timestamp filters (``updated_after`` / ``created_after``), so only issues is marked
# incremental. Orgs/projects/targets have no reliable server-side time filter, so they ship
# full refresh and dedupe on their primary key.
SNYK_ENDPOINTS: dict[str, SnykEndpointConfig] = {
    "organizations": SnykEndpointConfig(
        name="organizations",
        scope=SnykScope.ORGANIZATION,
        path="/orgs",
        primary_keys=["id"],
    ),
    "projects": SnykEndpointConfig(
        name="projects",
        scope=SnykScope.PER_ORG,
        path="/orgs/{org_id}/projects",
        primary_keys=["id", "organization_id"],
    ),
    "targets": SnykEndpointConfig(
        name="targets",
        scope=SnykScope.PER_ORG,
        path="/orgs/{org_id}/targets",
        primary_keys=["id", "organization_id"],
    ),
    "issues": SnykEndpointConfig(
        name="issues",
        scope=SnykScope.PER_ORG,
        path="/orgs/{org_id}/issues",
        primary_keys=["id", "organization_id"],
        partition_key="created_at",
        incremental_fields=[
            _timestamp_incremental_field("updated_at"),
            _timestamp_incremental_field("created_at"),
        ],
        incremental_param_by_field={
            "updated_at": "updated_after",
            "created_at": "created_after",
        },
        default_incremental_field="updated_at",
    ),
}

ENDPOINTS = tuple(SNYK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SNYK_ENDPOINTS.items()
}
