from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

LINODE_MONTHLY_TRANSFER = "linode_monthly_transfer"

# Months of history the first monthly transfer sync reads, the current month included. Each month
# costs one request per Linode, so the window stays bounded.
MONTHLY_TRANSFER_LOOKBACK_MONTHS = 12

# Max allowed page_size is 500 (min 25). Using the max minimizes request count against the 200 req/min
# paginated-GET rate limit.
PAGE_SIZE = 500


@dataclass(frozen=True)
class LinodeEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Primary key columns for dedup on merge. All Linode collections expose a globally unique `id`
    # except users, which key on `username` instead. None for full-refresh tables with no unique key.
    primary_keys: list[str] | None = field(default_factory=lambda: ["id"])
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
    # The endpoint returns one bare object instead of the paginated {data, page, pages} envelope.
    single_object: bool = False
    # Set for child resources that only exist per parent row (e.g. items under an invoice).
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE

    @property
    def default_incremental_field(self) -> str | None:
        return self.incremental_field


# Linode API v4 (https://api.linode.com/v4). Every list endpoint shares the same page/page_size query
# params and the {data, page, pages, results} response envelope, so a single paginated client fits all.
#
# Incremental sync uses the JSON `X-Filter` header with the `+gte`/`+order_by`/`+order` operators on
# fields the API documents as filterable. Only `events` (by monotonic integer id) and `invoices` (by
# date) expose a genuine server-side filter; the infrastructure inventories are small and their
# created/updated timestamps are not consistently filterable, so they ship full refresh. The monthly
# transfer table is incremental without X-Filter: the month is part of the request path.
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
    "invoice_items": LinodeEndpointConfig(
        name="invoice_items",
        path="/account/invoices/{invoice_id}/items",
        # Items carry no id, and two items on one invoice can share label, type and period, so there
        # is no unique key. Issued invoices are immutable and the set is small, so full refresh fits.
        primary_keys=None,
        partition_key="invoice_date",
        incremental_fields=[],
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoice_id",
            resolve_field="id",
            include_from_parent=["id", "date"],
            parent_field_renames={"id": "invoice_id", "date": "invoice_date"},
        ),
    ),
    "account_transfer": LinodeEndpointConfig(
        name="account_transfer",
        path="/account/transfer",
        # One row: the account's network transfer pool for the current month, replaced on every sync.
        primary_keys=None,
        single_object=True,
        incremental_fields=[],
    ),
    "linode_types": LinodeEndpointConfig(
        name="linode_types",
        path="/linode/types",
        incremental_fields=[],
    ),
    "regions": LinodeEndpointConfig(
        name="regions",
        path="/regions",
        incremental_fields=[],
    ),
    "images": LinodeEndpointConfig(
        name="images",
        path="/images",
        partition_key="created",
        incremental_fields=[],
    ),
    "databases": LinodeEndpointConfig(
        name="databases",
        path="/databases/instances",
        # The listing aggregates every engine (MySQL, PostgreSQL, Valkey), and the API does not say
        # that ids are unique across engines.
        primary_keys=["engine", "id"],
        partition_key="created",
        incremental_fields=[],
    ),
    "database_types": LinodeEndpointConfig(
        name="database_types",
        path="/databases/types",
        incremental_fields=[],
    ),
    "lke_node_pools": LinodeEndpointConfig(
        name="lke_node_pools",
        path="/lke/clusters/{cluster_id}/pools",
        primary_keys=["cluster_id", "id"],
        # Pools carry no timestamp, so there is nothing stable to partition on.
        incremental_fields=[],
        fanout=DependentEndpointConfig(
            parent_name="lke_clusters",
            resolve_param="cluster_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "cluster_id"},
        ),
    ),
    LINODE_MONTHLY_TRANSFER: LinodeEndpointConfig(
        name=LINODE_MONTHLY_TRANSFER,
        path="/linode/instances/{linode_id}/transfer/{year}/{month}",
        # One row per Linode per calendar month. The source builds `month_start` itself and walks the
        # months oldest first, so an incremental run requests only the months from the watermark on.
        primary_keys=["linode_id", "month_start"],
        partition_key="month_start",
        incremental_field="month_start",
        incremental_fields=[
            {
                "label": "month_start",
                "type": IncrementalFieldType.DateTime,
                "field": "month_start",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "volume_quotas": LinodeEndpointConfig(
        name="volume_quotas",
        path="/volumes/quotas",
        # Quotas key on a string `quota_id` (e.g. `vol-capacity-us-east`) and carry no timestamp.
        primary_keys=["quota_id"],
        incremental_fields=[],
    ),
    "volume_quota_usage": LinodeEndpointConfig(
        name="volume_quota_usage",
        path="/volumes/quotas/{quota_id}/usage",
        # One row per quota: the current usage against its limit, replaced on every sync.
        primary_keys=["quota_id"],
        single_object=True,
        incremental_fields=[],
        fanout=DependentEndpointConfig(
            parent_name="volume_quotas",
            resolve_param="quota_id",
            resolve_field="quota_id",
            include_from_parent=["quota_id"],
            parent_field_renames={"quota_id": "quota_id"},
            # The usage request takes no page params, so the listing's page size is set here instead.
            parent_params={"page_size": PAGE_SIZE},
            # Quotas with `has_usage` false return 404 for their usage.
            child_response_actions=[{"status_code": 404, "action": "ignore", "message": None}],
        ),
    ),
}

ENDPOINTS = tuple(LINODE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LINODE_ENDPOINTS.items()
}
