from dataclasses import dataclass, field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Apple's Campaign Management API 5, which Apple sunsets on 2027-01-26.
APPLE_SEARCH_ADS_API_VERSION_V5 = "v5"
# Apple Ads Platform API 1.0, which supersedes it and also covers Apple Maps advertising.
APPLE_ADS_API_VERSION_V1 = "v1"

# How each endpoint is read:
#   single      — one GET, whole result set in `data` (no pagination params).
#   query_page  — GET with `limit`/`offset` query params.
#   find        — POST whose body *is* a Selector (`conditions`/`pagination`).
#   report      — POST a date-bounded report request; rows arrive one per entity with a daily
#                 metric array to flatten.
#   acls        — one GET, ad accounts nested under `result.acls`.
#   query       — POST a `QueryRequest` (`filters`/`sorting`/`pagination`), rows in `result`.
# `single`, `query_page` and `find` are v5 only; `acls` and `query` are v1 only.
EndpointKind = Literal["single", "query_page", "find", "report", "acls", "query"]

# v5 caps `limit` at 1000; the Platform API caps `pageSize` at 5000. One page size stays under
# both.
PAGE_SIZE = 1000

# Reporting requests are bounded to a short window so that the per-batch incremental
# watermark can never advance further ahead of the data than the trailing lookback below
# re-reads. Within one window rows arrive grouped by entity rather than by date, so the
# window length is the ordering error budget — keep it <= the lookback.
REPORT_WINDOW_DAYS = 7

# Apple restates recent reporting rows (3-4h ingestion delay plus attribution), so every
# incremental run re-reads a trailing week rather than trusting the frozen watermark.
REPORT_LOOKBACK_SECONDS = REPORT_WINDOW_DAYS * 24 * 60 * 60

# How far back the first sync of a report table reaches when the user gives no start date,
# before the version's own ceiling clamps it.
DEFAULT_INITIAL_LOOKBACK_DAYS = 365


# Apple evaluates a report's date range in the ad account's own reporting time zone, while this
# source counts days in UTC. An account ahead of UTC can already be on the next day, so a floor
# that landed exactly on Apple's boundary would be one day too old for part of every UTC day.
_REPORT_TIME_ZONE_SKEW_DAYS = 2


@frozen
class ReportingLimits:
    """Bounds Apple enforces on a DAILY-granularity report request, per API version."""

    # Oldest day a request may start at, counted back from today in UTC.
    max_lookback_days: int
    # Shortest range a request may cover. The Platform API rejects a DAILY range of a single
    # day, which v5 accepted.
    min_window_days: int


REPORTING_LIMITS: dict[str, ReportingLimits] = {
    # v5 rejects a DAILY range starting more than 24 months back. Treating a month as 30 days
    # keeps the clamp inside that limit despite calendar-month variation.
    APPLE_SEARCH_ADS_API_VERSION_V5: ReportingLimits(
        max_lookback_days=24 * 30 - _REPORT_TIME_ZONE_SKEW_DAYS, min_window_days=1
    ),
    # The Platform API rejects a DAILY range starting more than 90 days back.
    APPLE_ADS_API_VERSION_V1: ReportingLimits(max_lookback_days=90 - _REPORT_TIME_ZONE_SKEW_DAYS, min_window_days=2),
}


@dataclass(frozen=True)
class AppleSearchAdsEndpointConfig:
    name: str
    # Path under the version's base URL.
    path: str
    kind: EndpointKind
    primary_keys: list[str]
    # Every endpoint except the ACL lookup is scoped to one organization (v5) or one ad
    # account (Platform API) through the `X-AP-Context` header.
    requires_context: bool = True
    # Endpoints Apple only serves per campaign, built by fanning out over the account's
    # campaign ids. v5 takes the campaign in the path; the Platform API takes it as a filter,
    # and additionally requires one on every report and on the keyword query.
    fan_out_over_campaigns: bool = False
    # Column the Platform API's `metadata.id` is projected onto, so a report table keeps the
    # primary key it had under v5.
    entity_id_field: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Reporting date — set by Apple, never restated to a different day, so it is a stable
    # partition key.
    partition_key: Optional[str] = None


_REPORT_INCREMENTAL_FIELDS = [incremental_field("date", IncrementalFieldType.Date)]

APPLE_SEARCH_ADS_ENDPOINTS: dict[str, AppleSearchAdsEndpointConfig] = {
    "acls": AppleSearchAdsEndpointConfig(
        name="acls",
        path="/acls",
        kind="single",
        primary_keys=["orgId"],
        requires_context=False,
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
        incremental_fields=_REPORT_INCREMENTAL_FIELDS,
    ),
    "ad_group_report": AppleSearchAdsEndpointConfig(
        name="ad_group_report",
        path="/reports/campaigns/{campaign_id}/adgroups",
        kind="report",
        fan_out_over_campaigns=True,
        primary_keys=["campaignId", "adGroupId", "date"],
        partition_key="date",
        incremental_fields=_REPORT_INCREMENTAL_FIELDS,
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
        incremental_fields=_REPORT_INCREMENTAL_FIELDS,
    ),
}

