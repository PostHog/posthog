from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class KoyebEndpointConfig:
    name: str
    # Path on https://app.koyeb.com (the canonical Koyeb API host; api.prod.koyeb.com is an alias).
    path: str
    # Key in the JSON response body that holds the list of rows (e.g. {"apps": [...]}).
    response_data_key: str
    primary_keys: list[str]
    # Stable datetime field used for datetime partitioning. Must never change after the row is
    # created (created_at / when / started_at) — an updated_at-style key would rewrite partitions
    # on every sync.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Endpoint accepts an `order` query param ("asc"/"desc"). We always request "asc" so offset
    # pagination stays stable while new rows are appended during a sync.
    supports_order: bool = False
    # Query param that lower-bounds results by time (RFC 3339). Only set where Koyeb documents a
    # genuine server-side time filter — None means full refresh for this endpoint.
    starting_time_param: Optional[str] = None
    # /v1/usages/details requires a starting_time/ending_time window on every request (they are
    # the only list params Koyeb does not mark "(Optional)" in its API spec).
    requires_time_window: bool = False
    # Endpoint rows embed a deployment `definition`, whose `env[].value` and `config_files[].content`
    # carry plaintext application secrets. Redact those before persisting so warehouse-query access
    # can't surface credentials a member can't read in Koyeb itself.
    scrub_definition_secrets: bool = False


# Every Koyeb list endpoint shares one pagination model: `limit`/`offset` query params, with the
# reply echoing `limit`/`offset` and, on most endpoints, a `has_next` boolean (some replies carry
# only `count`, so a short page is the fallback end-of-list signal). Entity ids are unique across
# the organization the API token is scoped to.
#
# Only `instances` is marked incremental: it is the one entity list with a documented server-side
# time filter (`starting_time`, which bounds the period the instance was running — a superset of
# "created after the watermark", and the merge dedupes the overlap on `id`). The event streams and
# `activities` are append-only but expose no time filter, so re-paging them is a full refresh by
# definition; the remaining config entities are small and ship as full refresh too.
KOYEB_ENDPOINTS: dict[str, KoyebEndpointConfig] = {
    "apps": KoyebEndpointConfig(
        name="apps",
        path="/v1/apps",
        response_data_key="apps",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "services": KoyebEndpointConfig(
        name="services",
        path="/v1/services",
        response_data_key="services",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "deployments": KoyebEndpointConfig(
        name="deployments",
        path="/v1/deployments",
        response_data_key="deployments",
        primary_keys=["id"],
        partition_key="created_at",
        scrub_definition_secrets=True,
    ),
    "regional_deployments": KoyebEndpointConfig(
        name="regional_deployments",
        path="/v1/regional_deployments",
        response_data_key="regional_deployments",
        primary_keys=["id"],
        partition_key="created_at",
        # Documented rows carry no definition, but scrub defensively in case a per-region rollout
        # ever echoes the deployment definition it was cut from.
        scrub_definition_secrets=True,
    ),
    "instances": KoyebEndpointConfig(
        name="instances",
        path="/v1/instances",
        response_data_key="instances",
        primary_keys=["id"],
        partition_key="created_at",
        supports_order=True,
        # `starting_time` filters instances by the period they were running, so any instance
        # created after the watermark is included; long-running instances created earlier are
        # re-fetched and deduped by the merge on `id`. We had no live credentials to probe the
        # filter with a future-date cutoff, so the paginator keeps its full termination logic
        # rather than trusting the filter alone.
        starting_time_param="starting_time",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "domains": KoyebEndpointConfig(
        name="domains",
        path="/v1/domains",
        response_data_key="domains",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    # List metadata only — Koyeb never returns secret values from the list endpoint (they require
    # a separate explicit reveal call, which this source never makes).
    "secrets": KoyebEndpointConfig(
        name="secrets",
        path="/v1/secrets",
        response_data_key="secrets",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "volumes": KoyebEndpointConfig(
        name="volumes",
        path="/v1/volumes",
        response_data_key="volumes",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "snapshots": KoyebEndpointConfig(
        name="snapshots",
        path="/v1/snapshots",
        response_data_key="snapshots",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    # No partition key: `joined_at` moves if a member is removed and re-invited, and the table is
    # tiny anyway.
    "organization_members": KoyebEndpointConfig(
        name="organization_members",
        path="/v1/organization_members",
        response_data_key="members",
        primary_keys=["id"],
    ),
    "activities": KoyebEndpointConfig(
        name="activities",
        path="/v1/activities",
        response_data_key="activities",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    "app_events": KoyebEndpointConfig(
        name="app_events",
        path="/v1/app_events",
        response_data_key="events",
        primary_keys=["id"],
        partition_key="when",
        supports_order=True,
    ),
    "service_events": KoyebEndpointConfig(
        name="service_events",
        path="/v1/service_events",
        response_data_key="events",
        primary_keys=["id"],
        partition_key="when",
        supports_order=True,
    ),
    "deployment_events": KoyebEndpointConfig(
        name="deployment_events",
        path="/v1/deployment_events",
        response_data_key="events",
        primary_keys=["id"],
        partition_key="when",
        supports_order=True,
    ),
    "instance_events": KoyebEndpointConfig(
        name="instance_events",
        path="/v1/instance_events",
        response_data_key="events",
        primary_keys=["id"],
        partition_key="when",
        supports_order=True,
    ),
    # Usage rows have no id; one row per instance run, keyed by the instance and when that run
    # started. Full refresh only: rows for still-running instances keep accruing
    # `duration_seconds`, so replacing the table each sync is the only shape that stays correct.
    "usage_details": KoyebEndpointConfig(
        name="usage_details",
        path="/v1/usages/details",
        response_data_key="usage_details",
        primary_keys=["instance_id", "started_at"],
        partition_key="started_at",
        supports_order=True,
        requires_time_window=True,
    ),
}

ENDPOINTS = tuple(KOYEB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KOYEB_ENDPOINTS.items()
}
