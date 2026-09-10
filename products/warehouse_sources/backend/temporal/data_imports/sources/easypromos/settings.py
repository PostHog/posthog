from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class EasypromosEndpointConfig:
    name: str
    # Path under /v2. Fan-out children use a `{promotion_id}` placeholder filled per parent
    # promotion (e.g. "/users/{promotion_id}").
    path: str
    # Columns that uniquely identify a row table-wide. Fan-out children aggregate rows from every
    # promotion, so the parent `promotion_id` is part of the key — Easypromos ids (user, stage,
    # participation, ...) are only documented as unique within their promotion.
    primary_keys: list[str]
    # Stable creation-timestamp field to partition by, or None to skip partitioning. Only set where
    # the API docs reliably show a `created` field on every row; never an `updated`/`last_*` field
    # (those move and rewrite partitions every sync).
    partition_key: Optional[str] = None
    # When set, the endpoint is fetched by walking `/promotions` and calling this path once per
    # promotion, substituting the promotion id into the `{promotion_id}` placeholder. Each emitted
    # row gets `promotion_id` injected so the composite primary key is unique across promotions.
    fan_out_over_promotions: bool = False
    # Whether the table is selected for sync by default in the wizard.
    should_sync_default: bool = True
    # Easypromos exposes no server-side updated-since filter — only `order=created_asc|created_desc`
    # with no `created_gte`-style cutoff — so every endpoint is full refresh and advertises no
    # incremental fields. Kept as an explicit (empty) field for parity with other sources.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# The Easypromos REST API v2 (https://api.easypromosapp.com/v2) is hierarchical: a handful of
# account-level list endpoints, with the rest scoped to a single promotion. We model the
# promotion-scoped resources as a single-hop fan-out over `/promotions`.
#
# None of these endpoints expose a server-side timestamp filter, so all are full refresh. The
# `order` param (created_asc/created_desc) is honored but cannot bound the result set, so it only
# fixes a stable pagination order (see easypromos.py).
EASYPROMOS_ENDPOINTS: dict[str, EasypromosEndpointConfig] = {
    "promotions": EasypromosEndpointConfig(
        name="promotions",
        path="/promotions",
        primary_keys=["id"],
        partition_key="created",
    ),
    "organizing_brands": EasypromosEndpointConfig(
        name="organizing_brands",
        path="/organizing_brands",
        primary_keys=["id"],
    ),
    "stages": EasypromosEndpointConfig(
        name="stages",
        path="/stages/{promotion_id}",
        primary_keys=["promotion_id", "id"],
        fan_out_over_promotions=True,
    ),
    "users": EasypromosEndpointConfig(
        name="users",
        path="/users/{promotion_id}",
        primary_keys=["promotion_id", "id"],
        partition_key="created",
        fan_out_over_promotions=True,
    ),
    "participations": EasypromosEndpointConfig(
        name="participations",
        path="/participations/{promotion_id}",
        primary_keys=["promotion_id", "id"],
        partition_key="created",
        fan_out_over_promotions=True,
    ),
    "prizes": EasypromosEndpointConfig(
        name="prizes",
        path="/prizes/{promotion_id}",
        primary_keys=["promotion_id", "id"],
        partition_key="created",
        fan_out_over_promotions=True,
    ),
    # GetPromotionVirtualCoinTransactions. The transaction object carries an `id`; its timestamp
    # field name isn't confirmed against a live account, so no partition key until verified.
    "coin_transactions": EasypromosEndpointConfig(
        name="coin_transactions",
        path="/coins/{promotion_id}",
        primary_keys=["promotion_id", "id"],
        fan_out_over_promotions=True,
        should_sync_default=False,
    ),
    # A ranking is a leaderboard of users with scores. Keyed on the user within the promotion; the
    # exact id field isn't confirmed against a live White Label account, so this may need adjusting.
    "rankings": EasypromosEndpointConfig(
        name="rankings",
        path="/rankings/{promotion_id}",
        primary_keys=["promotion_id", "user_id"],
        fan_out_over_promotions=True,
        should_sync_default=False,
    ),
    "points_of_sale": EasypromosEndpointConfig(
        name="points_of_sale",
        path="/points_of_sale/{promotion_id}",
        primary_keys=["promotion_id", "id"],
        fan_out_over_promotions=True,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(EASYPROMOS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EASYPROMOS_ENDPOINTS.items()
}
