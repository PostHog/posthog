"""Canonical, documentation-sourced descriptions for Reddit Ads endpoints and columns.

Sourced from the official Reddit Ads API reference (https://ads-api.reddit.com/docs/v3/).
Keyed by the endpoint names in `settings.py` `REDDIT_ADS_CONFIG`, which match the
`ExternalDataSchema.name` of a synced Reddit Ads table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by Reddit Ads entity objects (campaigns, ad groups, ads).
_ENTITY_COLUMNS = {
    "id": "Unique identifier for the object.",
    "created_at": "Time at which the object was created.",
    "modified_at": "Time at which the object was last modified.",
    "name": "The object's name.",
    "configured_status": "The status configured by the advertiser (e.g. ACTIVE, PAUSED).",
    "effective_status": "The object's effective status after all rules are applied.",
}

# Fields shared by the report endpoints, which return aggregated metrics per breakdown.
_REPORT_COLUMNS = {
    "date": "The date the metrics are aggregated over.",
    "currency": "Three-letter ISO currency code for monetary metrics.",
    "impressions": "Number of times ads were shown.",
    "clicks": "Number of clicks on ads.",
    "spend": "Total amount spent, in the smallest currency unit.",
    "ctr": "Click-through rate (clicks divided by impressions).",
    "cpc": "Average cost per click.",
    "ecpm": "Effective cost per thousand impressions.",
    "reach": "Estimated number of unique users who saw the ads.",
    "frequency": "Average number of times each user saw the ads.",
    "conversion_roas": "Return on ad spend from conversions.",
    "conversion_purchase_total_items": "Total number of items purchased from conversions.",
    "conversion_purchase_total_value": "Total value of purchase conversions.",
    "conversion_purchase_total_value_all": "Total value of purchase conversions across all attribution windows (click and view-through).",
    "conversion_sign_up_views": "Number of sign-up view conversions.",
    "conversion_signup_total_value": "Total value of sign-up conversions.",
    "app_install_install_count": "Number of app installs attributed to ads.",
    "app_install_purchase_count": "Number of in-app purchases attributed to ads.",
    "app_install_revenue": "Revenue from app-install-attributed purchases.",
    "app_install_roas_double": "Return on ad spend from app installs.",
    "key_conversion_rate": "Rate of the key conversion event.",
    "key_conversion_total_count": "Total count of the key conversion event.",
    "video_started": "Number of video views started.",
    "video_view_rate": "Rate at which the video was viewed.",
    "video_completion_rate": "Rate at which the video was watched to completion.",
    "video_watched_25_percent": "Number of times the video was watched to 25%.",
    "video_watched_50_percent": "Number of times the video was watched to 50%.",
    "video_watched_75_percent": "Number of times the video was watched to 75%.",
    "video_watched_100_percent": "Number of times the video was watched to 100%.",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "A Reddit Ads campaign grouping ad groups under a shared objective and budget.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Get%20Campaigns",
        "columns": {
            **_ENTITY_COLUMNS,
            "objective": "The campaign's advertising objective (e.g. CONVERSIONS, TRAFFIC).",
            "spend_cap": "Lifetime spend cap for the campaign, if set.",
            "funding_instrument_id": "ID of the funding instrument paying for the campaign.",
        },
    },
    "ad_groups": {
        "description": "A Reddit Ads ad group within a campaign, defining targeting, bidding, and budget.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Get%20Ad%20Groups",
        "columns": {
            **_ENTITY_COLUMNS,
            "campaign_id": "ID of the campaign this ad group belongs to.",
            "bid_strategy": "The bidding strategy used by the ad group.",
            "bid_value": "The bid value for the ad group.",
            "goal_type": "The optimization goal type for the ad group.",
            "goal_value": "The optimization goal value for the ad group.",
            "start_time": "Time at which the ad group is scheduled to start.",
            "end_time": "Time at which the ad group is scheduled to end.",
        },
    },
    "ads": {
        "description": "A Reddit Ads ad — the creative shown to users within an ad group.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Get%20Ads",
        "columns": {
            **_ENTITY_COLUMNS,
            "ad_group_id": "ID of the ad group this ad belongs to.",
            "type": "The ad's creative type.",
            "click_url": "The destination URL users are sent to when clicking the ad.",
            "preview_url": "URL to preview the ad creative.",
            "post_id": "ID of the Reddit post backing the ad creative.",
        },
    },
    "campaign_report": {
        "description": "Daily aggregated performance metrics broken down by campaign.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "campaign_id": "ID of the campaign the metrics are aggregated for.",
        },
    },
    "ad_group_report": {
        "description": "Daily aggregated performance metrics broken down by ad group.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "ad_group_id": "ID of the ad group the metrics are aggregated for.",
        },
    },
    "ad_report": {
        "description": "Daily aggregated performance metrics broken down by ad.",
        "docs_url": "https://ads-api.reddit.com/docs/v3/operations/Generate%20Report",
        "columns": {
            **_REPORT_COLUMNS,
            "ad_id": "ID of the ad the metrics are aggregated for.",
        },
    },
}
