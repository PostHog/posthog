from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://docs-publisher.daisycon.com/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "transactions": {
        "description": "A sale or lead attributed to the publisher, with one part per commissionable item.",
        "docs_url": _DOCS,
        "columns": {
            "affiliatemarketing_id": "Unique identifier of the transaction.",
            "date": "When the transaction happened, in Daisycon's local time.",
            "program_id": "The advertiser program the transaction belongs to.",
            "program_name": "Name of the advertiser program.",
            "ip_country_code": "Country of the visitor, derived from the IP address.",
            "device_type_id": "Device type of the visitor, as a Daisycon device type id.",
            "parts": "The commissionable parts of the transaction, each with its own status, commission and revenue.",
            "last_modified": "Newest modification time across the transaction's parts. Used for incremental sync.",
        },
    },
    "statistics_daily": {
        "description": "Clicks, transactions and commission per day for the publisher.",
        "docs_url": _DOCS,
        "columns": {
            "date": "The day the statistics cover.",
            "currency_code": "Currency of the amounts in the row.",
            "click_raw": "All clicks recorded that day.",
            "click_unique": "Unique clicks recorded that day.",
            "transaction_unique": "Number of transactions that day.",
            "transaction_open": "Transactions still waiting for the advertiser's approval.",
            "transaction_approved": "Transactions the advertiser approved.",
            "transaction_disapproved": "Transactions the advertiser rejected.",
            "transaction_amount": "Total publisher commission for the day's transactions.",
            "transaction_revenue": "Total order value of the day's transactions.",
        },
    },
    "programs": {
        "description": "An advertiser program the publisher can promote.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the program.",
            "advertiser_id": "The advertiser that runs the program.",
            "name": "Program name.",
            "url": "Advertiser website URL.",
            "status": "Program status.",
            "startdate": "When the program started.",
            "enddate": "When the program ends, if it has an end date.",
            "commission": "Commission terms of the program.",
            "currency_code": "Currency of the program's commissions.",
        },
    },
    "media": {
        "description": "A website, app or other channel the publisher promotes programs on.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier of the media.",
            "name": "Media name.",
            "location": "URL or location of the media.",
            "type_id": "Media type, as a Daisycon media type id.",
            "creation_date": "When the media was registered.",
            "approval_status": "Whether Daisycon approved the media.",
            "status": "Media status: active, deleted or offline.",
        },
    },
}
