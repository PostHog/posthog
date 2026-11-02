from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.types import IncrementalField

# Which root listing a fan-out endpoint enumerates its parents from. Environments are
# discovered project-by-project, so their prerequisite is the projects listing. The rest are
# multi-level parents: identities are listed per environment; the feature-segments and version
# listings need an environment and a feature together, both enumerated per project (the versioned
# variant keeps only the environments that run v2 feature versioning, the only ones that serve a
# version listing); and the last two need three identifiers, a project plus a resource inside it
# plus an environment.
ParentResource = Literal[
    "organisation",
    "project",
    "environment",
    "identity",
    "environment_feature",
    "versioned_environment_feature",
    "project_feature_environment",
    "project_segment_environment",
]


@dataclass(frozen=True)
class FlagsmithEndpointConfig:
    name: str
    # Path under ``/api/v1``. A ``{parent}`` placeholder marks a fan-out endpoint queried
    # once per parent resource (organisation id, project id, or environment api_key), a
    # ``{child}`` placeholder the inner identifier of a two-level parent, and ``{extra}`` the
    # third identifier of a three-level one. The path may carry its own query string (e.g. the
    # environments listing filter).
    path: str
    primary_keys: list[str]
    parent: ParentResource | None = None
    # Row field the parent identifier is injected into, so a single table stays meaningful
    # (and uniquely keyed) across parents whose rows don't carry the parent id themselves.
    parent_field: str | None = None
    # Same, for the inner identifier of a two-level parent (the ``{child}`` path placeholder).
    child_field: str | None = None
    # Same, for the third identifier of a three-level parent (the ``{extra}`` path placeholder).
    extra_field: str | None = None
    # Static query params for the initial request. Only params the endpoint's OpenAPI spec
    # documents get one (page size, cursor limit, lookback window), because DRF silently
    # ignores anything else and adding one would imply support for it.
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
    # Daily evaluation counts per feature per environment, Flagsmith's headline usage metric.
    # ``environment_id`` is a required filter, so the fan-out needs the project, the feature and
    # an environment of that project together. ``period`` is a rolling window of days back from
    # now, so a sync refreshes the recent window and merge accumulates the history over time.
    # The published spec types the 200 body as a single object, but the endpoint returns the
    # series as a plain JSON array (one entry per day).
    "evaluation_data": FlagsmithEndpointConfig(
        name="evaluation_data",
        path="/projects/{parent}/features/{child}/evaluation-data/?environment_id={extra}",
        # Rows carry no id of their own. The grain is one feature/environment/day because we
        # pass no client-application or user-agent filter, so the counts arrive aggregated.
        primary_keys=["_feature_id", "_environment_id", "day"],
        parent="project_feature_environment",
        parent_field="_project_id",
        child_field="_feature_id",
        extra_field="_environment_id",
        params={"period": 30},
        partition_key="day",
    ),
    # Project-level tag lookup resolving the tag ids carried on feature rows.
    "tags": FlagsmithEndpointConfig(
        name="tags",
        path="/projects/{parent}/tags/",
        primary_keys=["id"],
        parent="project",
        parent_field="_project_id",
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
    # Version history of a feature in one environment: the state-change trail behind the current
    # feature_states rows. Only environments on v2 feature versioning serve this listing, so the
    # parent enumeration filters the rest out rather than letting them fail the sync.
    "environment_feature_versions": FlagsmithEndpointConfig(
        name="environment_feature_versions",
        path="/environments/{parent}/features/{child}/versions/",
        # Versions expose a uuid rather than an id, and it is unique across environments.
        primary_keys=["uuid"],
        parent="versioned_environment_feature",
        parent_field="_environment_id",
        child_field="_feature_id",
        params={"page_size": 100},
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
    # Which identities fall into each segment, resolved per environment because segment rules are
    # evaluated against an environment's identities. Pages with an opaque body cursor.
    "segment_members": FlagsmithEndpointConfig(
        name="segment_members",
        path="/projects/{parent}/segments/{child}/members/?environment={extra}",
        # Rows carry no id; an identity_key is unique within its environment.
        primary_keys=["_segment_id", "_environment_id", "identity_key"],
        parent="project_segment_environment",
        parent_field="_project_id",
        child_field="_segment_id",
        extra_field="_environment_id",
        params={"limit": 100},
    ),
    # Segment overrides: the join rows tying a feature to a segment within one environment. The
    # listing requires both an environment id and a feature id, so the fan-out walks every valid
    # pair within each project.
    "feature_segments": FlagsmithEndpointConfig(
        name="feature_segments",
        path="/features/feature-segments/?environment={parent}&feature={child}",
        primary_keys=["id"],
        parent="environment_feature",
        parent_field="_environment_id",
        # The response carries the segment and environment but not the feature it overrides.
        child_field="_feature_id",
    ),
    # The end users flags are evaluated against, listed per environment.
    "identities": FlagsmithEndpointConfig(
        name="identities",
        path="/environments/{parent}/identities/",
        primary_keys=["id"],
        parent="environment",
        parent_field="_environment_api_key",
        params={"page_size": 100},
    ),
    # Trait values per identity — the attributes segment rules match on. Flagsmith exposes no bulk
    # traits listing, so this costs at least one request per identity and is bounded by the shared
    # page budget on very large environments.
    "identity_traits": FlagsmithEndpointConfig(
        name="identity_traits",
        path="/environments/{parent}/identities/{child}/traits/",
        primary_keys=["id"],
        parent="identity",
        parent_field="_environment_api_key",
        child_field="_identity_id",
        partition_key="created_date",
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
    # Permission groups, resolving the group ids referenced by feature owners and permissions.
    # Each group belongs to exactly one organisation, so its id alone keys the table.
    "groups": FlagsmithEndpointConfig(
        name="groups",
        path="/organisations/{parent}/groups/",
        primary_keys=["id"],
        parent="organisation",
        parent_field="_organisation_id",
    ),
}

ENDPOINTS = tuple(FLAGSMITH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FLAGSMITH_ENDPOINTS.items()
}
