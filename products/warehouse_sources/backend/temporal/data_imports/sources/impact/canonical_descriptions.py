from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Campaigns": {
        "description": "The affiliate programs (campaigns) advertised on your Impact.com account.",
        "docs_url": "https://integrations.impact.com/brand-api-reference/reference/programs/programs",
        "columns": {
            "Id": "Unique identifier for the campaign (program).",
            "Name": "Name of the campaign.",
            "State": "Current state of the campaign, e.g. ACTIVE, SETUP, CLOSED.",
            "Type": "Type of campaign.",
        },
    },
    "MediaPartners": {
        "description": "The partners (publishers/affiliates) working with your campaigns.",
        "docs_url": "https://integrations.impact.com/brand-api-reference/reference/partners/partners",
        "columns": {
            "Id": "Unique identifier for the partner.",
            "Name": "Display name of the partner.",
            "State": "Account state of the partner, e.g. ACTIVE, PENDING, DEACTIVATED.",
            "PartnerType": "DIRECT or MARKETPLACE.",
            "DateCreated": "When the partner account was created.",
            "DateLastUpdated": "When the partner record was last updated.",
        },
    },
    "Invoices": {
        "description": "Invoices issued for partner payouts.",
        "docs_url": "https://integrations.impact.com/brand-api-reference/reference/invoices/invoices",
        "columns": {
            "Id": "Unique identifier for the invoice.",
            "CreatedDate": "When the invoice was created.",
            "MediaId": "Partner (media) id the invoice was issued to.",
            "MediaName": "Partner (media) name the invoice was issued to.",
            "Currency": "ISO 4217 currency code of the invoice.",
            "TotalAmount": "Total invoice amount.",
        },
    },
    "Actions": {
        "description": "Conversion and commission records tracked against your campaigns.",
        "docs_url": "https://integrations.impact.com/brand-api-reference/reference/actions/actions",
        "columns": {
            "Id": "Unique identifier for the action.",
            "CampaignId": "Campaign the action was tracked against.",
            "CampaignName": "Name of the campaign the action was tracked against.",
            "State": "Approval state of the action: PENDING, APPROVED, or REVERSED.",
            "Payout": "Commission payout for the action.",
            "Amount": "Order/transaction amount associated with the action.",
            "Currency": "ISO 4217 currency code of the payout/amount.",
            "EventDate": "When the tracked conversion event occurred.",
            "CreationDate": "When the action record was created.",
            "LockingDate": "When the action's payout was (or will be) locked/finalized.",
            "MediaPartnerId": "Partner credited with the action.",
            "MediaPartnerName": "Name of the partner credited with the action.",
        },
    },
}
