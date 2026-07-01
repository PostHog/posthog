"""Canonical, documentation-sourced descriptions for TikTok Ads endpoints and columns.

Sourced from the official TikTok Marketing API reference (https://business-api.tiktok.com/portal/docs).
Keyed by the resource names in `settings.py` `TIKTOK_ADS_CONFIG`, which match the
`ExternalDataSchema.name` of a synced TikTok Ads table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Metrics shared by every integrated report endpoint; merged into each report entry.
_REPORT_METRIC_COLUMNS = {
    "stat_time_day": "Date the metrics are aggregated for.",
    "spend": "Total amount spent in the reporting period.",
    "impressions": "Number of times the ads were shown.",
    "clicks": "Number of clicks on the ads.",
    "ctr": "Click-through rate (clicks divided by impressions).",
    "cpc": "Average cost per click.",
    "cpm": "Average cost per thousand impressions.",
    "conversion": "Number of conversions attributed in the reporting period.",
    "conversion_rate": "Conversion rate for the reporting period.",
    "cost_per_conversion": "Average cost per conversion.",
    "cost_per_result": "Average cost per result for the campaign's optimization goal.",
    "reach": "Number of unique users who saw the ads.",
    "frequency": "Average number of times each user saw the ads.",
    "currency": "Currency the monetary metrics are reported in.",
}


def _report_columns(**overrides: str) -> dict[str, str]:
    return {**_REPORT_METRIC_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "An advertising campaign in your TikTok Ads account, with its objective and budget.",
        "docs_url": "https://business-api.tiktok.com/portal/docs?id=1739315828649986",
        "columns": {
            "campaign_id": "Unique identifier for the campaign.",
            "advertiser_id": "ID of the advertiser account that owns the campaign.",
            "campaign_name": "The campaign's name.",
            "objective_type": "The campaign's advertising objective (e.g. TRAFFIC, CONVERSIONS, REACH).",
            "rf_campaign_type": "For Reach & Frequency campaigns, the type of R&F campaign.",
            "budget": "Budget allocated to the campaign.",
            "budget_mode": "How the budget is applied (e.g. BUDGET_MODE_DAY, BUDGET_MODE_TOTAL).",
            "operation_status": "Operational status of the campaign (e.g. ENABLE, DISABLE).",
            "secondary_status": "More detailed status of the campaign.",
            "create_time": "Time at which the campaign was created.",
            "modify_time": "Time at which the campaign was last modified.",
        },
    },
    "ad_groups": {
        "description": "An ad group within a campaign, defining targeting, placement, and bidding.",
        "docs_url": "https://business-api.tiktok.com/portal/docs?id=1739314558673922",
        "columns": {
            "adgroup_id": "Unique identifier for the ad group.",
            "campaign_id": "ID of the campaign this ad group belongs to.",
            "advertiser_id": "ID of the advertiser account that owns the ad group.",
            "adgroup_name": "The ad group's name.",
            "placement_type": "How placements are selected (e.g. PLACEMENT_TYPE_AUTOMATIC, PLACEMENT_TYPE_NORMAL).",
            "budget": "Budget allocated to the ad group.",
            "budget_mode": "How the ad group's budget is applied.",
            "bid_type": "Bidding strategy for the ad group.",
            "bid_price": "Bid amount for the ad group, if a fixed bid is set.",
            "optimization_goal": "What the ad group is optimized for (e.g. CLICK, CONVERT, REACH).",
            "billing_event": "Event the advertiser is charged for (e.g. CPC, CPM).",
            "click_attribution_window": "Click-through attribution window for conversions (e.g. SEVEN_DAYS).",
            "promotion_type": "What the ad group promotes (e.g. WEBSITE, APP, LEAD_GENERATION).",
            "operation_status": "Operational status of the ad group (e.g. ENABLE, DISABLE).",
            "create_time": "Time at which the ad group was created.",
            "modify_time": "Time at which the ad group was last modified.",
        },
    },
    "ads": {
        "description": "An individual ad creative within an ad group.",
        "docs_url": "https://business-api.tiktok.com/portal/docs?id=1735735588640770",
        "columns": {
            "ad_id": "Unique identifier for the ad.",
            "adgroup_id": "ID of the ad group this ad belongs to.",
            "campaign_id": "ID of the campaign this ad belongs to.",
            "advertiser_id": "ID of the advertiser account that owns the ad.",
            "ad_name": "The ad's name.",
            "ad_format": "Format of the ad (e.g. SINGLE_VIDEO, SINGLE_IMAGE, CAROUSEL).",
            "ad_text": "Primary text shown with the ad.",
            "call_to_action": "Call-to-action button text on the ad.",
            "landing_page_url": "URL the ad directs users to.",
            "music_id": "ID of the music track used in the ad.",
            "tiktok_item_id": "ID of the TikTok post (item) used as the ad creative.",
            "vast_moat_enabled": "Whether third-party VAST/MOAT viewability measurement is enabled for the ad.",
            "operation_status": "Operational status of the ad (e.g. ENABLE, DISABLE).",
            "create_time": "Time at which the ad was created.",
            "modify_time": "Time at which the ad was last modified.",
        },
    },
    "campaign_report": {
        "description": "Daily performance metrics for each campaign.",
        "docs_url": "https://business-api.tiktok.com/portal/docs?id=1740302848100353",
        "columns": _report_columns(
            campaign_id="ID of the campaign the metrics belong to.",
            campaign_name="Name of the campaign the metrics belong to.",
        ),
    },
    "ad_group_report": {
        "description": "Daily performance metrics for each ad group.",
        "docs_url": "https://business-api.tiktok.com/portal/docs?id=1740302848100353",
        "columns": _report_columns(
            adgroup_id="ID of the ad group the metrics belong to.",
            total_complete_payment_rate="Rate of complete-payment conversion events relative to clicks.",
        ),
    },
    "ad_report": {
        "description": "Daily performance metrics for each ad.",
        "docs_url": "https://business-api.tiktok.com/portal/docs?id=1740302848100353",
        "columns": _report_columns(
            ad_id="ID of the ad the metrics belong to.",
            video_views_p100="Number of times the video was watched to 100% of its length.",
        ),
    },
}
