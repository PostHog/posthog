from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.types import IncrementalField

# Which root listing a fan-out endpoint enumerates its parents from. Environments are
# discovered project-by-project, so their prerequisite is the projects listing.
ParentResource = Literal["organisation", "project", "environment"]


@dataclass
class FlagsmithEndpointConfig:
    name: str
    # Path under ``/api/v1``. A ``{parent}`` placeholder marks a fan-out endpoint queried
    # once per parent resource (organisation id, project id, or environment api_key). The
    # path may carry its own query string (e.g. the environments listing filter).
    path: str
    primary_keys: list[str]
    parent: ParentResource | None = None
    # Row field the parent identifier is injected into, so a single table stays meaningful
    # (and uniquely keyed) across parents whose rows don't carry the parent id themselves.
    parent_field: str | None = None
    # Static query params for the initial request. Only endpoints whose OpenAPI spec
    # documents ``page_size`` get one — DRF silently ignores it elsewhere, so don't imply it.
    params: dict[str, Any] = field(default_factory=dict)
    # A STABLE datetime field to partition by — never one that mutates on update.
    partition_key: str | None = None
    # Flagsmith's Admin API exposes no server-side updated-since/created-after filter on any
    # of these resources (verified against the live OpenAPI spec), so every endpoint is
    # full-refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


FLAGSMITH_ENDPOINTS: dict[str, FlagsmithEndpointConfig] = {
    # The organisation(s) the API key can administer. Organisation API keys are org-scoped,
    # so this is normally a single row.
    "organisations": FlagsmithEndpointConfig(
        name="organisations",
        path="/organisations/",
        primary_keys=["id"],
    ),
    # All projects visible to the key. Returns a plain JSON array (no pagination envelope).
    "projects": FlagsmithEndpointConfig(
        name="projects",
        path="/projects/",
        primary_keys=["id"],
    ),
    "environments": FlagsmithEndpointConfig(
        name="environments",
        path="/environments/?project={parent}",
        primary_keys=["id"],
        parent="project",
        parent_field="_project_id",
    ),
    "features": FlagsmithEndpointConfig(
        name="features",
        path="/projects/{parent}/features/",
        primary_keys=["id"],
        parent="project",
        parent_field="_project_id",
        # An explicit stable sort prevents page-boundary skips/duplicates while paginating.
        params={"page_size": 100, "sort_field": "created_date", "sort_direction": "ASC"},
        partition_key="created_date",
    ),
    # Current flag values per environment (environment defaults and segment overrides).
    "feature_states": FlagsmithEndpointConfig(
        name="feature_states",
        path="/environments/{parent}/featurestates/",
        primary_keys=["id"],
        parent="environment",
        parent_field="_environment_api_key",
        partition_key="created_at",
    ),
    "segments": FlagsmithEndpointConfig(
        name="segments",
        path="/projects/{parent}/segments/",
        primary_keys=["id"],
        parent="project",
        parent_field="_project_id",
        params={"page_size": 100},
        partition_key="created_at",
    ),
    # Append-only change history for the organisation. Retention on Flagsmith SaaS is
    # plan-gated, so the table reflects the currently retained window.
    "audit_logs": FlagsmithEndpointConfig(
        name="audit_logs",
        path="/organisations/{parent}/audit/",
        primary_keys=["id"],
        parent="organisation",
        parent_field="_organisation_id",
        params={"page_size": 100},
        partition_key="created_date",
    ),
    # Organisation members. Returns a plain JSON array. A user can belong to more than one
    # organisation, so the composite key includes the injected ``_organisation_id``.
    "users": FlagsmithEndpointConfig(
        name="users",
        path="/organisations/{parent}/users/",
        primary_keys=["id", "_organisation_id"],
        parent="organisation",
        parent_field="_organisation_id",
    ),
}

ENDPOINTS = tuple(FLAGSMITH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FLAGSMITH_ENDPOINTS.items()
}
