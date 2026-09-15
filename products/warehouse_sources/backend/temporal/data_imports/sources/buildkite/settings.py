from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class BuildkiteEndpointConfig:
    name: str
    # Path template. ``{organization}`` is filled with the org slug from the source config.
    # Endpoints that aren't org-scoped (e.g. /v2/organizations) carry no placeholder. A fan-out
    # child keeps its parent placeholders (``{suite_slug}``, ``{pipeline_slug}``,
    # ``{build_number}``) for the framework to bind per parent row.
    path: str
    incremental_fields: list[IncrementalField]
    # Field used to partition the Delta table. Must be STABLE (set once at creation) — never
    # ``updated_at`` style fields, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Maps an incremental field name to the Buildkite query param that filters on it server-side.
    # Only set for endpoints with a genuine server-side timestamp filter.
    incremental_param_map: Optional[dict[str, str]] = None
    # Path the credential probe hits for this endpoint. Fan-out children can't be probed directly
    # (their path needs a parent row), so they point at the listing that carries the same scope.
    probe_path: Optional[str] = None
    # Rows restate after creation, so append would materialize each re-pulled row as a duplicate.
    merge_only: bool = False
    should_sync_default: bool = True
    description: Optional[str] = None


# Buildkite v2 REST API endpoints. Most resources are nested under an organization slug, and the
# Test Engine resources live under the /v2/analytics prefix. Only the builds endpoint exposes a
# server-side timestamp filter (created_from); jobs inherit it through their parent build fan-out,
# and the rest are full refresh.
BUILDKITE_ENDPOINTS: dict[str, BuildkiteEndpointConfig] = {
    "organizations": BuildkiteEndpointConfig(
        name="organizations",
        path="/v2/organizations",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "pipelines": BuildkiteEndpointConfig(
        name="pipelines",
        path="/v2/organizations/{organization}/pipelines",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "builds": BuildkiteEndpointConfig(
        name="builds",
        path="/v2/organizations/{organization}/builds",
        partition_key="created_at",
        # The builds list returns newest-first by created_at and accepts a `created_from` filter
        # (ISO 8601). We sync incrementally by passing created_from=<watermark> and paginating the
        # bounded window newest-first. `created_at` is immutable; a build's state/finished_at mutate
        # after it first appears, so a build that finishes after newer builds have landed won't be
        # re-fetched once it drops below the watermark. Full refresh re-pulls everything.
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort_mode="desc",
        incremental_param_map={"created_at": "created_from"},
    ),
    "jobs": BuildkiteEndpointConfig(
        name="jobs",
        path="/v2/organizations/{organization}/pipelines/{pipeline_slug}/builds/{build_number}/jobs",
        # Job ids are unique organization-wide — Buildkite serves a job by id alone at
        # /v2/organizations/{org}/jobs/{job.id}, with no pipeline or build in the path.
        primary_keys=["id"],
        # Jobs carry no server-side time filter of their own, so the incremental window is applied
        # to the parent build walk and each job row carries its build's creation time as the cursor.
        # A job retried onto a build older than the watermark isn't re-fetched, the same trade-off
        # the builds endpoint already makes.
        partition_key="build_created_at",
        incremental_fields=[
            {
                "label": "build_created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "build_created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort_mode="desc",
        probe_path="/v2/organizations/{organization}/builds",
        merge_only=True,
        should_sync_default=False,
        description=(
            "Fetches the jobs of every build, at least one request per build. "
            "Disabled by default because of the API cost"
        ),
    ),
    "agents": BuildkiteEndpointConfig(
        name="agents",
        path="/v2/organizations/{organization}/agents",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "teams": BuildkiteEndpointConfig(
        name="teams",
        path="/v2/organizations/{organization}/teams",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "test_suites": BuildkiteEndpointConfig(
        name="test_suites",
        path="/v2/analytics/organizations/{organization}/suites",
        # Suites expose no creation timestamp, so there is nothing stable to partition on.
        incremental_fields=[],
    ),
    "test_suite_runs": BuildkiteEndpointConfig(
        name="test_suite_runs",
        path="/v2/analytics/organizations/{organization}/suites/{suite_slug}/runs",
        primary_keys=["suite_slug", "id"],
        partition_key="created_at",
        # Runs come back newest-first per suite and the listing takes no time filter, only build_id.
        sort_mode="desc",
        incremental_fields=[],
        probe_path="/v2/analytics/organizations/{organization}/suites",
    ),
    "test_suite_tests": BuildkiteEndpointConfig(
        name="test_suite_tests",
        path="/v2/analytics/organizations/{organization}/suites/{suite_slug}/tests",
        primary_keys=["suite_slug", "id"],
        incremental_fields=[],
        probe_path="/v2/analytics/organizations/{organization}/suites",
    ),
}

ENDPOINTS = tuple(BUILDKITE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BUILDKITE_ENDPOINTS.items()
}

MERGE_ONLY: tuple[str, ...] = tuple(name for name, config in BUILDKITE_ENDPOINTS.items() if config.merge_only)

SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    name: config.should_sync_default for name, config in BUILDKITE_ENDPOINTS.items()
}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in BUILDKITE_ENDPOINTS.items() if config.description
}
