from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
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


# Reports require an explicit window. Starting before FirstPromoter existed covers an account's whole
# history; the months before its first activity just come back with zeroed metrics.
REPORTS_START_DATE = "2014-01-01T00:00:00Z"
# Monthly buckets keep a whole-history response small. The current month is partial and is
# re-read by the next full refresh.
REPORTS_GROUP_BY = "month"

# Every metric the overview and campaign reports accept in `columns[]`.
PROGRAM_REPORT_COLUMNS: tuple[str, ...] = (
    "active_customers",
    "monthly_churn",
    "clicks_count",
    "net_revenue_amount",
    "revenue_amount",
    "referrals_count",
    "customers_count",
    "sales_count",
    "refunds_count",
    "cancelled_customers_count",
    "promoter_earnings_amount",
    "non_link_customers",
    "referrals_to_customers_cr",
    "3m_epc",
    "6m_epc",
    "clicks_to_customers_cr",
    "clicks_to_referrals_cr",
    "promoter_paid_amount",
    "signups_count",
)

# The traffic sources report accepts a smaller metric set than the overview and campaign reports.
TRAFFIC_SOURCES_REPORT_COLUMNS: tuple[str, ...] = (
    "clicks_count",
    "revenue_amount",
    "promoter_earnings_amount",
    "referrals_count",
    "customers_count",
    "sales_count",
    "refunds_count",
    "cancelled_customers_count",
    "referrals_to_customers_cr",
    "clicks_to_customers_cr",
    "clicks_to_referrals_cr",
)

# A promoter deleted between the /promoters listing and its child fetch must not fail the fan-out.
_DELETED_PROMOTER_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


def base_url(api_version: str) -> str:
    return f"{FIRST_PROMOTER_HOST}/api/{api_version}/company"


@dataclass(frozen=True)
class FirstPromoterReportConfig:
    columns: tuple[str, ...]
    # Top-level response field each row is grouped by (e.g. `campaign`), or None for the
    # program-wide overview. Grouped reports nest their per-period buckets under `sub_data`.
    dimension: str | None = None


@dataclass(frozen=True)
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
    page_size: int = DEFAULT_PAGE_SIZE
    report: FirstPromoterReportConfig | None = None
    fanout: DependentEndpointConfig | None = None


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
    "promoter_referral_links": FirstPromoterEndpointConfig(
        name="promoter_referral_links",
        path="/promoters/{promoter_id}/referral_links",
        # A link's own `id` is nullable, so the url identifies it within its promoter.
        primary_key=["promoter_id", "url"],
        fanout=DependentEndpointConfig(
            parent_name="promoters",
            resolve_param="promoter_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "promoter_id"},
            parent_params={"sorting[joined_at]": "asc"},
            child_response_actions=_DELETED_PROMOTER_IGNORE,
        ),
        description="Every referral link of each promoter: the default link plus campaign and custom links with their sub-IDs.",
    ),
    "reports_overview": FirstPromoterEndpointConfig(
        name="reports_overview",
        path="/reports/overview",
        primary_key=["period"],
        report=FirstPromoterReportConfig(columns=PROGRAM_REPORT_COLUMNS),
        description="Program-wide monthly metrics: clicks, referrals, customers, revenue, earnings per click and churn.",
    ),
    "reports_campaigns": FirstPromoterEndpointConfig(
        name="reports_campaigns",
        path="/reports/campaigns",
        primary_key=["campaign_id", "period"],
        report=FirstPromoterReportConfig(columns=PROGRAM_REPORT_COLUMNS, dimension="campaign"),
        description="Monthly clicks, conversions and revenue per campaign.",
    ),
    "reports_traffic_sources": FirstPromoterEndpointConfig(
        name="reports_traffic_sources",
        path="/reports/traffic_sources",
        primary_key=["source", "period"],
        report=FirstPromoterReportConfig(columns=TRAFFIC_SOURCES_REPORT_COLUMNS, dimension="source"),
        description="Monthly traffic, conversion rates and attributed revenue per referral traffic source.",
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
