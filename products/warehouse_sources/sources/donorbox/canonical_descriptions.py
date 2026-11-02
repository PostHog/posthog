from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.donorbox.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "campaigns": {
        "description": "Fundraising campaigns with donation counts, goals, and totals.",
        "docs_url": f"{API_DOCS_URL}#campaigns",
        "columns": {
            "id": "The campaign identifier in Donorbox.",
            "created_at": "The time the campaign was created.",
            "goal_amt": "The fundraising goal amount.",
            "total_raised": "The total amount raised.",
        },
    },
    "donations": {
        "description": "Donations with payment details, donor information, and campaign information.",
        "docs_url": f"{API_DOCS_URL}#donations",
        "columns": {
            "id": "The donation identifier in Donorbox.",
            "donation_date": "The date and time of the donation.",
            "amount": "The donation amount in the donation currency.",
            "amount_refunded": "The refunded donation amount.",
            "recurring": "Whether the donation is recurring.",
        },
    },
    "plans": {
        "description": "Recurring donation plans with schedules, amounts, and status.",
        "docs_url": f"{API_DOCS_URL}#plans",
        "columns": {
            "id": "The plan identifier in Donorbox.",
            "started_at": "The date the plan started.",
            "last_donation_date": "The date and time of the last donation.",
            "next_donation_date": "The date of the next scheduled donation.",
            "status": "The plan status.",
        },
    },
    "donors": {
        "description": "Donor contact details, donation counts, and totals by currency.",
        "docs_url": f"{API_DOCS_URL}#donors",
        "columns": {
            "id": "The donor identifier in Donorbox.",
            "created_at": "The time the donor record was created.",
            "donations_count": "The number of donations from the donor.",
            "total": "Donation totals grouped by currency.",
        },
    },
    "events": {
        "description": "Fundraising events with donation and ticket counts.",
        "docs_url": f"{API_DOCS_URL}#events",
        "columns": {
            "id": "The event identifier in Donorbox.",
            "name": "The event name.",
            "tickets_count": "The number of event tickets.",
        },
    },
    "tickets": {
        "description": "Event tickets with prices, ticket types, and purchase details.",
        "docs_url": f"{API_DOCS_URL}#tickets",
        "columns": {
            "id": "The ticket identifier in Donorbox.",
            "price": "The ticket price.",
            "free_ticket": "Whether the ticket is free.",
            "transaction": "The transaction associated with the ticket purchase.",
        },
    },
    "purchases": {
        "description": "Event ticket purchases with payment details and purchased tickets.",
        "docs_url": f"{API_DOCS_URL}#event-ticket-purchases",
        "columns": {
            "id": "The purchase identifier in Donorbox.",
            "date": "The date and time of the purchase.",
            "amount_refunded": "The refunded purchase amount.",
            "tickets_count": "The number of tickets in the purchase.",
        },
    },
}
