from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


class SnykScope(Enum):
    """Where an endpoint lives in Snyk's resource hierarchy.

    Every Snyk REST resource except the org inventory itself is scoped under an
    organization, so fetching those tables means walking ``orgs -> <endpoint>``.
    """

    # Top-level collection reachable directly from the token (GET /rest/orgs).
    ORGANIZATION = "organization"
    # Fan out over every organization the token can see (GET /rest/orgs/{org_id}/...).
    PER_ORG = "per_org"
    # Fan out over the distinct groups of the organizations (GET /rest/groups/{group_id}/...).
    # Snyk lists groups only on a beta version, so the group ids come from the orgs' ``group_id``.
    PER_GROUP = "per_group"
    # Fan out over every row of another per-org endpoint (``parent_endpoint``), for example
    # GET /rest/orgs/{org_id}/collections/{collection_id}/...
    PER_ORG_CHILD = "per_org_child"


@dataclass(frozen=False)
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
    # The audit log search endpoints name the page size ``size`` instead of ``limit``.
    page_size_param: str = "limit"
    # JSONPath of the row list. The audit log search endpoints nest it under ``data.items``.
    data_selector: str = "data"
    # PER_ORG_CHILD only: the per-org endpoint whose rows this endpoint fans out over, and the
    # column (and path placeholder) that holds the parent row's id.
    parent_endpoint: Optional[str] = None
    parent_id_column: Optional[str] = None
    # When ``window_start_param`` is missing, the endpoint returns only a recent slice (audit log
    # search starts at the start of yesterday). A sync with no watermark sends the start of the
    # vendor's retention window instead.
    window_start_param: Optional[str] = None
    retention_days: Optional[int] = None
    # Audit log items have no id, so the transport hashes these fields into a synthetic ``id``.
    synthetic_id_fields: tuple[str, ...] = ()

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
# targets, and the high-value issues/findings table), plus memberships, collections, group
# organizations, container images and audit logs.
#
# Incremental vs full refresh: only the issues endpoint (``updated_after`` / ``created_after``)
# and the audit log search (``from``) document genuine server-side timestamp filters, so only
# they are marked incremental. The other endpoints have no reliable server-side time filter, so
# they ship full refresh and dedupe on their primary key.
# Snyk keeps audit logs for 90 days.
AUDIT_LOG_RETENTION_DAYS = 90
AUDIT_LOG_ID_FIELDS = ("created", "event", "org_id", "group_id", "project_id", "content")

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
    "org_memberships": SnykEndpointConfig(
        name="org_memberships",
        scope=SnykScope.PER_ORG,
        path="/orgs/{org_id}/memberships",
        primary_keys=["id", "organization_id"],
    ),
    "group_memberships": SnykEndpointConfig(
        name="group_memberships",
        scope=SnykScope.PER_GROUP,
        path="/groups/{group_id}/memberships",
        primary_keys=["id", "group_id"],
    ),
    "collections": SnykEndpointConfig(
        name="collections",
        scope=SnykScope.PER_ORG,
        path="/orgs/{org_id}/collections",
        primary_keys=["id", "organization_id"],
    ),
    # One row per project in a collection. A project can be in several collections, so the
    # collection id is part of the key.
    "collection_projects": SnykEndpointConfig(
        name="collection_projects",
        scope=SnykScope.PER_ORG_CHILD,
        path="/orgs/{org_id}/collections/{collection_id}/relationships/projects",
        primary_keys=["id", "collection_id", "organization_id"],
        parent_endpoint="collections",
        parent_id_column="collection_id",
    ),
    # Every org in each group, also the orgs the token is not a member of.
    "group_organizations": SnykEndpointConfig(
        name="group_organizations",
        scope=SnykScope.PER_GROUP,
        path="/groups/{group_id}/orgs",
        primary_keys=["id", "group_id"],
    ),
    "container_images": SnykEndpointConfig(
        name="container_images",
        scope=SnykScope.PER_ORG,
        path="/orgs/{org_id}/container_images",
        primary_keys=["id", "organization_id"],
    ),
    # Links each image to the targets it was imported through. One image can have several refs.
    "container_image_target_refs": SnykEndpointConfig(
        name="container_image_target_refs",
        scope=SnykScope.PER_ORG_CHILD,
        path="/orgs/{org_id}/container_images/{image_id}/relationships/image_target_refs",
        primary_keys=["id", "image_id", "organization_id"],
        parent_endpoint="container_images",
        parent_id_column="image_id",
    ),
    "org_audit_logs": SnykEndpointConfig(
        name="org_audit_logs",
        scope=SnykScope.PER_ORG,
        path="/orgs/{org_id}/audit_logs/search",
        primary_keys=["id", "organization_id"],
        partition_key="created",
        incremental_fields=[_timestamp_incremental_field("created")],
        incremental_param_by_field={"created": "from"},
        default_incremental_field="created",
        page_size_param="size",
        data_selector="data.items",
        window_start_param="from",
        retention_days=AUDIT_LOG_RETENTION_DAYS,
        synthetic_id_fields=AUDIT_LOG_ID_FIELDS,
    ),
    "group_audit_logs": SnykEndpointConfig(
        name="group_audit_logs",
        scope=SnykScope.PER_GROUP,
        path="/groups/{group_id}/audit_logs/search",
        primary_keys=["id", "group_id"],
        partition_key="created",
        incremental_fields=[_timestamp_incremental_field("created")],
        incremental_param_by_field={"created": "from"},
        default_incremental_field="created",
        page_size_param="size",
        data_selector="data.items",
        window_start_param="from",
        retention_days=AUDIT_LOG_RETENTION_DAYS,
        synthetic_id_fields=AUDIT_LOG_ID_FIELDS,
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
