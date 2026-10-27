from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://docs.unity.com/en-us/oas-statistics/2.0.0"

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
}
