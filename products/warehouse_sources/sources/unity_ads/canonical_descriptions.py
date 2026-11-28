from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS = "https://docs.unity.com/en-us/oas-statistics/2.0.0"
_MANAGEMENT_DOCS = "https://docs.unity.com/en-us/oas-advertise/1.0.0"

_METRICS = {
    "timestamp": "The UTC day the row covers.",
    "campaignId": "Unity identifier of the campaign.",
    "campaignName": "Name of the campaign on that day.",
    "starts": "Times a user started the ad, also known as impressions.",
    "views": "Times a user watched the whole ad.",
    "clicks": "Times a user clicked the ad's call-to-action button.",
    "installs": "Users who installed the app after watching the ad.",
    "spend": "Advertising budget spent, in US dollars.",
    "cpi": "Average cost per install.",
    "ctr": "Clicks divided by starts.",
    "cvr": "Installs divided by starts.",
    "ecpm": "Estimated cost per 1,000 starts.",
    "d7AdRevenue": "Ad revenue from installed users within 7 days of install.",
    "d7IapRevenue": "In-app purchase revenue from installed users within 7 days of install.",
    "d7TotalRoas": "Ad and in-app purchase revenue within 7 days, divided by spend.",
    "d7Retained": "Installed users still active 7 days after install.",
}

_BID_COLUMNS = {
    "campaignSetId": "Unity identifier of the advertised app.",
    "campaignId": "Unity identifier of the campaign.",
    "country": "Country where the bid applies.",
    "bid": "Bid amount in US dollars.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns_daily": {
        "description": "Unity Ads user acquisition statistics per day and campaign.",
        "docs_url": _DOCS,
        "columns": _METRICS,
    },
    "campaigns_daily_by_country": {
        "description": "Unity Ads user acquisition statistics per day, campaign and country.",
        "docs_url": _DOCS,
        "columns": {**_METRICS, "country": "Two-letter code of the country the users were in."},
    },
    "skan_daily": {
        "description": "Daily SKAdNetwork installs by campaign and conversion value.",
        "docs_url": _DOCS,
        "columns": {
            "timestamp": _METRICS["timestamp"],
            "campaignId": _METRICS["campaignId"],
            "campaignName": _METRICS["campaignName"],
            "conversionValue": "Fine-grained SKAdNetwork conversion value.",
            "installs": "Installs that SKAdNetwork reports, including repeat downloads.",
        },
    },
    "apps": {
        "description": "Apps advertised through Unity Ads.",
        "docs_url": _MANAGEMENT_DOCS,
        "columns": {
            "id": "Unity campaign set identifier for the app.",
            "name": "Name of the advertised app.",
            "store": "Store that lists the app.",
            "storeId": "Identifier of the app in its store.",
        },
    },
    "campaigns": {
        "description": "Unity Ads campaign settings for each advertised app.",
        "docs_url": _MANAGEMENT_DOCS,
        "columns": {
            "id": _METRICS["campaignId"],
            "campaignSetId": _BID_COLUMNS["campaignSetId"],
            "name": "Name of the campaign.",
            "goal": "Optimization goal of the campaign.",
            "enabled": "Whether the campaign is enabled.",
        },
    },
    "cpi_bids": {
        "description": "Campaign cost-per-install bids by country.",
        "docs_url": _MANAGEMENT_DOCS,
        "columns": _BID_COLUMNS,
    },
    "source_bids": {
        "description": "Campaign bids by country and source app.",
        "docs_url": _MANAGEMENT_DOCS,
        "columns": {**_BID_COLUMNS, "sourceAppId": "Unity identifier of the app that shows the ad."},
    },
}
