from typing import Any, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen


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
    # How far back a first sync reaches. Amazon keeps report data at least this long.
    retention_days: int = 95
    # Report rows carry no id, and some grouping columns can be null. When set, `_row_id` is a hash
    # of these columns, so it identifies a row together with the profile and the date.
    key_columns: tuple[str, ...] = ()


# Page size for the list endpoints that accept one. Amazon caps it per endpoint, so an endpoint
# whose ceiling is lower carries its own.
PAGE_SIZE = 500
# The unified Ads API caps an entity query at 100 results, except for targets.
ADS_API_PAGE_SIZE = 100
ADS_API_TARGET_PAGE_SIZE = 5000

# `GET /sp/budgetRules` and its campaigns caps `pageSize` at 30, and requires it on every page.
BUDGET_RULES_PAGE_SIZE = 30
# The Sponsored TV list endpoints cap `maxResults` at 100.
ST_PAGE_SIZE = 100

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
    method: str = "POST"
    page_size_key: str = "maxResults"
    next_token_key: str = "nextToken"
    next_token_response_key: Optional[str] = None
    history: bool = False
    # `/v2/profiles` query that finds the profiles this table can read. Without one, Amazon lists
    # only the profiles with view-and-edit campaign permission.
    profile_discovery_params: Optional[dict[str, str]] = None
    # False for an endpoint that refuses a page size next to a page token.
    page_size_with_token: bool = True
    # A child table read once per row of its parent table, in each profile. `path` holds a
    # `{parent_id}` placeholder, and each child row carries the parent id under `fan_out_parent_key`.
    fan_out_parent: Optional[str] = None
    fan_out_parent_key: Optional[str] = None


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


def report_endpoint(name: str, report: AmazonAdsReportConfig) -> AmazonAdsEndpointConfig:
    return AmazonAdsEndpointConfig(
        name=name,
        path="/reporting/reports",
        primary_keys=["_profile_id", "date", "_row_id"],
        profile_scoped=True,
        report=report,
    )


