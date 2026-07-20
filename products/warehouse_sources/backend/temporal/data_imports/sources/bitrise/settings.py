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
# the given time), which gives an honest incremental sync on `triggered_at`. Artifacts inherit
# that filter through their parent build fan-out, keyed on the injected `build_triggered_at`.
# Apps and workflows are small listings with no server-side time filter, so they stay full refresh.
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
}

ENDPOINTS = tuple(BITRISE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BITRISE_ENDPOINTS.items() if config.incremental_fields
}
