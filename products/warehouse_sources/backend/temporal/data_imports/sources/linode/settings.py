from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class LinodeEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Primary key columns for dedup on merge. All Linode collections expose a globally unique `id`
    # except users, which key on `username` instead.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field to partition by. Must never change once set (e.g. `created`, `date`),
    # so a row never migrates partitions. None leaves the table unpartitioned (no stable timestamp).
    partition_key: Optional[str] = None
    # The field passed to the Linode `X-Filter` header for server-side incremental sync. It must be
    # documented as filterable AND orderable on this endpoint. None means full refresh only.
    incremental_field: Optional[str] = None
    # Events are an immutable, append-only audit log capped to the last 90 days by the API, so they
    # can only ever be appended, never merged/upserted.
    append_only: bool = False
    should_sync_default: bool = True


# Linode API v4 (https://api.linode.com/v4). Every list endpoint shares the same page/page_size query
# params and the {data, page, pages, results} response envelope, so a single paginated client fits all.
#
# Incremental sync uses the JSON `X-Filter` header with the `+gte`/`+order_by`/`+order` operators on
# fields the API documents as filterable. Only `events` (by monotonic integer id) and `invoices` (by
# date) expose a genuine server-side filter; the infrastructure inventories are small and their
# created/updated timestamps are not consistently filterable, so they ship full refresh.
LINODE_ENDPOINTS: dict[str, LinodeEndpointConfig] = {
    "linodes": LinodeEndpointConfig(
        name="linodes",
        path="/linode/instances",
        partition_key="created",
        incremental_fields=[],
    ),
    "volumes": LinodeEndpointConfig(
        name="volumes",
        path="/volumes",
        partition_key="created",
        incremental_fields=[],
    ),
    "nodebalancers": LinodeEndpointConfig(
        name="nodebalancers",
        path="/nodebalancers",
        partition_key="created",
        incremental_fields=[],
    ),
    "lke_clusters": LinodeEndpointConfig(
        name="lke_clusters",
        path="/lke/clusters",
        partition_key="created",
        incremental_fields=[],
    ),
    "domains": LinodeEndpointConfig(
        name="domains",
        path="/domains",
        # Domain objects carry no creation/update timestamp, so there is nothing stable to partition on.
        incremental_fields=[],
    ),
    "users": LinodeEndpointConfig(
        name="users",
        path="/account/users",
        primary_keys=["username"],
        incremental_fields=[],
    ),
    "invoices": LinodeEndpointConfig(
        name="invoices",
        path="/account/invoices",
        partition_key="date",
        incremental_field="date",
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "payments": LinodeEndpointConfig(
        name="payments",
        path="/account/payments",
        partition_key="date",
        # Payments carry a `date`, but the API docs don't clearly mark it filterable and we couldn't
        # confirm it against the live API, so ship full refresh (the billing history is small).
        incremental_fields=[],
    ),
    "events": LinodeEndpointConfig(
        name="events",
        path="/account/events",
        partition_key="created",
        # Event ids increase monotonically, so the id `+gte` filter is the cheapest reliable cursor and
        # avoids any datetime formatting ambiguity. Events only retain 90 days upstream regardless.
        incremental_field="id",
        append_only=True,
        incremental_fields=[
            {
                "label": "id",
                "type": IncrementalFieldType.Integer,
                "field": "id",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
}

ENDPOINTS = tuple(LINODE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LINODE_ENDPOINTS.items()
}
