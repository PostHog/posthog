from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BitriseEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["slug"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field to partition on (trigger time never changes once a build exists).
    partition_key: str | None = None
    should_sync_default: bool = True


# Bitrise's builds endpoint accepts a server-side `after` Unix-timestamp filter (builds run after
# the given time), which gives an honest incremental sync on `triggered_at`. The pipelines endpoint
# takes the same filter as an RFC3339 date. Artifacts inherit the builds filter through their parent
# build fan-out, keyed on the injected `build_triggered_at`. Apps, workflows, branches,
# organizations, organization members, build requests, activities and stacks have no server-side
# time filter, so they stay full refresh. Archived builds take the same `after` filter as builds, but
# their rows carry no `triggered_at` to watermark on, so they stay full refresh too.
BITRISE_ENDPOINTS: dict[str, BitriseEndpointConfig] = {
    "apps": BitriseEndpointConfig(
        name="apps",
    ),
    "builds": BitriseEndpointConfig(
        name="builds",
        # Build slugs look globally unique but Bitrise doesn't document that scope, so keep the
        # app linkage in the key.
        primary_keys=["app_slug", "slug"],
        partition_key="triggered_at",
        incremental_fields=[
            {
                "label": "triggered_at",
                "type": IncrementalFieldType.DateTime,
                "field": "triggered_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "workflows": BitriseEndpointConfig(
        name="workflows",
        # The build-workflows endpoint returns bare workflow names, unique per app only.
        primary_keys=["app_slug", "workflow"],
    ),
    "artifacts": BitriseEndpointConfig(
        name="artifacts",
        # Artifact slugs are only unique within their build.
        primary_keys=["app_slug", "build_slug", "slug"],
        partition_key="build_triggered_at",
        should_sync_default=False,
        incremental_fields=[
            {
                "label": "build_triggered_at",
                "type": IncrementalFieldType.DateTime,
                "field": "build_triggered_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "pipelines": BitriseEndpointConfig(
        name="pipelines",
        # Pipeline slugs share the build slug namespace, which Bitrise doesn't document as global.
        primary_keys=["app_slug", "slug"],
        partition_key="triggered_at",
        incremental_fields=[
            {
                "label": "triggered_at",
                "type": IncrementalFieldType.DateTime,
                "field": "triggered_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "branches": BitriseEndpointConfig(
        name="branches",
        # The branches endpoint returns bare branch names, unique per app only.
        primary_keys=["app_slug", "branch"],
    ),
    "organizations": BitriseEndpointConfig(
        name="organizations",
    ),
    "organization_members": BitriseEndpointConfig(
        name="organization_members",
        # A member slug identifies the Bitrise account, which can belong to several organizations.
        primary_keys=["org_slug", "slug"],
    ),
    "archived_builds": BitriseEndpointConfig(
        name="archived_builds",
        primary_keys=["app_slug", "slug"],
        partition_key="started_on_worker_at",
    ),
    "build_requests": BitriseEndpointConfig(
        name="build_requests",
        primary_keys=["app_slug", "slug"],
        partition_key="created_at",
    ),
    "activities": BitriseEndpointConfig(
        name="activities",
        partition_key="created_at",
        # A full refresh pages through the whole account activity history on every run.
        should_sync_default=False,
    ),
    "available_stacks": BitriseEndpointConfig(
        name="available_stacks",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(BITRISE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BITRISE_ENDPOINTS.items() if config.incremental_fields
}
