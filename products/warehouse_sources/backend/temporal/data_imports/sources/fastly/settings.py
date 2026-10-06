from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How each Fastly endpoint is fetched:
# - "object":           GET returns a single object (e.g. /current_user).
# - "service_list":     GET /service returns a page-paginated array (Link header for next page).
# - "version_list":     fan out over every service, list that service's versions.
# - "version_resource": fan out over every service, fetch a resource scoped to the service's
#                       currently-active version (domains, backends, ACLs, dictionaries).
# - "version_resource_child": as above, then fan out again over each returned resource to list its
#                       versionless members (ACL entries, dictionary items).
# - "billing_list":     GET a /billing/v3 collection; rows sit under `data` and the next page is an
#                       opaque cursor rather than a Link header.
# - "billing_usage_metrics": as "billing_list", but each page groups per-service rows under a usage
#                       type, so the transport flattens them.
# - "plain_list":       GET returns an unpaginated array (e.g. /datacenters).
# - "json_api_list":    GET a JSON:API collection; rows sit under `data` with their fields split
#                       across `attributes` and `relationships`, and the next page is a body link.
# - "stats_list":       GET /stats returns one array of time buckets per service, keyed by service id.
# - "origin_inspector": fan out over every service, reading its origin metrics timeseries.
FastlyEndpointKind = Literal[
    "object",
    "service_list",
    "version_list",
    "version_resource",
    "version_resource_child",
    "billing_list",
    "billing_usage_metrics",
    "plain_list",
    "json_api_list",
    "stats_list",
    "origin_inspector",
]

# Fastly reports both metrics families in whole time buckets keyed by their start. The cursor is the
# bucket start as a Unix timestamp, which is also what the `from` / `start` request params take, so a
# watermark feeds straight back into the next sync with no reformatting.
_BUCKET_START_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "Bucket start",
        "type": IncrementalFieldType.DateTime,
        "field": "start_time",
        "field_type": IncrementalFieldType.Integer,
    },
]

# Fastly revises recently reported metrics, so each incremental run re-reads a trailing window
# rather than freezing a bucket at the value it first had.
METRICS_LOOKBACK_SECONDS = 3 * 24 * 60 * 60


@frozen
class FastlyEndpointConfig:
    name: str
    path: str
    kind: FastlyEndpointKind
    # Partition on a STABLE creation timestamp so partitions aren't rewritten every sync.
    partition_key: str | None = "created_at"
    should_sync_default: bool = True
    description: str | None = None
    # Unique across the whole table. Fan-out children aggregate rows from every parent, so the
    # key includes the parent (service) identifier unless the resource id is globally unique.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # "version_resource_child" only: the version-scoped endpoint listing the parents of `path`, and
    # the column on a child row that holds its parent's id.
    parent_path: str | None = None
    parent_key: str | None = None
    # "version_resource_child" only: a truthy field on a parent row that means its members cannot be
    # listed, so the transport must not request them.
    skip_parent_flag: str | None = None
    # Empty means the endpoint has no server-side timestamp filter, so it is full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    incremental_lookback_seconds: int | None = None


