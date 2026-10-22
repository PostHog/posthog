from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

REWARDFUL_BASE_URL = "https://api.getrewardful.com/v1"

# The documented maximum; the default is 25.
PAGE_LIMIT = 100


@frozen
class RewardfulEndpointConfig:
    name: str
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    # Rewardful only filters `referrals` by `updated_since` server-side, so that is the one
    # incremental table. Every other list endpoint has no time filter and no sort parameter.
    incremental_fields: tuple[IncrementalField, ...] = ()
    partition_key: str | None = "created_at"
    params: tuple[tuple[str, str], ...] = ()
    paginated: bool = True


_UPDATED_AT: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}

REWARDFUL_ENDPOINTS: dict[str, RewardfulEndpointConfig] = {
    "affiliates": RewardfulEndpointConfig(name="affiliates", path="/affiliates"),
    "referrals": RewardfulEndpointConfig(
        name="referrals",
        path="/referrals",
        incremental_fields=(_UPDATED_AT,),
    ),
    "commissions": RewardfulEndpointConfig(
        name="commissions",
        path="/commissions",
        # The sale carries the charge, refund and tax amounts the commission was computed from.
        params=(("expand[]", "sale"),),
    ),
    "payouts": RewardfulEndpointConfig(name="payouts", path="/payouts"),
    # Rewardful documents no paging for campaigns and describes the response as a bare array.
    "campaigns": RewardfulEndpointConfig(name="campaigns", path="/campaigns", paginated=False),
    "affiliate_links": RewardfulEndpointConfig(name="affiliate_links", path="/affiliate_links", partition_key=None),
    "affiliate_coupons": RewardfulEndpointConfig(
        name="affiliate_coupons", path="/affiliate_coupons", partition_key=None
    ),
}

ENDPOINTS = tuple(REWARDFUL_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in REWARDFUL_ENDPOINTS.items()
}
