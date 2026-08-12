from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_INSIGHTS_COMMON_COLUMNS = {
    "id": "Composite bucket identifier (start=<unix>:end=<unix>:entity_id=<id>), unique per time bucket and entity.",
    "start_time": "Start of the reporting bucket (UTC timestamp).",
    "end_time": "End of the reporting bucket (UTC timestamp).",
    "readable_time": "Human-readable bucket label, e.g. the bucket's calendar date for daily granularity.",
    "impressions": "Number of times ads were shown during the bucket.",
    "clicks": "Number of clicks recorded during the bucket.",
    "spend": "Amount spent during the bucket, in the ad account's currency (decimal, not micros).",
    "ctr": "Click-through rate: clicks divided by impressions.",
    "cpc": "Average cost per click, in the ad account's currency.",
    "cpm": "Average cost per thousand impressions, in the ad account's currency.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "Ad campaigns in the ad account. A campaign defines the budget, flight dates, and location targeting under which its ad groups deliver.",
        "docs_url": "https://developers.openai.com/ads/api-reference/campaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "Internal campaign name (not shown to users).",
            "description": "Optional campaign description.",
            "status": "Delivery status: active, paused, or archived.",
            "bidding_type": "What the campaign bids on: impressions, clicks, or conversions.",
            "budget": "Budget object, including the lifetime spend limit in micros of the account currency.",
            "targeting": "Targeting object, including the locations the campaign delivers to.",
            "conversion_event_setting_ids": "Conversion event settings attached to the campaign.",
            "mode": "Campaign mode; product_feed for product-feed campaigns.",
            "start_time": "Unix timestamp the campaign starts delivering.",
            "end_time": "Unix timestamp the campaign stops delivering, if set.",
            "created_at": "Unix timestamp the campaign was created.",
            "updated_at": "Unix timestamp the campaign was last updated.",
        },
    },
    "ad_groups": {
        "description": "Ad groups in the ad account, listed per parent campaign. An ad group defines the bidding configuration and audience hints for the ads it contains.",
        "docs_url": "https://developers.openai.com/ads/api-reference/ad-groups",
        "columns": {
            "id": "Unique identifier for the ad group.",
            "campaign_id": "Identifier of the parent campaign (stamped from the listing request).",
            "name": "Internal ad group name (not shown to users).",
            "description": "Optional ad group description.",
            "status": "Delivery status: active, paused, or archived.",
            "context_hints": "Free-form audience or placement hints.",
            "bidding_config": "Bidding configuration: billing event type (impression or click) and max bid in micros.",
            "created_at": "Unix timestamp the ad group was created.",
            "updated_at": "Unix timestamp the ad group was last updated.",
        },
    },
    "ads": {
        "description": "Ads in the ad account, listed per parent ad group. An ad carries the creative (title, body, image, target URL) shown to users in ChatGPT.",
        "docs_url": "https://developers.openai.com/ads/api-reference/ads",
        "columns": {
            "id": "Unique identifier for the ad.",
            "ad_group_id": "Identifier of the parent ad group (stamped from the listing request).",
            "campaign_id": "Identifier of the grandparent campaign (stamped from the listing request).",
            "name": "Internal ad name (not shown to users).",
            "status": "Delivery status: active, paused, or archived.",
            "review_status": "Ad review outcome: in_review, approved, or rejected.",
            "creative": "Creative object: type (chat_card or product_ad_template), title, body, image, target URL, and optional price.",
            "created_at": "Unix timestamp the ad was created.",
            "updated_at": "Unix timestamp the ad was last updated.",
        },
    },
    "campaign_insights": {
        "description": "Daily delivery metrics per campaign: impressions, clicks, spend, CTR, CPC, and CPM.",
        "docs_url": "https://developers.openai.com/ads/api-reference/insights",
        "columns": {
            **_INSIGHTS_COMMON_COLUMNS,
            "campaign_id": "Identifier of the campaign the row aggregates.",
            "campaign_name": "Name of the campaign the row aggregates.",
            "campaign_status": "Status of the campaign at query time.",
        },
    },
    "ad_group_insights": {
        "description": "Daily delivery metrics per ad group: impressions, clicks, spend, CTR, CPC, and CPM.",
        "docs_url": "https://developers.openai.com/ads/api-reference/insights",
        "columns": {
            **_INSIGHTS_COMMON_COLUMNS,
            "ad_group_id": "Identifier of the ad group the row aggregates.",
            "ad_group_name": "Name of the ad group the row aggregates.",
            "ad_group_status": "Status of the ad group at query time.",
        },
    },
    "ad_insights": {
        "description": "Daily delivery metrics per ad: impressions, clicks, spend, CTR, CPC, and CPM.",
        "docs_url": "https://developers.openai.com/ads/api-reference/insights",
        "columns": {
            **_INSIGHTS_COMMON_COLUMNS,
            "ad_id": "Identifier of the ad the row aggregates.",
            "ad_name": "Internal name of the ad the row aggregates.",
            "ad_title": "Creative title of the ad the row aggregates.",
            "ad_status": "Status of the ad at query time.",
            "ad_review_status": "Review status of the ad at query time.",
        },
    },
    "ad_account_insights": {
        "description": "Daily delivery metrics for the whole ad account: impressions, clicks, spend, CTR, CPC, and CPM.",
        "docs_url": "https://developers.openai.com/ads/api-reference/insights",
        "columns": {
            **_INSIGHTS_COMMON_COLUMNS,
            "ad_account_name": "Name of the ad account the row aggregates.",
        },
    },
}
