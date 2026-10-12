from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class DockerhubEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    sort_mode: SortMode = "asc"
    partition_key: Optional[str] = None
    """A STABLE field to partition on. Never an updated_at-style field, which would rewrite
    partitions on every sync."""
    org_scoped: bool = False
    """Reads from /v2/orgs or /v2/auditlogs, which only answer for an organization namespace."""


# Docker Hub management API v2 list endpoints (https://docs.docker.com/reference/api/hub/latest/).
# Only the audit log carries a server-side time filter (`from`/`to`); the repository, tag, member
# and group endpoints expose no updated_after/since parameter, so they are full refresh only.
# Tag rows carry a numeric `repository` id, not the repo name, so we inject `namespace` and
# `repository_name` into every tag row and key on those plus the tag name, because tag names are
# only unique within their repository.
DOCKERHUB_ENDPOINTS: dict[str, DockerhubEndpointConfig] = {
    "repositories": DockerhubEndpointConfig(name="repositories", primary_keys=["namespace", "name"]),
    "tags": DockerhubEndpointConfig(name="tags", primary_keys=["namespace", "repository_name", "name"]),
    "org_members": DockerhubEndpointConfig(name="org_members", primary_keys=["id"], org_scoped=True),
    "org_groups": DockerhubEndpointConfig(name="org_groups", primary_keys=["id"], org_scoped=True),
    "audit_logs": DockerhubEndpointConfig(
        name="audit_logs",
        # Audit events carry no id of their own, so the transport hashes each row's contents into
        # one. See `_audit_log_row`.
        primary_keys=["id"],
        incremental_fields=[incremental_field("timestamp")],
        # The audit log endpoint documents no ordering and takes no sort parameter, so we cannot
        # claim rows arrive oldest-first. "desc" is the safe reading of an unknown order, because
        # the pipeline then commits the watermark once at the end of the run from the highest
        # timestamp it saw, instead of checkpointing each batch as if the stream were ascending.
        sort_mode="desc",
        partition_key="timestamp",
        org_scoped=True,
    ),
    "audit_log_actions": DockerhubEndpointConfig(
        name="audit_log_actions",
        # Action names are unique within their group, not across the whole catalog.
        primary_keys=["action_group", "name"],
        org_scoped=True,
    ),
}

ENDPOINTS = tuple(DOCKERHUB_ENDPOINTS.keys())

ORG_SCOPED_ENDPOINTS = tuple(name for name, config in DOCKERHUB_ENDPOINTS.items() if config.org_scoped)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DOCKERHUB_ENDPOINTS.items() if config.incremental_fields
}
