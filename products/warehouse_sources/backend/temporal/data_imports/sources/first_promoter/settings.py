from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

FIRST_PROMOTER_HOST = "https://api.firstpromoter.com"

# The Admin API's maximum `per_page`. Requesting less just costs more round trips against the
# 400 requests/minute per-account budget.
DEFAULT_PAGE_SIZE = 100

# A commission's `status` (pending -> approved/denied), `is_paid` and payout linkage all change
# after the row is created, but the only server-side time filter is on `created_at`. Re-read a
# trailing month on every incremental run so those transitions land; the merge dedupes on `id`.
# Users whose approval window is longer can raise it in the schema's sync settings.
COMMISSIONS_INCREMENTAL_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


def base_url(api_version: str) -> str:
    return f"{FIRST_PROMOTER_HOST}/api/{api_version}/company"


@dataclass
class FirstPromoterEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    # Only /promoters wraps its rows in `{"data": [...], "meta": {...}}`; every other Admin API
    # list endpoint returns a bare JSON array.
    data_selector: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Bracket-nested server-side filter that carries the incremental watermark, e.g.
    # `filters[created_at][from]`.
    incremental_start_param: str | None = None
    partition_key: str | None = None
    # Merged into every request. Used for the documented `sorting[<field>]` params, which keep
    # page boundaries stable while rows are inserted mid-sync.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Response fields stripped from every row before storage because they are credentials, not
    # data - a warehouse table is the wrong place for them and any project member with query
    # access could read one.
    redact_fields: tuple[str, ...] = ()
    description: str | None = None


FIRST_PROMOTER_ENDPOINTS: dict[str, FirstPromoterEndpointConfig] = {
    "commissions": FirstPromoterEndpointConfig(
        name="commissions",
        path="/commissions",
        primary_key=["id"],
        incremental_fields=[incremental_field("created_at")],
        default_incremental_field="created_at",
        incremental_start_param="filters[created_at][from]",
        partition_key="created_at",
        extra_params={"sorting[created_at]": "asc"},
        description="Commissions earned by promoters, including sale amount, payout status and fraud checks.",
    ),
    "payouts": FirstPromoterEndpointConfig(
        name="payouts",
        path="/payouts",
        primary_key=["id"],
        partition_key="created_at",
        extra_params={"sorting[period_start]": "asc"},
        # Full refresh: the only date filters are on the payout period, not on creation, and a
        # payout's status walks pending -> processing -> completed/failed long after it exists.
        description="Payouts owed to or already paid to promoters, grouped by payout period.",
    ),
    "promo_codes": FirstPromoterEndpointConfig(
        name="promo_codes",
        path="/promo_codes",
        primary_key=["id"],
        description="Promo/coupon codes attached to promoter campaigns.",
    ),
    "promoter_campaigns": FirstPromoterEndpointConfig(
        name="promoter_campaigns",
        path="/promoter_campaigns",
        primary_key=["id"],
        partition_key="created_at",
        description="A promoter's participation in one campaign, with its referral link, coupon and stats.",
    ),
    "promoters": FirstPromoterEndpointConfig(
        name="promoters",
        path="/promoters",
        primary_key=["id"],
        data_selector="data",
        partition_key="joined_at",
        extra_params={"sorting[joined_at]": "asc"},
        # A promoter row carries `password_setup_url`, a link that sets that promoter's dashboard
        # password. It's a live credential, not analytics data, so it never reaches a table.
        redact_fields=("password_setup_url",),
        # Full refresh: `filters[joined_at][from]` exists, but every interesting field on a
        # promoter (stats, balances, state, last_login_at) keeps moving after they join, so a
        # joined_at cursor would freeze them at their first-imported values.
        description="Affiliates and referral partners, with their profile, campaign stats and balances.",
    ),
    "referrals": FirstPromoterEndpointConfig(
        name="referrals",
        path="/referrals",
        primary_key=["id"],
        partition_key="created_at",
        # Full refresh: `filters[created_at][from]` exists, but this endpoint documents no
        # `sorting` param, so row order can't be pinned, and a referral's `state` changes for as
        # long as the customer is around.
        description="Leads and customers referred by promoters, with their state and attribution.",
    ),
}

ENDPOINTS = tuple(FIRST_PROMOTER_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FIRST_PROMOTER_ENDPOINTS.items()
}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in FIRST_PROMOTER_ENDPOINTS.items() if config.description
}

INCREMENTAL_LOOKBACK_SECONDS: dict[str, int] = {
    "commissions": COMMISSIONS_INCREMENTAL_LOOKBACK_SECONDS,
}
