from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://docs.trafficstars.com/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "An advertising campaign that is not archived.",
        "docs_url": f"{_DOCS}#/_campaigns",
        "columns": {
            "id": "Unique identifier of the campaign.",
            "name": "Campaign name.",
            "status": "Campaign status.",
            "pricing_model": "How the campaign pays, such as CPM or CPC.",
            "price": "Bid price under the pricing model.",
            "max_daily": "Daily budget cap.",
            "total_budget": "Total budget cap.",
            "created_at": "When the campaign was created.",
            "updated_at": "When the campaign was last changed.",
        },
    },
    "creatives": {
        "description": "A creative (banner) that a campaign shows.",
        "docs_url": f"{_DOCS}#/_banners",
        "columns": {
            "id": "Unique identifier of the creative.",
            "campaign_id": "The campaign the creative belongs to.",
            "name": "Creative name.",
            "status": "Creative status.",
            "approved": "Whether TrafficStars approved the creative.",
            "created_at": "When the creative was created.",
            "updated_at": "When the creative was last changed.",
        },
    },
    "campaign_statistics_daily": {
        "description": "Impressions, clicks, leads and costs per day and campaign.",
        "docs_url": f"{_DOCS}#/_reports",
        "columns": {
            "date": "The day the statistics cover.",
            "id": "The campaign the statistics cover.",
            "name": "Campaign name.",
            "impressions": "Ad impressions that day.",
            "clicks": "Ad clicks that day.",
            "leads": "Conversions tracked that day.",
            "costs": "Amount spent that day.",
            "ctr": "Clicks per impression, as a percentage.",
            "ecpm": "Effective cost per 1,000 impressions.",
            "ecpc": "Effective cost per click.",
            "ecpa": "Effective cost per conversion.",
            "goals": "Conversions, cost and revenue per conversion goal.",
        },
    },
}
