from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.settings import ENDPOINTS

REFERENCE_URL = "https://developers.criteo.com/marketing-solutions/v2026.07/reference"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Advertisers": {
        "description": ENDPOINTS["Advertisers"].description,
        "docs_url": f"{REFERENCE_URL}/advertiser/2026-07advertisersme",
        "columns": {"id": "Advertiser identifier.", "advertiserName": "Advertiser name."},
    },
    "Campaigns": {
        "description": ENDPOINTS["Campaigns"].description,
        "docs_url": f"{REFERENCE_URL}/campaign/2026-07marketing-solutionscampaignssearch",
        "columns": {
            "id": "Campaign identifier.",
            "advertiserId": "Identifier of the advertiser that owns the campaign.",
        },
    },
    "AdSets": {
        "description": ENDPOINTS["AdSets"].description,
        "docs_url": f"{REFERENCE_URL}/campaign/2026-07marketing-solutionsad-setssearch",
        "columns": {"id": "Ad set identifier.", "campaignId": "Identifier of the campaign that contains this ad set."},
    },
    "Ads": {
        "description": ENDPOINTS["Ads"].description,
        "docs_url": f"{REFERENCE_URL}/creative/2026-07marketing-solutionsadvertisers-ads",
        "columns": {
            "id": "Ad identifier.",
            "advertiserId": "Identifier of the advertiser that owns the ad.",
            "adSetId": "Identifier of the ad set linked to this ad.",
            "creativeId": "Identifier of the creative linked to this ad.",
        },
    },
    "Audiences": {
        "description": ENDPOINTS["Audiences"].description,
        "docs_url": f"{REFERENCE_URL}/audience/2026-07marketing-solutionsaudiencessearch",
        "columns": {"id": "Audience identifier."},
    },
    "CampaignStats": {
        "description": ENDPOINTS["CampaignStats"].description,
        "docs_url": "https://developers.criteo.com/marketing-solutions/docs/campaign-statistics",
        "columns": {
            "AdvertiserId": "Advertiser identifier.",
            "CampaignId": "Campaign identifier.",
            "Day": "Report day in UTC.",
            "Currency": "Currency used for monetary metrics.",
            "Displays": "Number of ad impressions.",
            "Clicks": "Number of ad clicks.",
            "AdvertiserCost": "Advertiser cost in the selected report currency.",
            "SalesClientAttribution": "Sales attributed with the advertiser's attribution settings.",
            "RevenueGeneratedClientAttribution": "Revenue attributed with the advertiser's attribution settings.",
        },
    },
}
