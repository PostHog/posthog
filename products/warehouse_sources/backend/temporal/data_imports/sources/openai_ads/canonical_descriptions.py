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
    "currency_code": "Account currency code fetched from the ad account metadata for this sync.",
    "spend": "Amount spent during the bucket, in the ad account's currency (decimal, not micros).",
    "ctr": "Click-through rate: clicks divided by impressions.",
    "cpc": "Average cost per click, in the ad account's currency.",
    "cpm": "Average cost per thousand impressions, in the ad account's currency.",
}

_SEGMENT_INSIGHTS_COMMON_COLUMNS = {
    "id": "Composite bucket identifier, unique per time bucket, campaign, and segment value.",
    "start_time": "Start of the reporting bucket (UTC timestamp).",
    "end_time": "End of the reporting bucket (UTC timestamp).",
    "readable_time": "Human-readable bucket label, e.g. the bucket's calendar date for daily granularity.",
    "currency_code": "Account currency code fetched from the ad account metadata for this sync.",
    "campaign_id": "Identifier of the campaign the row aggregates.",
    "campaign_name": "Name of the campaign the row aggregates.",
}


def _segment_metric_columns(segment: str, label: str) -> dict[str, str]:
    return {
        f"{segment}_impressions": f"Number of times the campaign's ads were shown for this {label} during the bucket.",
        f"{segment}_clicks": f"Number of clicks for this {label} during the bucket.",
        f"{segment}_spend": f"Amount spent for this {label} during the bucket, in the ad account's currency.",
        f"{segment}_ctr": f"Click-through rate for this {label}: clicks divided by impressions.",
        f"{segment}_cpc": f"Average cost per click for this {label}, in the ad account's currency.",
        f"{segment}_cpm": f"Average cost per thousand impressions for this {label}, in the ad account's currency.",
    }


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "ad_account": {
        "description": "The ad account that the API key belongs to: names, primary URL, status, timezone, currency, and brand review status.",
        "docs_url": "https://developers.openai.com/ads/api-reference/ad-account",
        "columns": {
            "id": "Unique identifier for the ad account.",
            "name": "Legal business name, kept for compatibility.",
            "legal_name": "Legal business name.",
            "account_name": "Internal account name shown in Ads Manager.",
            "brand_name": "Public advertiser name shown in ads.",
            "url": "Primary destination URL of the advertiser.",
            "preview_url": "Preview URL of the advertiser icon, when one is available.",
            "status": "Account status, when one is available.",
            "timezone": "Timezone of the ad account.",
            "currency_code": "Currency of the ad account.",
            "review": "Brand review object, including the review status.",
        },
    },
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
    "campaign_country_insights": {
        "description": "Daily delivery metrics per campaign, split by the country where the ads were shown. Needs segmented insights enabled for the ad account.",
        "docs_url": "https://developers.openai.com/ads/api-reference/insights",
        "columns": {
            **_SEGMENT_INSIGHTS_COMMON_COLUMNS,
            **_segment_metric_columns("country", "country"),
            "country_name": "Name of the country the row covers.",
        },
    },
    "campaign_device_insights": {
        "description": "Daily delivery metrics per campaign, split by device type. Needs segmented insights enabled for the ad account.",
        "docs_url": "https://developers.openai.com/ads/api-reference/insights",
        "columns": {
            **_SEGMENT_INSIGHTS_COMMON_COLUMNS,
            **_segment_metric_columns("device", "device type"),
            "device_type": "Device type the row covers.",
        },
    },
    "campaign_product_insights": {
        "description": "Daily delivery metrics per campaign, split by product-feed item. Use the feed ID and item ID together to match a row to your catalog. Needs segmented insights enabled for the ad account.",
        "docs_url": "https://developers.openai.com/ads/api-reference/insights",
        "columns": {
            **_SEGMENT_INSIGHTS_COMMON_COLUMNS,
            **_segment_metric_columns("product", "product"),
            "product_feed_id": "Identifier of the product feed the item belongs to.",
            "item_id": "Identifier of the item in the product feed.",
            "product_title": "Title of the product-feed item.",
            "product_brand": "Brand of the product-feed item.",
            "product_seller_name": "Seller name of the product-feed item.",
            "product_price": "Price of the product-feed item.",
            "product_availability": "Availability of the product-feed item.",
        },
    },
}