# The Platform API serves the same seven tables, so a repinned source keeps its table names,
# primary keys and incremental fields. It reads them differently: every collection moved to a
# `POST .../query` body, the report paths carry the entity level instead of the campaign id,
# and each report row names its own entity `id` rather than `campaignId`/`adGroupId`/
# `keywordId`.
APPLE_ADS_PLATFORM_ENDPOINTS: dict[str, AppleSearchAdsEndpointConfig] = {
    "acls": AppleSearchAdsEndpointConfig(
        name="acls",
        path="/acls",
        kind="acls",
        # One row per ad account rather than per organization: an access token binds to a
        # single org, so every row repeats the same `orgId` and only `id` identifies one.
        primary_keys=["id"],
        requires_context=False,
    ),
    "campaigns": AppleSearchAdsEndpointConfig(
        name="campaigns",
        path="/campaigns/query",
        kind="query",
        primary_keys=["id"],
    ),
    "ad_groups": AppleSearchAdsEndpointConfig(
        name="ad_groups",
        path="/adgroups/query",
        kind="query",
        primary_keys=["id"],
    ),
    "keywords": AppleSearchAdsEndpointConfig(
        name="keywords",
        path="/keywords/query",
        kind="query",
        # Apple rejects a keyword query that scopes neither a campaign nor an ad group, so
        # this table is built per campaign even though it is not a report.
        fan_out_over_campaigns=True,
        primary_keys=["id"],
    ),
    "campaign_report": AppleSearchAdsEndpointConfig(
        name="campaign_report",
        path="/reports/apps/campaigns/query",
        kind="report",
        # Apple requires a `campaignId` filter on every apps report, including this one, which
        # v5 served for the whole organization in a single request.
        fan_out_over_campaigns=True,
        entity_id_field="campaignId",
        primary_keys=["campaignId", "date"],
        partition_key="date",
        incremental_fields=_REPORT_INCREMENTAL_FIELDS,
    ),
    "ad_group_report": AppleSearchAdsEndpointConfig(
        name="ad_group_report",
        path="/reports/apps/adgroups/query",
        kind="report",
        fan_out_over_campaigns=True,
        entity_id_field="adGroupId",
        primary_keys=["campaignId", "adGroupId", "date"],
        partition_key="date",
        incremental_fields=_REPORT_INCREMENTAL_FIELDS,
    ),
    "keyword_report": AppleSearchAdsEndpointConfig(
        name="keyword_report",
        path="/reports/apps/keywords/query",
        kind="report",
        fan_out_over_campaigns=True,
        entity_id_field="keywordId",
        primary_keys=["campaignId", "keywordId", "date"],
        partition_key="date",
        incremental_fields=_REPORT_INCREMENTAL_FIELDS,
    ),
}

ENDPOINTS_BY_VERSION: dict[str, dict[str, AppleSearchAdsEndpointConfig]] = {
    APPLE_SEARCH_ADS_API_VERSION_V5: APPLE_SEARCH_ADS_ENDPOINTS,
    APPLE_ADS_API_VERSION_V1: APPLE_ADS_PLATFORM_ENDPOINTS,
}


def endpoints_for_version(api_version: str) -> dict[str, AppleSearchAdsEndpointConfig]:
    """Endpoint catalog for a resolved version pin.

    Raising beats falling back: a version this source declares but has no catalog for would
    otherwise sync silently against the wrong wire.
    """
    try:
        return ENDPOINTS_BY_VERSION[api_version]
    except KeyError:
        raise ValueError(f"Apple Ads: no endpoint catalog for API version {api_version!r}")


def reporting_limits_for_version(api_version: str) -> ReportingLimits:
    try:
        return REPORTING_LIMITS[api_version]
    except KeyError:
        raise ValueError(f"Apple Ads: no reporting limits for API version {api_version!r}")


# The table set is identical across versions by design, so discovery does not depend on the
# pin and a repinned source keeps every table it had.
ENDPOINTS = tuple(APPLE_SEARCH_ADS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPLE_SEARCH_ADS_ENDPOINTS.items()
}

REPORT_ENDPOINTS = tuple(name for name, config in APPLE_SEARCH_ADS_ENDPOINTS.items() if config.kind == "report")

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "acls": "Ad accounts the API credentials can read, with the organization and role names.",
    "campaigns": "Campaigns in the account, with budget, serving status and countries or regions.",
    "ad_groups": "Ad groups across every campaign in the account, with default bid and targeting.",
    "keywords": "Targeting keywords across every ad group in the account, with match type and bid.",
    "campaign_report": "Daily campaign performance: impressions, taps, installs, spend and derived rates.",
    "ad_group_report": "Daily ad group performance for every campaign in the account.",
    "keyword_report": "Daily keyword performance for every campaign in the account.",
}
