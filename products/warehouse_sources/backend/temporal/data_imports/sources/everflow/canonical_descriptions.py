from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://developers.everflow.io/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "offers": {
        "description": "An offer the network runs for an advertiser, with its payout and revenue terms.",
        "docs_url": f"{_DOCS}api-reference/post-networksofferstable",
        "columns": {
            "network_offer_id": "Unique identifier of the offer in the network.",
            "network_advertiser_id": "The advertiser that owns the offer.",
            "name": "Offer name.",
            "offer_status": "Offer status, such as active, paused or deleted.",
            "time_created": "When the offer was created, as Unix seconds.",
            "time_saved": "When the offer was last saved, as Unix seconds.",
        },
    },
    "affiliates": {
        "description": "A partner that promotes the network's offers.",
        "docs_url": f"{_DOCS}api-reference/post-networksaffiliatestable",
        "columns": {
            "network_affiliate_id": "Unique identifier of the partner in the network.",
            "name": "Partner name.",
            "account_status": "Partner account status.",
            "account_manager_id": "The network employee who manages the partner.",
            "balance": "Amount the network owes the partner.",
            "time_created": "When the partner was created, as Unix seconds.",
            "time_saved": "When the partner was last saved, as Unix seconds.",
        },
    },
    "advertisers": {
        "description": "A brand whose offers the network runs.",
        "docs_url": f"{_DOCS}api-reference/post-networksadvertiserstable",
        "columns": {
            "network_advertiser_id": "Unique identifier of the advertiser in the network.",
            "name": "Advertiser name.",
            "account_status": "Advertiser account status: active, inactive or suspended.",
            "default_currency_id": "Currency the advertiser is billed in.",
            "time_created": "When the advertiser was created, as Unix seconds.",
            "time_saved": "When the advertiser was last saved, as Unix seconds.",
        },
    },
    "conversions": {
        "description": "A conversion or post-conversion event attributed to a partner and an offer.",
        "docs_url": f"{_DOCS}api-reference/post-networksreportingconversions",
        "columns": {
            "conversion_id": "Unique identifier of the conversion.",
            "conversion_unix_timestamp": "When the conversion happened, as Unix seconds in UTC.",
            "click_unix_timestamp": "When the click behind the conversion happened, as Unix seconds in UTC.",
            "transaction_id": "Identifier of the click the conversion is attributed to.",
            "status": "Conversion status, such as approved, pending or rejected.",
            "payout": "Amount the network pays the partner for the conversion.",
            "revenue": "Amount the network earns from the advertiser for the conversion.",
            "currency_id": "Currency of the payout and revenue.",
            "is_event": "Whether the row is a post-conversion event rather than the base conversion.",
            "relationship": "The offer, partner and advertiser the conversion belongs to.",
        },
    },
    "daily_performance": {
        "description": "Clicks, conversions, payout and revenue per day, offer and partner.",
        "docs_url": f"{_DOCS}api-reference/post-networksreportingentitytable",
        "columns": {
            "date": "The UTC day the totals cover.",
            "network_offer_id": "The offer the totals cover.",
            "offer_name": "Name of the offer.",
            "network_affiliate_id": "The partner the totals cover.",
            "affiliate_name": "Name of the partner.",
            "currency_id": "Currency of the payout, revenue and profit amounts.",
            "total_click": "All clicks that day.",
            "unique_click": "Unique clicks that day.",
            "cv": "Conversions that day.",
            "payout": "Amount owed to the partner for that day.",
            "revenue": "Amount earned from the advertiser for that day.",
            "profit": "Revenue minus payout.",
        },
    },
}
