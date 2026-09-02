"""Canonical, documentation-sourced descriptions for Meta Ads endpoints and columns.

Sourced from the official Meta Marketing API reference (https://developers.facebook.com/docs/marketing-apis/).
Keyed by the resource names in `schemas.py` `MetaAdsResource`, which match the
`ExternalDataSchema.name` of a synced Meta Ads table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.schemas import (
    HOURLY_BREAKDOWN_STATS_FIELDS,
    MetaAdsResource,
)

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


_INSIGHTS_BREAKDOWNS_DOCS_URL = "https://developers.facebook.com/docs/marketing-api/insights/breakdowns/"

# The hourly table syncs a reduced metric set, so its descriptions are filtered to match.
_HOURLY_COLUMN_NAMES = {*HOURLY_BREAKDOWN_STATS_FIELDS, "hourly_stats_aggregated_by_advertiser_time_zone"}


def _campaign_breakdown_columns(**breakdowns: str) -> dict[str, str]:
    """Campaign-level breakdown tables share the campaign_stats columns, plus their own dimensions."""
    return _stats_columns(campaign_id="The ID of the campaign the metrics belong to.", **breakdowns)


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
    MetaAdsResource.AdAccount: {
        "description": "The Meta ad account this source syncs, including its currency, timezone and spend limits.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/ad-account/",
        "columns": {
            "id": "The ad account ID, prefixed with act_.",
            "account_id": "The ad account ID without the act_ prefix.",
            "name": "The name of the ad account.",
            "account_status": "Numeric status of the account (1 active, 2 disabled, 3 unsettled, 101 closed).",
            "currency": "The currency the account is billed in. Every spend and value metric is denominated in it.",
            "timezone_id": "The ID of the account's timezone.",
            "timezone_name": "The name of the account's timezone, for example America/Los_Angeles.",
            "timezone_offset_hours_utc": "The account timezone's offset from UTC, in hours.",
            "amount_spent": "Total amount spent by the account, in the account's minor currency unit.",
            "balance": "Outstanding balance on the account, in the account's minor currency unit.",
            "spend_cap": "The account-level spend cap, in the account's minor currency unit.",
            "min_campaign_group_spend_cap": "The minimum spend cap allowed on a campaign in this account.",
            "min_daily_budget": "The minimum daily budget allowed in this account.",
            "created_time": "Time the ad account was created.",
            "business_country_code": "Country code of the business that owns the account.",
            "business_name": "Name of the business that owns the account.",
            "business": "The business that owns the account.",
            "funding_source_details": "Details of the payment method funding the account.",
            "disable_reason": "Why the account was disabled, if it was.",
            "is_prepay_account": "Whether the account is prepaid.",
            "tos_accepted": "Which Meta terms of service the account has accepted.",
            "capabilities": "Capabilities granted to the account.",
            "owner": "ID of the business or person that owns the account.",
        },
    },
    MetaAdsResource.AdCreatives: {
        "description": "An ad creative in Meta Ads: the copy, imagery and call to action an ad is built from.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/ad-creative/",
        "columns": {
            "id": "Unique identifier for the ad creative.",
            "account_id": "The ID of the ad account the creative belongs to.",
            "name": "The name of the creative as it appears in the account's library.",
            "status": "The status of the creative (ACTIVE, IN_PROCESS, WITH_ISSUES, DELETED).",
            "object_type": "The type of Facebook object the creative advertises (e.g. PAGE, SHARE, VIDEO).",
            "object_story_id": "ID of the Page post used in the ad.",
            "effective_object_story_id": "ID of the Page post actually delivered, including unpublished posts.",
            "object_story_spec": "Specification of the unpublished Page post backing the creative.",
            "thumbnail_url": "URL of a thumbnail image for the creative.",
            "image_url": "URL of the creative's image.",
            "image_hash": "Hash of the creative's image, joining to the ad_images table.",
            "video_id": "ID of the video used in the creative.",
            "body": "The body text of the ad.",
            "title": "The headline of a link ad.",
            "call_to_action_type": "Type of call to action button on the ad (e.g. SHOP_NOW, LEARN_MORE).",
            "link_url": "The destination the ad links to.",
            "url_tags": "Query string parameters appended to the ad's URLs, typically UTM tags.",
            "instagram_permalink_url": "Permalink to the Instagram post run as an ad.",
            "actor_id": "The Page ID behind the creative.",
            "asset_feed_spec": "Asset combinations used for dynamic creative.",
            "degrees_of_freedom_spec": "Which automatic creative transformations are enabled.",
            "effective_authorization_category": "Whether the ad is categorized as political or issue advertising.",
        },
    },
    MetaAdsResource.AdImages: {
        "description": "An image in the ad account's image library, referenced by ad creatives via its hash.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/ad-image/",
        "columns": {
            "id": "Identifier for the image, made up of the account ID and the image hash.",
            "hash": "Hash of the image. Ad creatives reference images by this value.",
            "account_id": "The ID of the ad account the image belongs to.",
            "name": "The filename of the image.",
            "url": "A temporary URL the image can be fetched from.",
            "url_128": "A temporary URL for a 128px version of the image.",
            "permalink_url": "A permanent URL for the image.",
            "width": "Width of the image as stored, in pixels.",
            "height": "Height of the image as stored, in pixels.",
            "original_width": "Width of the uploaded image before resizing, in pixels.",
            "original_height": "Height of the uploaded image before resizing, in pixels.",
            "status": "Status of the image (ACTIVE, INTERNAL, DELETED).",
            "created_time": "Time the image was uploaded.",
            "updated_time": "Time the image was last updated.",
            "creatives": "IDs of the ad creatives using this image.",
            "is_associated_creatives_in_adgroups": "Whether creatives using this image are attached to ads.",
        },
    },
    MetaAdsResource.AdsPixels: {
        "description": "A Meta pixel owned by the ad account, used to track website conversions.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/ads-pixel/",
        "columns": {
            "id": "Unique identifier for the pixel.",
            "name": "The name of the pixel.",
            "code": "The pixel's base code snippet.",
            "creation_time": "Time the pixel was created.",
            "last_fired_time": "Time the pixel last fired.",
            "is_created_by_business": "Whether the pixel was created by a business rather than a person.",
            "is_unavailable": "Whether the pixel is unavailable.",
            "data_use_setting": "How data collected by the pixel may be used.",
            "enable_automatic_matching": "Whether automatic advanced matching is enabled.",
            "automatic_matching_fields": "Which fields are enabled for automatic advanced matching.",
            "owner_business": "The business that owns the pixel.",
        },
    },
    MetaAdsResource.CustomConversions: {
        "description": "A custom conversion defined on the ad account, mapping pixel or offline events to an outcome.",
        "docs_url": "https://developers.facebook.com/docs/marketing-api/reference/custom-conversion/",
        "columns": {
            "id": "Unique identifier for the custom conversion.",
            "account_id": "The ID of the ad account the custom conversion belongs to.",
            "name": "The name of the custom conversion.",
            "description": "The description of the custom conversion.",
            "creation_time": "Time the custom conversion was created.",
            "first_fired_time": "Time the custom conversion first fired.",
            "last_fired_time": "Time the custom conversion last fired.",
            "custom_event_type": "The standard event the conversion maps to (e.g. PURCHASE, LEAD, OTHER).",
            "default_conversion_value": "The value assigned to the conversion when the event carries none.",
            "event_source_type": "Where the events come from (e.g. pixel, app, offline).",
            "is_archived": "Whether the custom conversion is archived.",
            "is_unavailable": "Whether the custom conversion is unavailable.",
            "pixel": "The pixel the custom conversion is defined on.",
            "rule": "The rule matching events to this conversion.",
            "retention_days": "How many days of events the conversion retains.",
            "data_sources": "The data sources feeding the custom conversion.",
            "business": "The business that owns the custom conversion.",
        },
    },
    MetaAdsResource.CampaignStatsByAgeGender: {
        "description": "Daily campaign Insights split by the age and gender of the people reached.",
        "docs_url": _INSIGHTS_BREAKDOWNS_DOCS_URL,
        "columns": _campaign_breakdown_columns(
            age="Age bracket of the people the metrics cover (e.g. 25-34).",
            gender="Gender of the people the metrics cover (female, male, unknown).",
        ),
    },
    MetaAdsResource.CampaignStatsByCountry: {
        "description": "Daily campaign Insights split by the country the ads were delivered in.",
        "docs_url": _INSIGHTS_BREAKDOWNS_DOCS_URL,
        "columns": _campaign_breakdown_columns(
            country="Two-letter country code the metrics were delivered in.",
        ),
    },
    MetaAdsResource.CampaignStatsByRegion: {
        "description": "Daily campaign Insights split by the region, such as a state or province, the ads were delivered in.",
        "docs_url": _INSIGHTS_BREAKDOWNS_DOCS_URL,
        "columns": _campaign_breakdown_columns(
            region="Name of the region, such as a state or province, the metrics were delivered in.",
        ),
    },
    MetaAdsResource.CampaignStatsByPlatform: {
        "description": "Daily campaign Insights split by where the ads appeared and what device they were seen on.",
        "docs_url": _INSIGHTS_BREAKDOWNS_DOCS_URL,
        "columns": _campaign_breakdown_columns(
            publisher_platform="The platform the ads ran on (facebook, instagram, audience_network, messenger).",
            platform_position="The placement within the platform (e.g. feed, story, reels).",
            impression_device="The device the impression was served on (e.g. iphone, android_smartphone, desktop).",
        ),
    },
    MetaAdsResource.CampaignStatsHourly: {
        "description": (
            "Campaign Insights split by hour of the day in the advertiser's timezone. "
            "Meta does not report unique metrics such as reach and frequency with hourly breakdowns, "
            "so this table omits them."
        ),
        "docs_url": _INSIGHTS_BREAKDOWNS_DOCS_URL,
        "columns": {
            key: value
            for key, value in _campaign_breakdown_columns(
                hourly_stats_aggregated_by_advertiser_time_zone=(
                    "The hour range the metrics cover, in the advertiser's timezone (e.g. 09:00:00 - 09:59:59)."
                ),
            ).items()
            if key in _HOURLY_COLUMN_NAMES
        },
    },
}
