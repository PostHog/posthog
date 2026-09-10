from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class AmazonAdsReportConfig:
    """One async reporting v3 request shape: create the report, poll it, download the gzipped JSON."""

    report_type_id: str
    ad_product: str
    group_by: tuple[str, ...]
    columns: tuple[str, ...]
    # `date` is only a valid column at DAILY granularity — a SUMMARY report carries startDate/endDate.
    time_unit: str = "DAILY"
    # Amazon rejects a report whose requested range is wider than this.
    max_window_days: int = 31
    # Amazon keeps report data for this long, so a first sync cannot reach further back.
    retention_days: int = 95


@frozen
class AmazonAdsEndpointConfig:
    name: str
    # Path under the regional advertising host.
    path: str
    primary_keys: list[str]
    # Sponsored Products v3 list endpoints are POSTs with vendor media types
    # and are scoped to a profile via the Amazon-Advertising-API-Scope header.
    profile_scoped: bool = False
    media_type: Optional[str] = None
    # Key the rows live under in the response body (None = bare array).
    data_key: Optional[str] = None
    # Set for the async reporting endpoints, which build their rows from a generated file
    # rather than from a paginated list response.
    report: Optional[AmazonAdsReportConfig] = None


# Sponsored Products campaign performance, one row per campaign per day. `date` is the only
# column Amazon lets us window on, so it is the cursor too.
SP_CAMPAIGN_REPORT = AmazonAdsReportConfig(
    report_type_id="spCampaigns",
    ad_product="SPONSORED_PRODUCTS",
    group_by=("campaign",),
    columns=(
        "date",
        "campaignId",
        "campaignName",
        "campaignStatus",
        "campaignBiddingStrategy",
        "campaignBudgetAmount",
        "campaignBudgetType",
        "campaignBudgetCurrencyCode",
        "campaignRuleBasedBudgetAmount",
        "campaignApplicableBudgetRuleId",
        "campaignApplicableBudgetRuleName",
        "impressions",
        "clicks",
        "clickThroughRate",
        "cost",
        "costPerClick",
        "spend",
        "topOfSearchImpressionShare",
        "addToList",
        "qualifiedBorrows",
        "royaltyQualifiedBorrows",
        "purchases1d",
        "purchases7d",
        "purchases14d",
        "purchases30d",
        "purchasesSameSku1d",
        "purchasesSameSku7d",
        "purchasesSameSku14d",
        "purchasesSameSku30d",
        "sales1d",
        "sales7d",
        "sales14d",
        "sales30d",
        "attributedSalesSameSku1d",
        "attributedSalesSameSku7d",
        "attributedSalesSameSku14d",
        "attributedSalesSameSku30d",
        "unitsSoldClicks1d",
        "unitsSoldClicks7d",
        "unitsSoldClicks14d",
        "unitsSoldClicks30d",
        "unitsSoldSameSku1d",
        "unitsSoldSameSku7d",
        "unitsSoldSameSku14d",
        "unitsSoldSameSku30d",
        "kindleEditionNormalizedPagesRead14d",
        "kindleEditionNormalizedPagesRoyalties14d",
    ),
)

# Amazon restates a day's metrics for as long as its widest attribution window (30 days), and the
# re-read also has to span a whole report window: one window is downloaded per profile, so its rows
# are only ascending by date within a profile.
REPORT_LOOKBACK_SECONDS = 60 * 60 * 24 * (SP_CAMPAIGN_REPORT.max_window_days + 30)

REPORT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    }
]


# Entity list endpoints have no updated-since filter, so every entity stream is a full refresh.
# Performance metrics come from the async reporting API, which windows on `date`.
AMAZON_ADS_ENDPOINTS: dict[str, AmazonAdsEndpointConfig] = {
    "profiles": AmazonAdsEndpointConfig(
        name="profiles",
        path="/v2/profiles",
        primary_keys=["profileId"],
    ),
    "sp_campaigns": AmazonAdsEndpointConfig(
        name="sp_campaigns",
        path="/sp/campaigns/list",
        primary_keys=["campaignId"],
        profile_scoped=True,
        media_type="application/vnd.spCampaign.v3+json",
        data_key="campaigns",
    ),
    "sp_ad_groups": AmazonAdsEndpointConfig(
        name="sp_ad_groups",
        path="/sp/adGroups/list",
        primary_keys=["adGroupId"],
        profile_scoped=True,
        media_type="application/vnd.spAdGroup.v3+json",
        data_key="adGroups",
    ),
    # Amazon hands out a separate `globalAdId` / `globalKeywordId` / `globalTargetId` for identity
    # across marketplaces, so the plain ids below are only unique within a profile.
    "sp_product_ads": AmazonAdsEndpointConfig(
        name="sp_product_ads",
        path="/sp/productAds/list",
        primary_keys=["_profile_id", "adId"],
        profile_scoped=True,
        media_type="application/vnd.spProductAd.v3+json",
        data_key="productAds",
    ),
    "sp_keywords": AmazonAdsEndpointConfig(
        name="sp_keywords",
        path="/sp/keywords/list",
        primary_keys=["_profile_id", "keywordId"],
        profile_scoped=True,
        media_type="application/vnd.spKeyword.v3+json",
        data_key="keywords",
    ),
    "sp_targets": AmazonAdsEndpointConfig(
        name="sp_targets",
        path="/sp/targets/list",
        primary_keys=["_profile_id", "targetId"],
        profile_scoped=True,
        media_type="application/vnd.spTargetingClause.v3+json",
        data_key="targetingClauses",
    ),
    "sp_campaign_reports": AmazonAdsEndpointConfig(
        name="sp_campaign_reports",
        path="/reporting/reports",
        primary_keys=["_profile_id", "campaignId", "date"],
        profile_scoped=True,
        report=SP_CAMPAIGN_REPORT,
    ),
}

ENDPOINTS = tuple(AMAZON_ADS_ENDPOINTS.keys())
