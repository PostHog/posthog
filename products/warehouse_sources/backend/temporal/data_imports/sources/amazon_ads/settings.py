from typing import Any, Optional

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


# Page size for the list endpoints that accept one. Amazon caps it per endpoint, so an endpoint
# whose ceiling is lower carries its own.
PAGE_SIZE = 500
# The unified Ads API caps an entity query at 100 results, except for targets.
ADS_API_PAGE_SIZE = 100
ADS_API_TARGET_PAGE_SIZE = 5000

SPONSORED_BRANDS = "SPONSORED_BRANDS"
SPONSORED_DISPLAY = "SPONSORED_DISPLAY"


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
    # `maxResults` to send with each list request. None omits it, for an endpoint whose request
    # schema declares no such field.
    page_size: Optional[int] = PAGE_SIZE
    # Request body fields every page of this endpoint repeats, such as the ad product a unified
    # Ads API query selects on.
    filters: Optional[dict[str, Any]] = None
    # The unified Ads API (`/adsApi/v1/query/...`) serves the Sponsored Brands and Sponsored
    # Display entities. It takes plain JSON, and it reads the client id from its own header.
    ads_api: bool = False


def ads_api_query(
    name: str, entity: str, ad_product: str, id_field: str, page_size: int = ADS_API_PAGE_SIZE
) -> AmazonAdsEndpointConfig:
    """One unified Ads API entity query. Sponsored Brands and Sponsored Display share the paths,
    so the ad product filter is what selects between them."""
    return AmazonAdsEndpointConfig(
        name=name,
        path=f"/adsApi/v1/query/{entity}",
        primary_keys=["_profile_id", id_field],
        profile_scoped=True,
        data_key=entity,
        page_size=page_size,
        filters={"adProductFilter": {"include": [ad_product]}},
        ads_api=True,
    )


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
    "sp_negative_keywords": AmazonAdsEndpointConfig(
        name="sp_negative_keywords",
        path="/sp/negativeKeywords/list",
        primary_keys=["_profile_id", "keywordId"],
        profile_scoped=True,
        media_type="application/vnd.spNegativeKeyword.v3+json",
        data_key="negativeKeywords",
    ),
    "sp_campaign_negative_keywords": AmazonAdsEndpointConfig(
        name="sp_campaign_negative_keywords",
        path="/sp/campaignNegativeKeywords/list",
        primary_keys=["_profile_id", "keywordId"],
        profile_scoped=True,
        media_type="application/vnd.spCampaignNegativeKeyword.v3+json",
        data_key="campaignNegativeKeywords",
    ),
    # Portfolios sit above campaigns and resolve the portfolioId the campaign tables carry.
    # Their list request schema has no `maxResults`, so none is sent.
    "portfolios": AmazonAdsEndpointConfig(
        name="portfolios",
        path="/portfolios/list",
        primary_keys=["_profile_id", "portfolioId"],
        profile_scoped=True,
        media_type="application/vnd.spPortfolio.v3+json",
        data_key="portfolios",
        page_size=None,
    ),
    "sb_campaigns": ads_api_query("sb_campaigns", "campaigns", SPONSORED_BRANDS, "campaignId"),
    "sb_ad_groups": ads_api_query("sb_ad_groups", "adGroups", SPONSORED_BRANDS, "adGroupId"),
    "sb_ads": ads_api_query("sb_ads", "ads", SPONSORED_BRANDS, "adId"),
    "sb_targets": ads_api_query(
        "sb_targets", "targets", SPONSORED_BRANDS, "targetId", page_size=ADS_API_TARGET_PAGE_SIZE
    ),
    "sd_campaigns": ads_api_query("sd_campaigns", "campaigns", SPONSORED_DISPLAY, "campaignId"),
    "sd_ad_groups": ads_api_query("sd_ad_groups", "adGroups", SPONSORED_DISPLAY, "adGroupId"),
    "sd_ads": ads_api_query("sd_ads", "ads", SPONSORED_DISPLAY, "adId"),
    "sd_targets": ads_api_query(
        "sd_targets", "targets", SPONSORED_DISPLAY, "targetId", page_size=ADS_API_TARGET_PAGE_SIZE
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
