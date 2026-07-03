"""Canonical, documentation-sourced descriptions for Snapchat Ads endpoints and columns.

Sourced from the official Snapchat Marketing API reference (https://developers.snap.com/api/marketing-api).
Keyed by the resource names in `settings.py` `SNAPCHAT_ADS_CONFIG`, which match the
`ExternalDataSchema.name` of a synced Snapchat Ads table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by the entity (campaign/ad squad/ad) objects.
_ENTITY_COLUMNS = {
    "id": "Unique identifier for the object.",
    "name": "The object's name.",
    "status": "Delivery status of the object (e.g. ACTIVE, PAUSED).",
    "created_at": "Time at which the object was created.",
    "updated_at": "Time at which the object was last updated.",
}

# Fields shared by the daily stats time-series objects.
_STATS_COLUMNS = {
    "id": "ID of the campaign, ad squad, or ad these stats are broken down by.",
    "type": "The entity type the stats are broken down by (CAMPAIGN, AD_SQUAD, or AD).",
    "granularity": "Time granularity of the stats (DAY for these daily tables).",
    "start_time": "Start of the day the stats cover.",
    "end_time": "End of the day the stats cover.",
    "impressions": "Number of times the ad was rendered.",
    "swipes": "Number of swipe-ups (clicks) on the ad.",
    "spend": "Amount spent over the period, in micro-currency (millionths of the account currency).",
    "video_views": "Number of qualifying video views.",
    "frequency": "Average number of times each unique user saw the ad.",
    "uniques": "Number of unique users reached.",
    "conversion_purchases": "Number of purchase conversions attributed to the ad.",
    "conversion_purchases_value": "Total value of purchase conversions attributed to the ad.",
    "conversion_invite": "Number of invite conversion events attributed to the ad.",
    "conversion_login_value": "Total value of login conversion events attributed to the ad.",
    "conversion_searches_value": "Total value of search conversion events attributed to the ad.",
    "conversion_start_checkout_value": "Total value of start-checkout conversion events attributed to the ad.",
    "conversion_achievement_unlocked_value": "Total value of achievement-unlocked conversion events attributed to the ad.",
    "custom_event_3_value": "Total value of the third custom conversion event attributed to the ad.",
    "quartile_1": "Number of times the video was played to 25% (first quartile).",
    "saves": "Number of times users saved the ad.",
    "shares": "Number of times users shared the ad.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "An advertising campaign — the top-level container that holds ad squads and sets the schedule and objective.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/campaigns",
        "columns": {
            **_ENTITY_COLUMNS,
            "ad_account_id": "ID of the ad account that owns the campaign.",
            "objective": "The campaign's advertising objective (e.g. AWARENESS, APP_INSTALLS, WEB_CONVERSION).",
            "start_time": "Scheduled start time of the campaign.",
            "end_time": "Scheduled end time of the campaign, if set.",
            "daily_budget_micro": "Daily budget cap for the campaign, in micro-currency.",
            "lifetime_spend_cap_micro": "Lifetime spend cap for the campaign, in micro-currency.",
        },
    },
    "ad_squads": {
        "description": "An ad squad (ad set) within a campaign — defines targeting, budget, bid, and schedule for a group of ads.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/ad-squads",
        "columns": {
            **_ENTITY_COLUMNS,
            "campaign_id": "ID of the campaign the ad squad belongs to.",
            "type": "The ad squad's type (e.g. SNAP_ADS).",
            "targeting": "Audience targeting specification for the ad squad.",
            "optimization_goal": "The event the ad squad is optimized to drive (e.g. IMPRESSIONS, SWIPES, PIXEL_PURCHASE).",
            "bid_micro": "Bid amount, in micro-currency.",
            "daily_budget_micro": "Daily budget cap for the ad squad, in micro-currency.",
            "lifetime_budget_micro": "Lifetime budget cap for the ad squad, in micro-currency.",
            "billing_event": "The event the ad squad is billed on (e.g. IMPRESSION).",
            "start_time": "Scheduled start time of the ad squad.",
            "end_time": "Scheduled end time of the ad squad, if set.",
        },
    },
    "ads": {
        "description": "An individual ad within an ad squad — pairs creative with delivery settings.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/ads",
        "columns": {
            **_ENTITY_COLUMNS,
            "ad_squad_id": "ID of the ad squad the ad belongs to.",
            "creative_id": "ID of the creative used by the ad.",
            "type": "The ad's type (e.g. SNAP_AD, STORY_AD, COLLECTION).",
            "review_status": "Review status of the ad (e.g. PENDING, APPROVED, REJECTED).",
        },
    },
    "campaign_stats_daily": {
        "description": "Daily performance metrics (spend, impressions, swipes, conversions) broken down by campaign.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/measurement",
        "columns": dict(_STATS_COLUMNS),
    },
    "ad_squad_stats_daily": {
        "description": "Daily performance metrics (spend, impressions, swipes, conversions) broken down by ad squad.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/measurement",
        "columns": dict(_STATS_COLUMNS),
    },
    "ad_stats_daily": {
        "description": "Daily performance metrics (spend, impressions, swipes, conversions) broken down by ad.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/measurement",
        "columns": dict(_STATS_COLUMNS),
    },
}
