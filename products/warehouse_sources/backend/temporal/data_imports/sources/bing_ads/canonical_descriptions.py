"""Canonical, documentation-sourced descriptions for Bing Ads (Microsoft Advertising) endpoints and columns.

Sourced from the official Microsoft Advertising API reference
(https://learn.microsoft.com/en-us/advertising/guides/). Keyed by the resource names in `schemas.py`
`RESOURCE_SCHEMAS`, which match the `ExternalDataSchema.name` of a synced Bing Ads table. Columns
absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Performance-report metrics shared by the campaign/ad-group/ad reports. Keyed by the normalized
# (snake_case) column names the pipeline writes to `DataWarehouseTable.columns`.
_REPORT_METRICS = {
    "account_name": "Name of the Microsoft Advertising account.",
    "campaign_id": "Identifier of the campaign the row belongs to.",
    "campaign_name": "Name of the campaign the row belongs to.",
    "time_period": "Date the aggregated metrics apply to.",
    "currency_code": "Three-letter ISO currency code for the monetary metrics.",
    "impressions": "Number of times the ad was shown.",
    "clicks": "Number of clicks the ad received.",
    "ctr": "Click-through rate — clicks divided by impressions.",
    "spend": "Total amount spent over the period.",
    "average_cpc": "Average cost per click.",
    "average_cpm": "Average cost per thousand impressions.",
    "conversions": "Number of conversions attributed over the period.",
    "conversion_rate": "Conversions divided by clicks.",
    "cost_per_conversion": "Average cost per conversion.",
    "revenue": "Revenue attributed to the ads over the period.",
    "return_on_ad_spend": "Return on ad spend — revenue divided by spend.",
    "assists": "Number of conversions the ad assisted but did not directly drive.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A Microsoft Advertising campaign — a container for ad groups, budget, and targeting settings.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/campaign-management-service/campaign",
        "columns": {
            "id": "Unique identifier of the campaign.",
            "name": "Name of the campaign.",
            "status": "Campaign status (e.g. Active, Paused, BudgetPaused).",
            "campaign_type": "Type of campaign (e.g. Search, Shopping, DynamicSearchAds, Audience).",
            "budget_type": "How the budget is applied (e.g. DailyBudgetStandard, DailyBudgetAccelerated).",
            "daily_budget": "Daily spending limit for the campaign.",
            "time_zone": "Time zone the campaign's schedule and reporting use.",
            "languages": "Languages the campaign targets.",
            "audience_ads_bid_adjustment": "Percentage bid adjustment applied to audience ads.",
        },
    },
    "campaign_performance_report": {
        "description": "Daily performance metrics for campaigns — impressions, clicks, spend, and conversions.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/reporting-service/campaignperformancereportrequest",
        "columns": {
            **_REPORT_METRICS,
            "absolute_top_impression_share_percent": "Percentage of impressions shown in the very top position.",
            "top_impression_share_percent": "Percentage of impressions shown in a top position above search results.",
            "impression_share_percent": "Share of impressions received out of those the ad was eligible for.",
            "impression_lost_to_budget_percent": "Share of impressions lost because of insufficient budget.",
            "impression_lost_to_rank_agg_percent": "Share of impressions lost because of ad rank.",
            "quality_score": "Microsoft's measure of how competitive the campaign's ads are.",
            "expected_ctr": "Expected click-through rate component of quality score.",
            "ad_relevance": "Ad relevance component of quality score.",
            "landing_page_experience": "Landing page experience component of quality score.",
        },
    },
    "ad_group_performance_report": {
        "description": "Daily performance metrics broken down by ad group.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/reporting-service/adgroupperformancereportrequest",
        "columns": {
            **_REPORT_METRICS,
            "ad_group_id": "Identifier of the ad group the row belongs to.",
            "ad_group_name": "Name of the ad group the row belongs to.",
            "absolute_top_impression_share_percent": "Percentage of impressions shown in the very top position.",
            "top_impression_share_percent": "Percentage of impressions shown in a top position above search results.",
            "impression_share_percent": "Share of impressions received out of those the ad group was eligible for.",
            "impression_lost_to_budget_percent": "Share of impressions lost because of insufficient budget.",
            "impression_lost_to_rank_agg_percent": "Share of impressions lost because of ad rank.",
            "quality_score": "Microsoft's measure of how competitive the ad group's ads are.",
            "expected_ctr": "Expected click-through rate component of quality score.",
            "ad_relevance": "Ad relevance component of quality score.",
            "landing_page_experience": "Landing page experience component of quality score.",
        },
    },
    "ad_performance_report": {
        "description": "Daily performance metrics broken down by individual ad.",
        "docs_url": "https://learn.microsoft.com/en-us/advertising/reporting-service/adperformancereportrequest",
        "columns": {
            **_REPORT_METRICS,
            "ad_group_id": "Identifier of the ad group the ad belongs to.",
            "ad_group_name": "Name of the ad group the ad belongs to.",
            "ad_id": "Identifier of the ad the row belongs to.",
            "ad_title": "Title text of the ad.",
            "ad_type": "Type of the ad (e.g. TextAd, ResponsiveSearchAd, ProductAd).",
        },
    },
}
