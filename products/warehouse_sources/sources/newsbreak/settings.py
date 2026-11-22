from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

BASE_URL = "https://business.newsbreak.com/business-api/v1"

# The list endpoints accept only 5, 10, 20, 50, 100, 200 or 500.
PAGE_SIZE = 500

# A DATE report accepts a FIXED range of at most 30 days. The report has no pagination, so short
# windows keep each response small for accounts with many ads.
REPORT_WINDOW_DAYS = 7
# Conversions are attributed back to the day of the click, so recent days change after they are
# first read. Incremental runs read this many days again by default, and the merge replaces them.
REPORT_LOOKBACK_DAYS = 14
# The first sync reads back to the creation of each ad account. This applies when the account has
# no creation time.
DEFAULT_BACKFILL_DAYS = 730
DEFAULT_TIMEZONE = "UTC"

# Every metric the synchronous report accepts. The response holds an integer and a `...Decimal`
# column for each money metric.
REPORT_METRICS = [
    "COST",
    "IMPRESSION",
    "CLICK",
    "CONVERSION",
    "VALUE",
    "CPM",
    "CPC",
    "CPA",
    "CTR",
    "CVR",
    "VPA",
    "COMPLETE_PAYMENT_ROAS",
    "SALE_ROAS",
    "APP_PURCHASE_ROAS",
    "APP_IN_APP_AD_IMPR_ROAS",
]

DATE_INCREMENTAL_FIELD: IncrementalField = {
    "label": "date",
    "type": IncrementalFieldType.Date,
    "field": "date",
    "field_type": IncrementalFieldType.Date,
}

NewsBreakEndpointKind = Literal["ad_accounts", "list", "report"]


@dataclass(frozen=True)
class NewsBreakEndpointConfig:
    name: str
    kind: NewsBreakEndpointKind
    primary_keys: list[str]
    # List endpoints: the path under BASE_URL, called once per ad account.
    path: str = ""
    # Report endpoints: the dimensions of the report, in addition to DATE.
    dimensions: list[str] = field(default_factory=list)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None


def _report(name: str, dimensions: list[str], primary_keys: list[str]) -> NewsBreakEndpointConfig:
    return NewsBreakEndpointConfig(
        name=name,
        kind="report",
        dimensions=["DATE", *dimensions],
        primary_keys=["date", *primary_keys],
        incremental_fields=[DATE_INCREMENTAL_FIELD],
        partition_key="date",
    )


NEWSBREAK_ENDPOINTS: dict[str, NewsBreakEndpointConfig] = {
    "ad_accounts": NewsBreakEndpointConfig(name="ad_accounts", kind="ad_accounts", primary_keys=["id"]),
    # The list endpoints have no filter on update time, so they sync as a full refresh.
    "campaigns": NewsBreakEndpointConfig(name="campaigns", kind="list", path="/campaign/getList", primary_keys=["id"]),
    "ad_sets": NewsBreakEndpointConfig(name="ad_sets", kind="list", path="/ad-set/getList", primary_keys=["id"]),
    "ads": NewsBreakEndpointConfig(name="ads", kind="list", path="/ad/getList", primary_keys=["id"]),
    "ad_account_daily_report": _report("ad_account_daily_report", ["AD_ACCOUNT"], ["adAccountId"]),
    "campaign_daily_report": _report(
        "campaign_daily_report", ["AD_ACCOUNT", "CAMPAIGN"], ["adAccountId", "campaignId"]
    ),
    "ad_set_daily_report": _report(
        "ad_set_daily_report", ["AD_ACCOUNT", "CAMPAIGN", "AD_SET"], ["adAccountId", "campaignId", "adSetId"]
    ),
    "ad_daily_report": _report(
        "ad_daily_report",
        ["AD_ACCOUNT", "CAMPAIGN", "AD_SET", "AD"],
        ["adAccountId", "campaignId", "adSetId", "adId"],
    ),
}

ENDPOINTS = tuple(NEWSBREAK_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NEWSBREAK_ENDPOINTS.items() if config.incremental_fields
}
