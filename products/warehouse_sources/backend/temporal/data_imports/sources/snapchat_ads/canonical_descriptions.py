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


# Objects that carry no delivery `status` of their own (creatives and media report their own
# status fields instead).
_UNSTATUSED_OBJECT_COLUMNS = {key: value for key, value in _ENTITY_COLUMNS.items() if key != "status"}

# Columns added to a stats row by a `report_dimension` (delivery insights) request.
_COUNTRY_DIMENSION_COLUMNS = {
    "country": "ISO country code the metrics on this row are broken down by.",
}

_DEMOGRAPHIC_DIMENSION_COLUMNS = {
    "age_bucket": "Age bucket the metrics on this row are broken down by (e.g. 13-17, 25-34, 35+).",
    "gender": "Gender the metrics on this row are broken down by (e.g. female, male, unknown).",
}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "ad_accounts": {
        "description": "The ad account the data is imported from, including the currency and timezone every spend and daily metric is reported in.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/ad-accounts",
        "columns": {
            **_ENTITY_COLUMNS,
            "type": "Account type (DIRECT or PARTNER).",
            "currency": "Currency the account is billed and reported in (e.g. USD, EUR, GBP).",
            "timezone": "Timezone used for the account's reporting day boundaries.",
            "organization_id": "ID of the organization that owns the ad account.",
            "advertiser": "Name of the advertiser the account runs ads for.",
            "advertiser_organization_id": "Organization ID of the selected advertiser.",
            "billing_type": "Billing model for the account (IO or REVOLVING).",
            "billing_center_id": "ID of the billing center the account bills through.",
            "funding_source_ids": "IDs of the funding sources attached to the account.",
            "lifetime_spend_cap_micro": "Lifetime spend cap for the account, in micro-currency.",
            "regulations": "Regulated-category settings (credit, housing, employment) applied to the account.",
            "agency_representing_client": "Whether the account is run by an agency on behalf of a client.",
            "test": "Whether this is a test ad account, which can never serve live ads.",
        },
    },
    "creatives": {
        "description": "A creative — the media, headline, and call to action an ad renders. Join to `ads.creative_id` to attribute performance to what people actually saw.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/creatives",
        "columns": {
            **_UNSTATUSED_OBJECT_COLUMNS,
            "ad_account_id": "ID of the ad account that owns the creative.",
            "type": "Creative type (e.g. SNAP_AD, APP_INSTALL, WEB_VIEW, COLLECTION, LENS).",
            "headline": "Headline displayed under the brand name.",
            "brand_name": "Brand name shown on the creative.",
            "call_to_action": "Call to action shown on the swipe-up button.",
            "top_snap_media_id": "ID of the media used as the top snap.",
            "top_snap_crop_position": "How the top snap media is cropped (OPTIMIZED, MIDDLE, TOP, BOTTOM).",
            "shareable": "Whether users are allowed to share the ad with friends.",
            "forced_view_eligibility": "Whether the creative can be used as a Commercial (FULL_DURATION, SIX_SECONDS, NONE).",
            "preview_creative_id": "ID of the preview creative, used by Story Ads.",
            "packaging_status": "Processing status of the creative's media packaging.",
            "review_status": "Ad review status of the creative.",
            "profile_properties": "Public profile attached to the creative.",
            "web_view_properties": "Web view attachment settings, for WEB_VIEW creatives.",
            "app_install_properties": "App install attachment settings, for APP_INSTALL creatives.",
            "deep_link_properties": "Deep link attachment settings, for DEEP_LINK creatives.",
            "lead_generation_form_id": "ID of the lead generation form, for LEAD_GENERATION creatives.",
        },
    },
    "media": {
        "description": "A media asset (video, image, or lens package) owned by the ad account. One media asset can be used by several creatives.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/media",
        "columns": {
            **_UNSTATUSED_OBJECT_COLUMNS,
            "ad_account_id": "ID of the ad account that owns the media.",
            "type": "Media type (VIDEO, IMAGE, LENS_PACKAGE, PLAYABLE).",
            "media_status": "Upload status of the media (PENDING_UPLOAD or READY).",
            "file_name": "File name of the uploaded asset.",
            "download_link": "URL the media file can be downloaded from.",
            "file_size_in_bytes": "Size of the uploaded file, in bytes.",
            "duration_in_seconds": "Duration of the asset, for video media.",
            "image_metadata": "Width, height, and format of the asset, for image media.",
            "video_metadata": "Width, height, rotation, and loudness of the asset, for video media.",
            "media_usages": "The creative slots this media can be used in (e.g. TOP_SNAP, APP_INSTALL_ICON).",
            "lens_package_metadata": "Metadata for lens media created in Lens Studio.",
            "is_demo_media": "Whether the asset is Snapchat-provided demo media.",
            "visibility": "Whether the media is visible in the ad account.",
        },
    },
    "audience_segments": {
        "description": "An audience segment (customer list, lookalike, engagement, or pixel-based) that ad squads can target.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/audience-creation/customer-lists",
        "columns": {
            **_ENTITY_COLUMNS,
            "ad_account_id": "ID of the ad account that owns the segment.",
            "description": "Free-text description of the segment.",
            "source_type": "How the segment was built (e.g. FIRST_PARTY, LOOKALIKE, ENGAGEMENT, PIXEL).",
            "status": "Status of the segment (e.g. PENDING, ACTIVE).",
            "upload_status": "Whether uploaded users have been processed (NO_UPLOAD, PROCESSING, COMPLETE).",
            "targetable_status": "Whether the segment can be targeted (NOT_READY, TOO_FEW_USERS, READY).",
            "retention_in_days": "Number of days a user stays in the segment.",
            "approximate_number_users": "Approximate number of users matched into the segment.",
        },
    },
    "pixels": {
        "description": "A Snap Pixel — the tag that ties website conversions back to the ads people saw. Join a pixel to the conversion metrics on the stats tables.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/snap-pixel",
        "columns": {
            **_ENTITY_COLUMNS,
            "ad_account_id": "ID of the ad account the pixel belongs to.",
            "status": "Configured status of the pixel.",
            "effective_status": "Status the pixel is actually serving with.",
            "pixel_javascript": "The pixel's JavaScript snippet, as installed on the advertiser's site.",
        },
    },
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
    "campaign_stats_daily_country": {
        "description": "Daily delivery insights per campaign and country. Estimated figures that need at least 30 impressions in a day, so totals will not match campaign_stats_daily exactly.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/measurement",
        "columns": {**_STATS_COLUMNS, **_COUNTRY_DIMENSION_COLUMNS},
    },
    "campaign_stats_daily_demographics": {
        "description": "Daily delivery insights per campaign, age bucket, and gender. Estimated figures that need at least 30 impressions in a day, so totals will not match campaign_stats_daily exactly.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/measurement",
        "columns": {**_STATS_COLUMNS, **_DEMOGRAPHIC_DIMENSION_COLUMNS},
    },
    "ad_stats_daily_country": {
        "description": "Daily delivery insights per ad and country. Estimated figures that need at least 30 impressions in a day, so totals will not match ad_stats_daily exactly.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/measurement",
        "columns": {**_STATS_COLUMNS, **_COUNTRY_DIMENSION_COLUMNS},
    },
    "ad_stats_daily_demographics": {
        "description": "Daily delivery insights per ad, age bucket, and gender. Estimated figures that need at least 30 impressions in a day, so totals will not match ad_stats_daily exactly.",
        "docs_url": "https://developers.snap.com/api/marketing-api/Ads-API/measurement",
        "columns": {**_STATS_COLUMNS, **_DEMOGRAPHIC_DIMENSION_COLUMNS},
    },
}