# Version-scoped resource paths carry `{service_id}` and `{version}` placeholders that the
# transport formats with the service id and its active version number.
FASTLY_ENDPOINTS: dict[str, FastlyEndpointConfig] = {
    "current_user": FastlyEndpointConfig(
        name="current_user",
        path="/current_user",
        kind="object",
        primary_keys=["id"],
        description="The user whose API token authenticates this connection.",
    ),
    "services": FastlyEndpointConfig(
        name="services",
        path="/service",
        kind="service_list",
        primary_keys=["id"],
        description="Every Fastly service in the account.",
    ),
    "service_versions": FastlyEndpointConfig(
        name="service_versions",
        path="/service/{service_id}/version",
        kind="version_list",
        primary_keys=["service_id", "number"],
        description="All configuration versions for each service.",
    ),
    "service_domains": FastlyEndpointConfig(
        name="service_domains",
        path="/service/{service_id}/version/{version}/domain",
        kind="version_resource",
        primary_keys=["service_id", "version", "name"],
        description="Domains attached to each service's active version.",
    ),
    "service_backends": FastlyEndpointConfig(
        name="service_backends",
        path="/service/{service_id}/version/{version}/backend",
        kind="version_resource",
        primary_keys=["service_id", "version", "name"],
        description="Origin backends configured on each service's active version.",
    ),
    "service_acls": FastlyEndpointConfig(
        name="service_acls",
        path="/service/{service_id}/version/{version}/acl",
        kind="version_resource",
        # ACL ids are globally unique; the service id is kept in the key defensively.
        primary_keys=["service_id", "id"],
        description="Access control lists on each service's active version.",
    ),
    "service_dictionaries": FastlyEndpointConfig(
        name="service_dictionaries",
        path="/service/{service_id}/version/{version}/dictionary",
        kind="version_resource",
        # Dictionary ids are globally unique; the service id is kept in the key defensively.
        primary_keys=["service_id", "id"],
        description="Edge dictionaries on each service's active version.",
    ),
    "acl_entries": FastlyEndpointConfig(
        name="acl_entries",
        path="/service/{service_id}/acl/{parent_id}/entries",
        kind="version_resource_child",
        parent_path="/service/{service_id}/version/{version}/acl",
        parent_key="acl_id",
        primary_keys=["service_id", "acl_id", "id"],
        description="The IP addresses and subnet ranges held in each service's ACLs.",
    ),
    "dictionary_items": FastlyEndpointConfig(
        name="dictionary_items",
        path="/service/{service_id}/dictionary/{parent_id}/items",
        kind="version_resource_child",
        parent_path="/service/{service_id}/version/{version}/dictionary",
        parent_key="dictionary_id",
        # Fastly refuses to list the items of a write-only dictionary.
        skip_parent_flag="write_only",
        # A dictionary item has no id of its own; its key is unique within its dictionary.
        primary_keys=["service_id", "dictionary_id", "item_key"],
        description="The key/value rows held in each service's edge dictionaries.",
    ),
    "historical_stats": FastlyEndpointConfig(
        name="historical_stats",
        path="/stats",
        kind="stats_list",
        partition_key="start_time",
        primary_keys=["service_id", "start_time"],
        incremental_fields=_BUCKET_START_INCREMENTAL_FIELDS,
        incremental_lookback_seconds=METRICS_LOOKBACK_SECONDS,
        description="Daily traffic, cache hit ratio, bandwidth and error counts for every service.",
    ),
    "origin_inspector": FastlyEndpointConfig(
        name="origin_inspector",
        path="/metrics/origins/services/{service_id}",
        kind="origin_inspector",
        partition_key="start_time",
        primary_keys=["service_id", "host", "start_time"],
        incremental_fields=_BUCKET_START_INCREMENTAL_FIELDS,
        incremental_lookback_seconds=METRICS_LOOKBACK_SECONDS,
        # Origin Inspector is a paid upgrade enabled per service, so most accounts have it on no
        # service and would sync an empty table.
        should_sync_default=False,
        description="Daily origin latency, status code and byte counts per origin host, for services with Origin Inspector enabled.",
    ),
    "service_authorizations": FastlyEndpointConfig(
        name="service_authorizations",
        path="/service-authorizations",
        kind="json_api_list",
        primary_keys=["id"],
        description="Which users can reach which services, and the permission each one holds.",
    ),
    "pops": FastlyEndpointConfig(
        name="pops",
        path="/datacenters",
        kind="plain_list",
        # A POP carries no timestamp, and the list is small enough that one partition is right.
        partition_key=None,
        primary_keys=["code"],
        description="Every Fastly POP, with the datacenter codes used in stats and origin metrics.",
    ),
    "invoices": FastlyEndpointConfig(
        name="invoices",
        path="/billing/v3/invoices",
        kind="billing_list",
        partition_key="billing_start_date",
        primary_keys=["invoice_id"],
        description="Posted invoices for the account, with the line items billed on each.",
    ),
    "billing_usage_metrics": FastlyEndpointConfig(
        name="billing_usage_metrics",
        path="/billing/v3/service-usage-metrics",
        kind="billing_usage_metrics",
        partition_key="start_time",
        primary_keys=["customer_id", "start_time", "usage_type", "service_id"],
        description="Usage per product and service over the most recent billing months.",
    ),
}

ENDPOINTS = tuple(FASTLY_ENDPOINTS.keys())
