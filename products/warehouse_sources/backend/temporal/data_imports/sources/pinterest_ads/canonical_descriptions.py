"""Canonical, documentation-sourced descriptions for Pinterest Ads endpoints and columns.

Sourced from the official Pinterest API v5 reference (https://developers.pinterest.com/docs/api/v5/).
Keyed by the endpoint names in `settings.py` `PINTEREST_ADS_CONFIG`, which match the
`ExternalDataSchema.name` of a synced Pinterest Ads table. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Metric columns shared by every analytics endpoint (campaign/ad group/ad), merged into each entry.
_ANALYTICS_COLUMNS = {
    "date": "The day the metrics are reported for.",
    "SPEND_IN_DOLLAR": "Amount spent in the advertiser's profile currency.",
    "SPEND_IN_MICRO_DOLLAR": "Amount spent in micro-units of the advertiser's profile currency.",
    "PAID_IMPRESSION": "Number of paid impressions served.",
    "TOTAL_IMPRESSION": "Total number of impressions (paid and earned).",
    "TOTAL_CLICKTHROUGH": "Total number of clickthroughs to the destination URL.",
    "OUTBOUND_CLICK_1": "Number of outbound clicks attributed in the 1-day window.",
    "TOTAL_ENGAGEMENT": "Total number of engagements (saves, clicks, closeups).",
    "ENGAGEMENT_RATE": "Engagements divided by impressions.",
    "CTR": "Clickthrough rate — clickthroughs divided by impressions.",
    "CPC_IN_MICRO_DOLLAR": "Cost per click, in micro-units of the profile currency.",
    "CPM_IN_DOLLAR": "Cost per thousand impressions, in the profile currency.",
    "TOTAL_CONVERSIONS": "Total number of attributed conversions.",
    "TOTAL_CHECKOUT": "Total number of attributed checkout conversions.",
    "CHECKOUT_ROAS": "Return on ad spend for checkout conversions.",
    "TOTAL_VIDEO_3SEC_VIEWS": "Number of 3-second video views.",
    "TOTAL_VIDEO_P100_COMPLETE": "Number of times the video was watched to completion.",
    # Normalized (snake_case) metric column names as stored after sync.
    "paid_impression": "Number of paid impressions served.",
    "engagement_rate": "Engagements divided by impressions.",
    "cpc_in_micro_dollar": "Cost per click, in micro-units of the profile currency.",
    "ecpc_in_micro_dollar": "Effective cost per click, in micro-units of the profile currency.",
    "ecpc_in_dollar": "Effective cost per click, in the profile currency.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A Pinterest advertising campaign that groups ad groups under a single objective and budget.",
        "docs_url": "https://developers.pinterest.com/docs/api/v5/campaigns-list/",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "ad_account_id": "ID of the ad account that owns the campaign.",
            "name": "The campaign's name.",
            "status": "Status of the campaign (e.g. ACTIVE, PAUSED, ARCHIVED).",
            "objective_type": "The campaign's advertising objective (e.g. AWARENESS, CONSIDERATION, WEB_CONVERSION).",
            "summary_status": "Read-only effective delivery status of the campaign (e.g. RUNNING, PAUSED, COMPLETED).",
            "daily_spend_cap": "Daily spend cap for the campaign, in micro-currency.",
            "lifetime_spend_cap": "Lifetime spend cap for the campaign, in micro-currency.",
            "created_time": "Time at which the campaign was created, as a Unix timestamp.",
            "updated_time": "Time at which the campaign was last updated, as a Unix timestamp.",
            "start_time": "Scheduled start time of the campaign, as a Unix timestamp.",
            "end_time": "Scheduled end time of the campaign, as a Unix timestamp.",
        },
    },
    "ad_groups": {
        "description": "A group of ads within a campaign, sharing targeting, budget, and bidding settings.",
        "docs_url": "https://developers.pinterest.com/docs/api/v5/ad_groups-list/",
        "columns": {
            "id": "Unique identifier for the ad group.",
            "ad_account_id": "ID of the ad account that owns the ad group.",
            "campaign_id": "ID of the campaign the ad group belongs to.",
            "name": "The ad group's name.",
            "status": "Status of the ad group (e.g. ACTIVE, PAUSED, ARCHIVED).",
            "performance_plus_ad_group_type": "The Performance+ ad group type, when the ad group uses Pinterest Performance+ automation.",
            "budget_in_micro_currency": "Budget for the ad group, in micro-currency.",
            "bid_in_micro_currency": "Bid amount for the ad group, in micro-currency.",
            "billable_event": "The event the ad group is billed on (e.g. CLICKTHROUGH, IMPRESSION).",
            "targeting_spec": "Targeting specification (audiences, locations, keywords) for the ad group.",
            "created_time": "Time at which the ad group was created, as a Unix timestamp.",
            "updated_time": "Time at which the ad group was last updated, as a Unix timestamp.",
            "start_time": "Scheduled start time of the ad group, as a Unix timestamp.",
            "end_time": "Scheduled end time of the ad group, as a Unix timestamp.",
        },
    },
    "ads": {
        "description": "An individual ad (promoted Pin) belonging to an ad group.",
        "docs_url": "https://developers.pinterest.com/docs/api/v5/ads-list/",
        "columns": {
            "id": "Unique identifier for the ad.",
            "ad_account_id": "ID of the ad account that owns the ad.",
            "ad_group_id": "ID of the ad group the ad belongs to.",
            "campaign_id": "ID of the campaign the ad belongs to.",
            "pin_id": "ID of the organic Pin promoted by this ad.",
            "name": "The ad's name.",
            "status": "Status of the ad (e.g. ACTIVE, PAUSED, ARCHIVED).",
            "creative_type": "The ad's creative type (e.g. REGULAR, VIDEO, CAROUSEL, SHOPPING).",
            "destination_url": "Destination URL the ad sends users to.",
            "created_time": "Time at which the ad was created, as a Unix timestamp.",
            "updated_time": "Time at which the ad was last updated, as a Unix timestamp.",
        },
    },
    "campaign_analytics": {
        "description": "Daily performance metrics (spend, impressions, clicks, conversions) per campaign.",
        "docs_url": "https://developers.pinterest.com/docs/api/v5/campaigns-analytics/",
        "columns": {"campaign_id": "ID of the campaign the metrics are for.", **_ANALYTICS_COLUMNS},
    },
    "ad_group_analytics": {
        "description": "Daily performance metrics (spend, impressions, clicks, conversions) per ad group.",
        "docs_url": "https://developers.pinterest.com/docs/api/v5/ad_groups-analytics/",
        "columns": {"ad_group_id": "ID of the ad group the metrics are for.", **_ANALYTICS_COLUMNS},
    },
    "ad_analytics": {
        "description": "Daily performance metrics (spend, impressions, clicks, conversions) per ad.",
        "docs_url": "https://developers.pinterest.com/docs/api/v5/ads-analytics/",
        "columns": {"ad_id": "ID of the ad the metrics are for.", **_ANALYTICS_COLUMNS},
    },
}
