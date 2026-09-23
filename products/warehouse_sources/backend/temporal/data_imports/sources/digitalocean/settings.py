from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# DigitalOcean caps `per_page` at 200; use the max to minimize round trips against the
# 5,000 req/hour + 250 req/minute rate limits.
PAGE_SIZE = 200


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's
# fields as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class DigitalOceanEndpointConfig:
    name: str
    # Path relative to the API root (https://api.digitalocean.com). A fan-out child's path
    # carries the `{...}` placeholder its `fanout.resolve_param` binds.
    path: str
    # Key the list of records is nested under in the JSON response body
    # (e.g. `{"droplets": [...]}` → "droplets"). `"$"` for an endpoint that returns the record
    # as the response body itself rather than wrapped in a list.
    data_selector: str
    # Columns that uniquely identify a record table-wide. DigitalOcean resource ids are
    # globally unique; keyless resources (domains, tags) use their natural name/ip key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp to partition by. `None` for resources the API doesn't stamp
    # with a creation time. Never a mutable field like `updated_at`.
    partition_key: Optional[str] = None
    # Extra query params merged into every request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Response keys carrying secrets (connection URIs, passwords, env-var values, log-shipping
    # credentials). Dropped from every record before it's stored — recursively, at any depth,
    # since some live nested inside spec/deployment objects — and their presence also disables
    # HTTP sample capture for the endpoint so the raw response can't leak into HTTP samples.
    sensitive_fields: frozenset[str] = frozenset()
    # `False` keeps the endpoint's raw response out of HTTP sample capture, which records the
    # response before the resource maps run. Set it for a response that carries data belonging in
    # the warehouse table but not in a diagnostic sample bucket, such as billing identity. A
    # `sensitive_fields` entry implies it, because a secret must never reach a sample either.
    captures_http_samples: bool = True
    # Set for endpoints that hang off a parent list endpoint (invoice line items and summaries
    # are only reachable per invoice uuid). `None` for top-level endpoints.
    fanout: Optional[DependentEndpointConfig] = None
    # `False` for an endpoint that returns a single record as the response body instead of a
    # paginated list. Declared rather than inferred because the REST framework assumes a path
    # ending in its resolved id is a single entity, and `/v2/customers/my/invoices/{invoice_uuid}`
    # returns a page of invoice line items instead.
    paginated: bool = True
    # Read by the fan-out helper's `FanoutEndpointLike` protocol. No DigitalOcean endpoint takes
    # a server-side time filter, so the incremental members stay empty for every endpoint.
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# DigitalOcean's list endpoints all share the same page-based pagination
# (`links.pages.next` full URLs, `meta.total`) and none expose a server-side
# `updated_since`/`created_since` filter, so every endpoint is full-refresh only.
DIGITALOCEAN_ENDPOINTS: dict[str, DigitalOceanEndpointConfig] = {
    "droplets": DigitalOceanEndpointConfig(
        name="droplets",
        path="/v2/droplets",
        data_selector="droplets",
        partition_key="created_at",
    ),
    # `GET /v2/apps` returns full app specs whose components carry environment-variable values
    # and log-destination credentials (Datadog/Papertrail/OpenSearch). Those `envs` and
    # `log_destinations` blocks live nested inside `spec` (and the deployment spec copies), so
    # they're stripped recursively; the surrounding app/service metadata is kept.
    "apps": DigitalOceanEndpointConfig(
        name="apps",
        path="/v2/apps",
        data_selector="apps",
        partition_key="created_at",
        sensitive_fields=frozenset({"envs", "log_destinations"}),
    ),
    # Account-wide state-transition log (creates, resizes, power cycles). `/v2/droplets/{id}/actions`
    # returns the same action objects filtered to one droplet, so it adds no columns, because these
    # rows already carry `resource_id` and `resource_type`. Fanning out per droplet would also
    # multiply requests against the account rate limit.
    "actions": DigitalOceanEndpointConfig(
        name="actions",
        path="/v2/actions",
        data_selector="actions",
        partition_key="started_at",
    ),
    "kubernetes_clusters": DigitalOceanEndpointConfig(
        name="kubernetes_clusters",
        path="/v2/kubernetes/clusters",
        data_selector="kubernetes_clusters",
        partition_key="created_at",
    ),
    # `GET /v2/databases` embeds live cluster credentials (connection URIs + passwords and
    # the per-database `users` list) alongside the metadata we want. Strip those fields so
    # they never land in a queryable warehouse table.
    "databases": DigitalOceanEndpointConfig(
        name="databases",
        path="/v2/databases",
        data_selector="databases",
        partition_key="created_at",
        sensitive_fields=frozenset(
            {
                "connection",
                "private_connection",
                "standby_connection",
                "standby_private_connection",
                "users",
            }
        ),
    ),
    "volumes": DigitalOceanEndpointConfig(
        name="volumes",
        path="/v2/volumes",
        data_selector="volumes",
        partition_key="created_at",
    ),
    "snapshots": DigitalOceanEndpointConfig(
        name="snapshots",
        path="/v2/snapshots",
        data_selector="snapshots",
        partition_key="created_at",
    ),
    "load_balancers": DigitalOceanEndpointConfig(
        name="load_balancers",
        path="/v2/load_balancers",
        data_selector="load_balancers",
        partition_key="created_at",
    ),
    "projects": DigitalOceanEndpointConfig(
        name="projects",
        path="/v2/projects",
        data_selector="projects",
        partition_key="created_at",
    ),
    "vpcs": DigitalOceanEndpointConfig(
        name="vpcs",
        path="/v2/vpcs",
        data_selector="vpcs",
        partition_key="created_at",
    ),
    # User-owned images only; the unfiltered list also returns every public distribution
    # and application image, which is huge and identical for every account.
    "images": DigitalOceanEndpointConfig(
        name="images",
        path="/v2/images",
        data_selector="images",
        partition_key="created_at",
        extra_params={"private": "true"},
    ),
    "domains": DigitalOceanEndpointConfig(
        name="domains",
        path="/v2/domains",
        data_selector="domains",
        primary_keys=["name"],
    ),
    "ssh_keys": DigitalOceanEndpointConfig(
        name="ssh_keys",
        path="/v2/account/keys",
        data_selector="ssh_keys",
    ),
    "reserved_ips": DigitalOceanEndpointConfig(
        name="reserved_ips",
        path="/v2/reserved_ips",
        data_selector="reserved_ips",
        primary_keys=["ip"],
    ),
    "tags": DigitalOceanEndpointConfig(
        name="tags",
        path="/v2/tags",
        data_selector="tags",
        primary_keys=["name"],
    ),
    # Lookups that resolve the `size_slug` and `region` slugs carried by droplets, databases,
    # load balancers and volumes. Both are account-independent catalogs keyed by slug.
    "sizes": DigitalOceanEndpointConfig(
        name="sizes",
        path="/v2/sizes",
        data_selector="sizes",
        primary_keys=["slug"],
    ),
    "regions": DigitalOceanEndpointConfig(
        name="regions",
        path="/v2/regions",
        data_selector="regions",
        primary_keys=["slug"],
    ),
    "invoices": DigitalOceanEndpointConfig(
        name="invoices",
        path="/v2/customers/my/invoices",
        data_selector="invoices",
        primary_keys=["invoice_uuid"],
    ),
    # Append-only financial ledger with no natural unique key. The composite is a best-effort
    # dedup guard; the endpoint is full-refresh (replace) so it's rewritten wholesale each sync.
    "billing_history": DigitalOceanEndpointConfig(
        name="billing_history",
        path="/v2/customers/my/billing_history",
        data_selector="billing_history",
        primary_keys=["date", "type", "amount", "description"],
    ),
    # Per-resource line items behind each invoice, so spend can be attributed to the droplet,
    # database or cluster that incurred it. Line items carry no invoice reference of their own,
    # so the parent's `invoice_uuid` is projected onto every row.
    "invoice_items": DigitalOceanEndpointConfig(
        name="invoice_items",
        path="/v2/customers/my/invoices/{invoice_uuid}",
        data_selector="invoice_items",
        captures_http_samples=False,
        # Line items have no id. Like `billing_history`, this composite is a best-effort dedup
        # guard rather than a true key, because the endpoint is full-refresh and each sync
        # rewrites the whole table.
        primary_keys=[
            "invoice_uuid",
            "product",
            "resource_uuid",
            "group_description",
            "description",
            "start_time",
            "end_time",
        ],
        partition_key="start_time",
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoice_uuid",
            resolve_field="invoice_uuid",
            include_from_parent=["invoice_uuid"],
            parent_field_renames={"invoice_uuid": "invoice_uuid"},
            parent_params={"per_page": PAGE_SIZE},
            child_params={"per_page": PAGE_SIZE},
        ),
    ),
    # Invoice totals split into product charges, overages, taxes and credits, one row per
    # invoice. The endpoint returns a single object rather than a paginated list. The parent's
    # `invoice_uuid` is projected over the body's own, because the spec does not require the
    # summary body to carry it and it is this table's primary key.
    "invoice_summaries": DigitalOceanEndpointConfig(
        name="invoice_summaries",
        path="/v2/customers/my/invoices/{invoice_uuid}/summary",
        data_selector="$",
        primary_keys=["invoice_uuid"],
        paginated=False,
        captures_http_samples=False,
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoice_uuid",
            resolve_field="invoice_uuid",
            include_from_parent=["invoice_uuid"],
            parent_field_renames={"invoice_uuid": "invoice_uuid"},
            parent_params={"per_page": PAGE_SIZE},
        ),
    ),
}

ENDPOINTS = tuple(DIGITALOCEAN_ENDPOINTS.keys())

# DigitalOcean exposes no server-side timestamp filter on any list endpoint, so no endpoint
# supports genuine incremental sync. Kept for parity with the schema-building convention.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
