from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


class BugsnagScope(Enum):
    """Where an endpoint lives in BugSnag's resource hierarchy.

    The Data Access API is nested: a personal auth token grants access to one or more
    organizations, each organization owns projects, and most analytical resources
    (errors, events, releases, …) are scoped to a project. So fetching a project-scoped
    table means walking ``organizations -> projects -> <endpoint>``.
    """

    # Top-level collection reachable directly from the token (GET /user/organizations).
    ORGANIZATION = "organization"
    # Fan out over every organization the token can see (GET /organizations/{organization_id}/...).
    PER_ORG = "per_org"
    # Fan out over every project in every organization (GET /projects/{project_id}/...).
    PER_PROJECT = "per_project"


@dataclass
class BugsnagEndpointConfig:
    name: str
    scope: BugsnagScope
    # Path template. PER_ORG paths contain ``{organization_id}``; PER_PROJECT paths contain
    # ``{project_id}``. ORGANIZATION paths are static.
    path: str
    # Primary key columns used for merge dedup. For fan-out children the parent identifier is
    # included (and injected into every row) so the key is unique across the whole table — the
    # API only guarantees ids are unique within a parent resource.
    primary_keys: list[str]
    # Stable, creation-time datetime column to partition by. Never a `last_seen`/`updated_at`
    # style field — those move and would rewrite partitions every sync. None disables partitioning.
    partition_key: Optional[str] = None
    # The menu of incremental cursor candidates advertised to the user. Empty = full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Whether the table is selected for sync by default in the connection wizard.
    should_sync_default: bool = True


# BugSnag's id values are 24-character hex ObjectIds that are globally unique, but the Data Access
# API documents uniqueness only within a parent resource. We therefore include the parent id in
# every fan-out child's primary key (and inject it into the row) so merge dedup stays correct even
# if that assumption ever breaks — a redundant-but-safe composite never seeds duplicate rows.
BUGSNAG_ENDPOINTS: dict[str, BugsnagEndpointConfig] = {
    "organizations": BugsnagEndpointConfig(
        name="organizations",
        scope=BugsnagScope.ORGANIZATION,
        path="/user/organizations",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "projects": BugsnagEndpointConfig(
        name="projects",
        scope=BugsnagScope.PER_ORG,
        path="/organizations/{organization_id}/projects",
        primary_keys=["id", "organization_id"],
        partition_key="created_at",
    ),
    "collaborators": BugsnagEndpointConfig(
        name="collaborators",
        scope=BugsnagScope.PER_ORG,
        path="/organizations/{organization_id}/collaborators",
        primary_keys=["id", "organization_id"],
    ),
    "teams": BugsnagEndpointConfig(
        name="teams",
        scope=BugsnagScope.PER_ORG,
        path="/organizations/{organization_id}/teams",
        primary_keys=["id", "organization_id"],
    ),
    "errors": BugsnagEndpointConfig(
        name="errors",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/errors",
        primary_keys=["id", "project_id"],
        partition_key="first_seen",
    ),
    # Events can be very large (one row per captured event), so it's off by default to avoid a
    # surprise full-history sync. Enable deliberately when raw event-level data is needed.
    "events": BugsnagEndpointConfig(
        name="events",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/events",
        primary_keys=["id", "project_id"],
        partition_key="received_at",
        should_sync_default=False,
    ),
    "releases": BugsnagEndpointConfig(
        name="releases",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/releases",
        primary_keys=["id", "project_id"],
        partition_key="released_at",
    ),
    "pivots": BugsnagEndpointConfig(
        name="pivots",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/pivots",
        primary_keys=["event_field_display_id", "project_id"],
        should_sync_default=False,
    ),
    "event_fields": BugsnagEndpointConfig(
        name="event_fields",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/event_fields",
        primary_keys=["display_id", "project_id"],
        should_sync_default=False,
    ),
    "trace_fields": BugsnagEndpointConfig(
        name="trace_fields",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/trace_fields",
        primary_keys=["display_id", "project_id"],
        should_sync_default=False,
    ),
    "saved_searches": BugsnagEndpointConfig(
        name="saved_searches",
        scope=BugsnagScope.PER_PROJECT,
        path="/projects/{project_id}/saved_searches",
        primary_keys=["id", "project_id"],
    ),
}

ENDPOINTS = tuple(BUGSNAG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUGSNAG_ENDPOINTS.items()
}
