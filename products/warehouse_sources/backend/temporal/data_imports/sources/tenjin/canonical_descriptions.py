from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://api-docs.tenjin.com/"

_APP_COLUMNS = {
    "date": "Date of the related data.",
    "app_id": "The ID of the app in Tenjin.",
    "platform": "The app's platform (ios, android, windows, or amazon).",
    "bundle_id": "The Bundle ID of the app in the App Store.",
    "store_id": "The Store ID of the app in the App Store.",
}

_SPEND_METRIC_COLUMNS = {
    "spend": "Ad spend attributed to the row, in the account currency.",
    "impressions": "Number of ad impressions.",
    "clicks": "Number of ad clicks.",
    "installs": "Number of attributed installs.",
    "cpi": "Cost per install.",
    "ctr": "Click-through rate.",
    "cvr": "Click-to-install conversion rate.",
    "tcpi": "Cost per tracked install.",
    "tracked_installs": "Number of installs tracked by Tenjin.",
}

_CHANNEL_COLUMNS = {
    "ad_network_id": "The ID of the channel in Tenjin.",
    "ad_network_name": "The name of the channel.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "app_report": {
        "description": "Daily user-acquisition performance per app from Tenjin's spend report.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_APP_COLUMNS,
            "name": "The name of the app.",
            "icon_url": "The icon of the app in the App Store.",
            **_SPEND_METRIC_COLUMNS,
        },
    },
    "campaign_report": {
        "description": "Daily user-acquisition performance per campaign from Tenjin's spend report, including the campaign's app and channel.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_APP_COLUMNS,
            "name": "The name of the campaign in Tenjin.",
            "campaign_id": "The ID of the campaign in Tenjin.",
            "app_name": "The name of the app in Tenjin.",
            "app_icon_url": "The icon of the app in the App Store.",
            **_CHANNEL_COLUMNS,
            "icon_url": "The icon of the channel.",
            "ad_network_icon_url": "The icon of the channel.",
            **_SPEND_METRIC_COLUMNS,
        },
    },
    "ad_revenue_report": {
        "description": "Daily ad monetization revenue per app and channel from Tenjin's ad revenue report.",
        "docs_url": _DOCS_URL,
        "columns": {
            **_APP_COLUMNS,
            "app_name": "The name of the app in Tenjin.",
            "app_icon_url": "The icon of the app in the App Store.",
            **_CHANNEL_COLUMNS,
            "ad_network_icon_url": "The icon of the channel.",
            "ad_network_short_id": "Friendly URL slug used to identify the channel.",
            "ad_network_custom": "Whether the channel is custom or natively supported by Tenjin.",
            "ad_revenue": "Ad revenue attributed to the row, in the account currency.",
            "impressions": "Number of ad impressions shown in the app.",
            "clicks": "Number of clicks on ads shown in the app.",
            "ecpm": "Effective cost per thousand impressions.",
            "ecpc": "Effective cost per click.",
        },
    },
    "sk_ad_network_report": {
        "description": "Daily SKAdNetwork postback aggregates per app, channel, SKAN campaign, source app, and conversion value (iOS only).",
        "docs_url": _DOCS_URL,
        "columns": {
            **_APP_COLUMNS,
            "app_name": "The name of the app in Tenjin.",
            **_CHANNEL_COLUMNS,
            "ad_network_short_id": "Friendly URL slug used to identify the channel.",
            "campaign_id": "The ID of the campaign in Tenjin.",
            "campaign_name": "The name of the campaign in Tenjin.",
            "remote_campaign_id": "The campaign's ID on the ad network.",
            "sk_ad_network_id": "SKAdNetwork ID for the ad network.",
            "sk_campaign_id": "SKAdNetwork campaign ID, an integer from 0-99.",
            "sk_source_app_id": "The Store ID of the app that showed the advertisement that led to a conversion.",
            "fidelity_type": "1 for StoreKit-rendered ads, 0 for view-through ads.",
            "conversion_value": "SKAdNetwork conversion value, an integer from 0-63.",
            "conversion_value_count": "Count of occurrences of the conversion value.",
            "conversion_value_total": "Sum of conversion values.",
            "conversion_value_avg": "Average of conversion values.",
        },
    },
}
