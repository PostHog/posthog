from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How each endpoint is read:
#   single      — one GET, whole result set in `data` (no pagination params).
#   query_page  — GET with `limit`/`offset` query params.
#   find        — POST whose body *is* a Selector (`conditions`/`pagination`).
#   report      — POST a date-bounded report request; rows arrive nested under
#                 `data.reportingDataResponse.row`, one per entity with a daily
#                 `granularity` array.
EndpointKind = Literal["single", "query_page", "find", "report"]

# Apple caps `limit` (entity endpoints) and `selector.pagination.limit` (find/report) at 1000.
PAGE_SIZE = 1000

# Reporting requests are bounded to a short window so that the per-batch incremental
# watermark can never advance further ahead of the data than the trailing lookback below
# re-reads. Within one window rows arrive grouped by entity rather than by date, so the
# window length is the ordering error budget — keep it <= the lookback.
REPORT_WINDOW_DAYS = 7

# Apple restates recent reporting rows (3-4h ingestion delay plus attribution), so every
# incremental run re-reads a trailing week rather than trusting the frozen watermark.
REPORT_LOOKBACK_SECONDS = REPORT_WINDOW_DAYS * 24 * 60 * 60

# How far back the first sync of a report table reaches when the user gives no start date.
DEFAULT_INITIAL_LOOKBACK_DAYS = 365

# The earliest a configured start date may reach. Apple's Reporting API rejects a DAILY-
# granularity report (the only granularity this source requests) whose startTime is more than
# 24 months in the past with a 400 — treating a month as 30 days keeps this clamp safely inside
# that limit despite calendar-month variation.
MAX_INITIAL_LOOKBACK_DAYS = 24 * 30


@dataclass(frozen=True)
class AppleSearchAdsEndpointConfig:
    name: str
    # Path under `https://api.searchads.apple.com/api/{version}`.
    path: str
    kind: EndpointKind
    primary_keys: list[str]
    # Every Campaign Management endpoint except `/acls` is scoped to one organization via
    # the `X-AP-Context: orgId=...` header.
    requires_org_context: bool = True
    # Apple only exposes ad-group/keyword level reports per campaign, so those tables are
    # built by fanning out over the org's campaign ids.
    fan_out_over_campaigns: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Reporting date — set by Apple, never restated to a different day, so it is a stable
    # partition key.
    partition_key: Optional[str] = None


APPLE_SEARCH_ADS_ENDPOINTS: dict[str, AppleSearchAdsEndpointConfig] = {
    "acls": AppleSearchAdsEndpointConfig(
        name="acls",
        path="/acls",
        kind="single",
        primary_keys=["orgId"],
        requires_org_context=False,
    ),
    "campaigns": AppleSearchAdsEndpointConfig(
        name="campaigns",
        path="/campaigns",
        kind="query_page",
        primary_keys=["id"],
    ),
    "ad_groups": AppleSearchAdsEndpointConfig(
        name="ad_groups",
        path="/adgroups/find",
        kind="find",
        primary_keys=["id"],
    ),
    "keywords": AppleSearchAdsEndpointConfig(
        name="keywords",
        path="/targetingkeywords/find",
        kind="find",
        primary_keys=["id"],
    ),
    "campaign_report": AppleSearchAdsEndpointConfig(
        name="campaign_report",
        path="/reports/campaigns",
        kind="report",
        primary_keys=["campaignId", "date"],
        partition_key="date",
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
    ),
    "ad_group_report": AppleSearchAdsEndpointConfig(
        name="ad_group_report",
        path="/reports/campaigns/{campaign_id}/adgroups",
        kind="report",
        fan_out_over_campaigns=True,
        primary_keys=["campaignId", "adGroupId", "date"],
        partition_key="date",
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
    ),
    "keyword_report": AppleSearchAdsEndpointConfig(
        name="keyword_report",
        path="/reports/campaigns/{campaign_id}/keywords",
        kind="report",
        fan_out_over_campaigns=True,
        # Apple keyword ids are unique across ad groups, so the campaign the row was fanned
        # out from plus the keyword and date identify a row table-wide.
        primary_keys=["campaignId", "keywordId", "date"],
        partition_key="date",
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
    ),
}

ENDPOINTS = tuple(APPLE_SEARCH_ADS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPLE_SEARCH_ADS_ENDPOINTS.items()
}

REPORT_ENDPOINTS = tuple(name for name, config in APPLE_SEARCH_ADS_ENDPOINTS.items() if config.kind == "report")

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "acls": "Organizations the API credentials can read, with currency, time zone and role names.",
    "campaigns": "Campaigns in the organization, with budget, serving status and countries or regions.",
    "ad_groups": "Ad groups across every campaign in the organization, with default bid and targeting.",
    "keywords": "Targeting keywords across every ad group in the organization, with match type and bid.",
    "campaign_report": "Daily campaign performance: impressions, taps, installs, spend and derived rates.",
    "ad_group_report": "Daily ad group performance for every campaign in the organization.",
    "keyword_report": "Daily keyword performance for every campaign in the organization.",
}
