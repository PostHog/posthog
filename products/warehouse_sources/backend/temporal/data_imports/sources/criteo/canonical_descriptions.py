"""Canonical, documentation-sourced descriptions for Criteo endpoints and columns.

Sourced from the Criteo Marketing Solutions API reference
(https://developers.criteo.com/marketing-solutions/reference). Keyed by the endpoint names in
`settings.py` `CRITEO_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Criteo table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "advertisers": {
        "description": "The portfolio of advertisers the API credentials have been granted access to.",
        "docs_url": "https://developers.criteo.com/marketing-solutions/reference/advertiser/2026-01advertisersme",
        "columns": {
            "id": "Unique identifier of the advertiser.",
            "type": "Resource type returned by the API for this entity.",
            "advertiserName": "Name of the advertiser (the client name in Criteo).",
        },
    },
    "campaigns": {
        "description": "A campaign, which defines the advertising objective and success criteria its ad sets are optimized against.",
        "docs_url": "https://developers.criteo.com/marketing-solutions/reference/campaign/2026-01marketing-solutionscampaignssearch",
        "columns": {
            "id": "Unique identifier of the campaign.",
            "type": "Resource type returned by the API for this entity.",
            "name": "Name of the campaign.",
            "advertiserId": "Identifier of the advertiser the campaign belongs to.",
            "goal": "Marketing goal of the campaign: unspecified, acquisition, or retention.",
            "budgetAutomation": "Whether Criteo automatically distributes the campaign budget across its ad sets.",
            "spendLimit": "Spend limit configuration for the campaign: limit type, amount, and renewal period.",
        },
    },
    "ad_sets": {
        "description": "An ad set within a campaign, carrying the bidding, budget, schedule, and targeting configuration Criteo delivers against.",
        "docs_url": "https://developers.criteo.com/marketing-solutions/reference/campaign/2026-01marketing-solutionsad-setssearch",
        "columns": {
            "id": "Unique identifier of the ad set.",
            "type": "Resource type returned by the API for this entity.",
            "name": "Name of the ad set.",
            "advertiserId": "Identifier of the advertiser the ad set belongs to.",
            "campaignId": "Identifier of the campaign the ad set belongs to.",
            "datasetId": "Identifier of the dataset (product catalog) the ad set advertises from.",
            "mediaType": "Media the ad set delivers: display or video.",
            "objective": "Optimization objective of the ad set, for example clicks, conversions, revenue, or visits.",
            "destinationEnvironment": "Where users are sent on click: web or app.",
            "videoChannel": "Video channel for video ad sets: olv (online video) or ctv (connected TV).",
            "bidding": "Bidding configuration, including bid strategy, bid amount, and cost controller.",
            "budget": "Budget configuration, including budget strategy, amount, and delivery smoothing.",
            "schedule": "Start and end dates that bound the ad set's delivery.",
            "targeting": "Targeting configuration, including delivery, frequency capping, geo, and subscription settings.",
            "attributionConfiguration": "Click and view attribution windows used when crediting conversions to the ad set.",
        },
    },
    "ads": {
        "description": "An ad, pairing a creative with an ad set for delivery. Retrieved per advertiser in the portfolio.",
        "docs_url": "https://developers.criteo.com/marketing-solutions/reference/creative/2026-01marketing-solutionsadvertisers-ads",
        "columns": {
            "id": "Unique identifier of the ad.",
            "type": "Resource type returned by the API for this entity.",
            "name": "Name of the ad.",
            "description": "Description of the ad.",
            "adSetId": "Identifier of the ad set the ad is delivered in.",
            "creativeId": "Identifier of the creative the ad renders.",
            "inventoryType": "Inventory the ad is eligible for: Native, Display, or Video.",
            "startDate": "Date the ad starts being served.",
            "endDate": "Date the ad stops being served, if set.",
            "_advertiser_id": "Identifier of the advertiser this row was retrieved for. Added by PostHog, since the ads listing is queried per advertiser.",
        },
    },
    "audiences": {
        "description": "An audience: a reusable set of users, defined by an algebra of audience segments, that ad sets can target.",
        "docs_url": "https://developers.criteo.com/marketing-solutions/reference/audience/2026-01marketing-solutionsaudiencessearch",
        "columns": {
            "id": "Unique identifier of the audience.",
            "type": "Resource type returned by the API for this entity.",
            "name": "Name of the audience.",
            "description": "Description of the audience.",
            "advertiserId": "Identifier of the advertiser the audience belongs to.",
            "adSetIds": "Identifiers of the ad sets currently targeting this audience.",
            "algebra": "Set expression combining audience segments (include, exclude, intersect) that defines the audience.",
            "createdAt": "When the audience was created.",
            "updatedAt": "When the audience was last modified.",
        },
    },
    "campaign_stats": {
        "description": "Daily delivery, cost, and post-click conversion statistics per advertiser and campaign, from the Criteo statistics report.",
        "docs_url": "https://developers.criteo.com/marketing-solutions/docs/campaign-statistics",
        "columns": {
            "Day": "Day the statistics are aggregated over, in the reporting time zone.",
            "AdvertiserId": "Identifier of the advertiser the row covers.",
            "Advertiser": "Name of the advertiser the row covers.",
            "CampaignId": "Identifier of the campaign the row covers.",
            "Campaign": "Name of the campaign the row covers.",
            "Displays": "Number of ad impressions served on publishers via Criteo.",
            "Clicks": "Number of clicks driven by the ads.",
            "AdvertiserCost": "Total advertising spend, in the reporting currency.",
            "Visits": "Users who triggered at least one event within an hour of clicking.",
            "SalesAllPc30d": "Transactions attributed post-click within a 30-day window.",
            "RevenueGeneratedAllPc30d": "Revenue from transactions attributed post-click within a 30-day window, in the reporting currency.",
            "ConversionRateAllPc30d": "Share of clicks that converted, post-click within a 30-day window, as a decimal.",
            "RoasAllPc30d": "Return on ad spend: attributed revenue divided by cost, post-click within a 30-day window.",
            "Cpc": "Average cost per click, in the reporting currency.",
            "ClickThroughRate": "Clicks divided by displays, as a decimal.",
        },
    },
}