def sponsored_tv_list(name: str, entity: str, data_key: str, media_type: str, id_field: str) -> AmazonAdsEndpointConfig:
    return AmazonAdsEndpointConfig(
        name=name,
        path=f"/st/{entity}/list",
        primary_keys=["_profile_id", id_field],
        profile_scoped=True,
        media_type=media_type,
        data_key=data_key,
        page_size=ST_PAGE_SIZE,
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

_SP_REPORT_DIMENSIONS = (
    "date",
    "campaignId",
    "campaignName",
    "campaignStatus",
    "campaignBudgetAmount",
    "campaignBudgetType",
    "campaignBudgetCurrencyCode",
    "portfolioId",
    "adGroupId",
    "adGroupName",
)

_SP_REPORT_METRICS = (
    "impressions",
    "clicks",
    "clickThroughRate",
    "cost",
    "costPerClick",
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
    "salesOtherSku7d",
    "unitsSoldOtherSku7d",
    "acosClicks7d",
    "acosClicks14d",
    "roasClicks7d",
    "roasClicks14d",
    "kindleEditionNormalizedPagesRead14d",
    "kindleEditionNormalizedPagesRoyalties14d",
)

_SP_KEYWORD_COLUMNS = ("keywordId", "keyword", "keywordType", "keywordBid", "matchType", "targeting", "adKeywordStatus")

# Only searches that led to at least one click appear. `keywordId` holds the keyword or the
# targeting clause that matched the search.
SP_SEARCH_TERM_REPORT = AmazonAdsReportConfig(
    report_type_id="spSearchTerm",
    ad_product="SPONSORED_PRODUCTS",
    group_by=("searchTerm",),
    columns=(*_SP_REPORT_DIMENSIONS, *_SP_KEYWORD_COLUMNS, "searchTerm", *_SP_REPORT_METRICS),
    retention_days=65,
    key_columns=("campaignId", "adGroupId", "keywordId", "targeting", "searchTerm"),
)

SP_ADVERTISED_PRODUCT_REPORT = AmazonAdsReportConfig(
    report_type_id="spAdvertisedProduct",
    ad_product="SPONSORED_PRODUCTS",
    group_by=("advertiser",),
    columns=(*_SP_REPORT_DIMENSIONS, "adId", "advertisedAsin", "advertisedSku", "spend", *_SP_REPORT_METRICS),
    key_columns=("campaignId", "adGroupId", "adId", "advertisedAsin", "advertisedSku"),
)

SP_TARGETING_REPORT = AmazonAdsReportConfig(
    report_type_id="spTargeting",
    ad_product="SPONSORED_PRODUCTS",
    group_by=("targeting",),
    columns=(*_SP_REPORT_DIMENSIONS, *_SP_KEYWORD_COLUMNS, *_SP_REPORT_METRICS),
    key_columns=("campaignId", "adGroupId", "keywordId", "targeting"),
)

# Sales of products other than the advertised one, attributed to the ad that was clicked.
SP_PURCHASED_PRODUCT_REPORT = AmazonAdsReportConfig(
    report_type_id="spPurchasedProduct",
    ad_product="SPONSORED_PRODUCTS",
    group_by=("asin",),
    columns=(
        "date",
        "campaignId",
        "campaignName",
        "campaignBudgetCurrencyCode",
        "portfolioId",
        "adGroupId",
        "adGroupName",
        "keywordId",
        "keyword",
        "keywordType",
        "matchType",
        "advertisedAsin",
        "advertisedSku",
        "purchasedAsin",
        "marketplace",
        "addToList",
        "qualifiedBorrows",
        "royaltyQualifiedBorrows",
        "purchases1d",
        "purchases7d",
        "purchases14d",
        "purchases30d",
        "purchasesOtherSku1d",
        "purchasesOtherSku7d",
        "purchasesOtherSku14d",
        "purchasesOtherSku30d",
        "sales1d",
        "sales7d",
        "sales14d",
        "sales30d",
        "salesOtherSku1d",
        "salesOtherSku7d",
        "salesOtherSku14d",
        "salesOtherSku30d",
        "unitsSoldClicks1d",
        "unitsSoldClicks7d",
        "unitsSoldClicks14d",
        "unitsSoldClicks30d",
        "unitsSoldOtherSku1d",
        "unitsSoldOtherSku7d",
        "unitsSoldOtherSku14d",
        "unitsSoldOtherSku30d",
        "kindleEditionNormalizedPagesRead14d",
        "kindleEditionNormalizedPagesRoyalties14d",
    ),
    key_columns=("campaignId", "adGroupId", "keywordId", "advertisedAsin", "advertisedSku", "purchasedAsin"),
)

# Amazon keeps this report for 731 days, but a first sync reads the same 95 days as the other
# report tables, so it stays a few reports per profile.
SB_PURCHASED_PRODUCT_REPORT = AmazonAdsReportConfig(
    report_type_id="sbPurchasedProduct",
    ad_product="SPONSORED_BRANDS",
    group_by=("purchasedAsin",),
    columns=(
        "date",
        "campaignId",
        "campaignName",
        "campaignBudgetCurrencyCode",
        "campaignPriceTypeCode",
        "adGroupId",
        "adGroupName",
        "attributionType",
        "purchasedAsin",
        "productName",
        "productCategory",
        "orders14d",
        "ordersClicks14d",
        "sales14d",
        "salesClicks14d",
        "unitsSold14d",
        "unitsSoldClicks14d",
        "newToBrandPurchases14d",
        "newToBrandPurchasesPercentage14d",
        "newToBrandSales14d",
        "newToBrandSalesPercentage14d",
        "newToBrandUnitsSold14d",
        "newToBrandUnitsSoldPercentage14d",
        "kindleEditionNormalizedPagesRead14d",
        "kindleEditionNormalizedPagesRoyalties14d",
    ),
    key_columns=("campaignId", "adGroupId", "attributionType", "purchasedAsin"),
)

# Amazon restates a day's metrics for as long as its widest attribution window (30 days), and the
# re-read also has to span a whole report window: one window is downloaded per profile, so its rows
# are only ascending by date within a profile.
REPORT_LOOKBACK_SECONDS = 60 * 60 * 24 * (SP_CAMPAIGN_REPORT.max_window_days + 30)

# Amazon keeps change history for 90 days. A day less keeps a first sync inside it.
HISTORY_RETENTION_DAYS = 89
HISTORY_PAGE_SIZE = 200
# Amazon can record an event after a sync with a timestamp below that sync's cursor.
HISTORY_LOOKBACK_MS = 24 * 60 * 60 * 1000
# THEME needs the v1.1 response version, so it is left out.
HISTORY_EVENT_TYPES = ("CAMPAIGN", "AD_GROUP", "AD", "KEYWORD", "NEGATIVE_KEYWORD", "PRODUCT_TARGETING")

HISTORY_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.Integer,
        "field": "timestamp",
        "field_type": IncrementalFieldType.Integer,
    }
]

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
    "sp_negative_targets": AmazonAdsEndpointConfig(
        name="sp_negative_targets",
        path="/sp/negativeTargets/list",
        primary_keys=["_profile_id", "targetId"],
        profile_scoped=True,
        media_type="application/vnd.spNegativeTargetingClause.v3+json",
        data_key="negativeTargetingClauses",
    ),
    "sp_campaign_negative_targets": AmazonAdsEndpointConfig(
        name="sp_campaign_negative_targets",
        path="/sp/campaignNegativeTargets/list",
        primary_keys=["_profile_id", "targetId"],
        profile_scoped=True,
        media_type="application/vnd.spCampaignNegativeTargetingClause.v3+json",
        data_key="campaignNegativeTargetingClauses",
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
    "ads_accounts": AmazonAdsEndpointConfig(
        name="ads_accounts",
        path="/adsAccounts/list",
        primary_keys=["adsAccountId"],
        media_type="application/vnd.listaccountsresource.v1+json",
        data_key="adsAccounts",
        page_size=ADS_API_PAGE_SIZE,
    ),
    # Invoices are billed per profile. Their status and remaining amounts change after they are
    # issued, and the only filter is on the invoice date, so the table is a full refresh.
    "invoices": AmazonAdsEndpointConfig(
        name="invoices",
        path="/invoices",
        primary_keys=["_profile_id", "id"],
        profile_scoped=True,
        media_type="application/vnd.invoices.v1.1+json",
        data_key="invoiceSummaries",
        page_size=ADS_API_PAGE_SIZE,
        method="GET",
        page_size_key="count",
        next_token_key="cursor",
        next_token_response_key="nextCursor",
        page_size_with_token=False,
        profile_discovery_params={"apiProgram": "billing", "accessLevel": "view"},
    ),
    # A history event has no id of its own, so `_event_id` is a hash of the event.
    "change_history": AmazonAdsEndpointConfig(
        name="change_history",
        path="/history",
        primary_keys=["_profile_id", "_event_id"],
        profile_scoped=True,
        data_key="events",
        page_size=HISTORY_PAGE_SIZE,
        page_size_key="count",
        history=True,
        profile_discovery_params={"apiProgram": "campaign", "accessLevel": "view"},
    ),
    "sp_campaign_reports": AmazonAdsEndpointConfig(
        name="sp_campaign_reports",
        path="/reporting/reports",
        primary_keys=["_profile_id", "campaignId", "date"],
        profile_scoped=True,
        report=SP_CAMPAIGN_REPORT,
    ),
    "sp_search_term_reports": report_endpoint("sp_search_term_reports", SP_SEARCH_TERM_REPORT),
    "sp_advertised_product_reports": report_endpoint("sp_advertised_product_reports", SP_ADVERTISED_PRODUCT_REPORT),
    "sp_targeting_reports": report_endpoint("sp_targeting_reports", SP_TARGETING_REPORT),
    "sp_purchased_product_reports": report_endpoint("sp_purchased_product_reports", SP_PURCHASED_PRODUCT_REPORT),
    "sb_purchased_product_reports": report_endpoint("sb_purchased_product_reports", SB_PURCHASED_PRODUCT_REPORT),
    "sp_budget_rules": AmazonAdsEndpointConfig(
        name="sp_budget_rules",
        path="/sp/budgetRules",
        primary_keys=["_profile_id", "ruleId"],
        profile_scoped=True,
        data_key="budgetRulesForAdvertiserResponse",
        page_size=BUDGET_RULES_PAGE_SIZE,
        method="GET",
        page_size_key="pageSize",
    ),
    "sp_budget_rule_campaigns": AmazonAdsEndpointConfig(
        name="sp_budget_rule_campaigns",
        path="/sp/budgetRules/{parent_id}/campaigns",
        primary_keys=["_profile_id", "ruleId", "campaignId"],
        profile_scoped=True,
        data_key="associatedCampaigns",
        page_size=BUDGET_RULES_PAGE_SIZE,
        method="GET",
        page_size_key="pageSize",
        fan_out_parent="sp_budget_rules",
        fan_out_parent_key="ruleId",
    ),
    "st_campaigns": sponsored_tv_list(
        "st_campaigns", "campaigns", "campaigns", "application/vnd.stCampaign.v1+json", "campaignId"
    ),
    "st_ad_groups": sponsored_tv_list(
        "st_ad_groups", "adGroups", "adGroups", "application/vnd.stAdGroup.v1+json", "adGroupId"
    ),
    "st_ads": sponsored_tv_list("st_ads", "ads", "ads", "application/vnd.stAd.v1+json", "adId"),
    "st_targets": sponsored_tv_list(
        "st_targets", "targets", "targetingClauses", "application/vnd.stTargetingClause.v1+json", "targetId"
    ),
}

ENDPOINTS = tuple(AMAZON_ADS_ENDPOINTS.keys())
