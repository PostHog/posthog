from products.warehouse_sources.sources.sdk import CanonicalDescriptions, CanonicalEndpoint

_DOCS = "https://docs.trafficstars.com/"


def _breakdown(dimension: str) -> CanonicalEndpoint:
    return {
        "description": f"Impressions, clicks, leads and costs per day and {dimension}, across all campaigns.",
        "docs_url": f"{_DOCS}#/_reports",
        "columns": {
            "date": "The day the statistics cover.",
            "id": f"The {dimension} the statistics cover.",
            "name": f"Name of the {dimension}.",
            "impressions": "Ad impressions that day.",
            "clicks": "Ad clicks that day.",
            "leads": "Conversions tracked that day.",
            "costs": "Amount spent that day.",
            "ctr": "Clicks per impression, as a percentage.",
            "ecpm": "Effective cost per 1,000 impressions.",
            "ecpc": "Effective cost per click.",
            "ecpa": "Effective cost per conversion.",
        },
    }


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
    "country_statistics_daily": _breakdown("country"),
    "creative_statistics_daily": _breakdown("creative"),
    "spot_statistics_daily": _breakdown("ad spot"),
    "device_statistics_daily": _breakdown("device type"),
    "os_statistics_daily": _breakdown("operating system"),
    "countries": {
        "description": "A country that campaigns can target, with its code and name.",
        "docs_url": f"{_DOCS}#/_auxiliary",
        "columns": {
            "code": "Two-letter ISO 3166-1 country code.",
            "name": "Country name.",
        },
    },
}
