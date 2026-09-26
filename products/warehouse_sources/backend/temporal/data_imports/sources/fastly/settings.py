from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

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
FastlyEndpointKind = Literal[
    "object",
    "service_list",
    "version_list",
    "version_resource",
    "version_resource_child",
    "billing_list",
    "billing_usage_metrics",
]


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
