"""Canonical, documentation-sourced descriptions for Meta Ads endpoints and columns.

Sourced from the official Meta Marketing API reference (https://developers.facebook.com/docs/marketing-apis/).
Keyed by the resource names in `schemas.py` `MetaAdsResource`, which match the
`ExternalDataSchema.name` of a synced Meta Ads table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.schemas import MetaAdsResource

# Columns shared by every Insights (stats) endpoint; merged into each stats entry.
_COMMON_STATS_COLUMNS = {
    "account_id": "The ID of the ad account the metrics belong to.",
    "account_currency": "The currency of the ad account, used for spend and value metrics.",
    "date_start": "Start date of the metrics row (daily, used as the incremental cursor).",
    "date_stop": "End date of the metrics row (daily).",
    "impressions": "The number of times the ads were on screen.",
    "clicks": "The total number of clicks on the ads.",
    "spend": "The total amount spent, in the account currency.",
    "reach": "The number of unique people who saw the ads.",
    "frequency": "The average number of times each person saw the ads.",
    "cpm": "Average cost per 1,000 impressions.",
    "cpc": "Average cost per click.",
    "ctr": "Click-through rate (clicks divided by impressions).",
    "cpp": "Average cost per 1,000 people reached.",
    "cost_per_unique_click": "Average cost per unique click.",
    "unique_clicks": "The number of unique people who clicked.",
    "unique_ctr": "Unique click-through rate.",
    "actions": "Counts of conversion actions attributed to the ads, by action type.",
    "conversions": "The number of conversions attributed to the ads.",
    "conversion_values": "The total value of conversions attributed to the ads.",
    "cost_per_action_type": "Average cost per action, broken down by action type.",
    "action_values": "The total value of actions, broken down by action type.",
}


def _stats_columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_STATS_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    MetaAdsResource.Campaigns: {
        "description": "An advertising campaign in Meta Ads, defining the objective for its ad sets and ads.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "account_id": "The ID of the ad account the campaign belongs to.",
            "name": "The name of the campaign.",
            "status": "The current status of the campaign (ACTIVE, PAUSED, DELETED, ARCHIVED).",
            "configured_status": "The status set by the advertiser, before effective rules are applied.",
            "effective_status": "The effective status after account and delivery rules are applied.",
            "objective": "The campaign objective (e.g. OUTCOME_TRAFFIC, OUTCOME_SALES).",
            "buying_type": "The buying type for the campaign (AUCTION or RESERVED).",
            "daily_budget": "The daily budget for the campaign, in the account's minor currency unit.",
            "lifetime_budget": "The lifetime budget for the campaign, in the account's minor currency unit.",
            "budget_remaining": "The remaining budget for the campaign.",
            "created_time": "Time the campaign was created.",
            "updated_time": "Time the campaign was last updated.",
            "start_time": "The scheduled start time of the campaign.",
            "stop_time": "The scheduled stop time of the campaign.",
            "special_ad_categories": "Special ad categories the campaign is declared under (e.g. HOUSING, CREDIT).",
        },
    },
    MetaAdsResource.Adsets: {
        "description": "An ad set in Meta Ads, grouping ads that share a budget, schedule, and targeting.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/",
        "columns": {
            "id": "Unique identifier for the ad set.",
            "account_id": "The ID of the ad account the ad set belongs to.",
            "campaign_id": "The ID of the campaign the ad set belongs to.",
            "name": "The name of the ad set.",
            "status": "The current status of the ad set (ACTIVE, PAUSED, DELETED, ARCHIVED).",
            "configured_status": "The status set by the advertiser, before effective rules are applied.",
            "effective_status": "The effective status after account and delivery rules are applied.",
            "optimization_goal": "The optimization goal for the ad set (e.g. LINK_CLICKS, CONVERSIONS).",
            "billing_event": "The event the advertiser is billed for (e.g. IMPRESSIONS, LINK_CLICKS).",
            "bid_amount": "The bid amount for the ad set, in the account's minor currency unit.",
            "budget_remaining": "The remaining budget for the ad set.",
            "daily_budget": "The daily budget for the ad set, in the account's minor currency unit.",
            "lifetime_budget": "The lifetime budget for the ad set, in the account's minor currency unit.",
            "created_time": "Time the ad set was created.",
            "updated_time": "Time the ad set was last updated.",
            "start_time": "The scheduled start time of the ad set.",
            "end_time": "The scheduled end time of the ad set.",
            "targeting": "The targeting specification for the ad set.",
            "promoted_object": "The object this ad set is promoting (e.g. page, app, pixel).",
        },
    },
    MetaAdsResource.Ads: {
        "description": "An individual ad in Meta Ads, pairing a creative with its ad set.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/adgroup/",
        "columns": {
            "id": "Unique identifier for the ad.",
            "account_id": "The ID of the ad account the ad belongs to.",
            "adset_id": "The ID of the ad set the ad belongs to.",
            "campaign_id": "The ID of the campaign the ad belongs to.",
            "name": "The name of the ad.",
            "status": "The current status of the ad (ACTIVE, PAUSED, DELETED, ARCHIVED).",
            "configured_status": "The status set by the advertiser, before effective rules are applied.",
            "effective_status": "The effective status after account and delivery rules are applied.",
            "creative": "The creative associated with the ad.",
            "bid_amount": "The bid amount for the ad, in the account's minor currency unit.",
            "created_time": "Time the ad was created.",
            "updated_time": "Time the ad was last updated.",
            "tracking_specs": "The tracking specifications for the ad.",
            "conversion_specs": "The conversion specifications for the ad.",
        },
    },
    MetaAdsResource.CampaignStats: {
        "description": "Daily performance metrics (Insights) at the campaign level in Meta Ads.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/insights/",
        "columns": _stats_columns(
            campaign_id="The ID of the campaign the metrics belong to.",
        ),
    },
    MetaAdsResource.AdsetStats: {
        "description": "Daily performance metrics (Insights) at the ad set level in Meta Ads.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/insights/",
        "columns": _stats_columns(
            adset_id="The ID of the ad set the metrics belong to.",
            campaign_id="The ID of the campaign the ad set belongs to.",
        ),
    },
    MetaAdsResource.AdStats: {
        "description": "Daily performance metrics (Insights) at the ad level in Meta Ads.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/insights/",
        "columns": _stats_columns(
            ad_id="The ID of the ad the metrics belong to.",
            adset_id="The ID of the ad set the ad belongs to.",
            campaign_id="The ID of the campaign the ad belongs to.",
            video_30_sec_watched_actions="The number of times the video was watched for at least 30 seconds.",
            video_p25_watched_actions="The number of times the video was watched to 25% of its length.",
            video_p50_watched_actions="The number of times the video was watched to 50% of its length.",
            video_p75_watched_actions="The number of times the video was watched to 75% of its length.",
            video_p95_watched_actions="The number of times the video was watched to 95% of its length.",
            video_p100_watched_actions="The number of times the video was watched to 100% of its length.",
        ),
    },
}
