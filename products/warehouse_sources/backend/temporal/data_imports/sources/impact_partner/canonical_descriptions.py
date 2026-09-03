from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Campaigns": {
        "description": "The brand programs (campaigns) your partner account has joined.",
        "docs_url": "https://integrations.impact.com/partner-api-reference/reference/programs/programs",
        "columns": {
            "CampaignId": "Unique identifier of the program (campaign).",
            "CampaignName": "Display name of the program.",
            "CampaignUrl": "URL of the program's landing site.",
            "AdvertiserId": "Unique identifier of the brand (advertiser) running the program.",
            "AdvertiserName": "Display name of the brand.",
            "ContractStatus": "Status of your contract with the program, e.g. Active.",
            "TrackingLink": "Your default tracking link for the program.",
        },
    },
    "Actions": {
        "description": "Conversion and commission records credited to your partner account.",
        "docs_url": "https://integrations.impact.com/partner-api-reference/reference/actions/actions",
        "columns": {
            "Id": "Unique identifier for the action.",
            "CampaignId": "Program (campaign) the action was tracked against.",
            "CampaignName": "Name of the program the action was tracked against.",
            "State": "Approval state of the action: PENDING, APPROVED, or REVERSED.",
            "Payout": "Commission payout for the action.",
            "Amount": "Order/transaction amount associated with the action.",
            "Currency": "ISO 4217 currency code of the payout/amount.",
            "EventDate": "When the tracked conversion event occurred.",
            "CreationDate": "When the action record was created.",
            "LockingDate": "When the action's payout was (or will be) locked/finalized.",
            "ClearedDate": "When the action's payout cleared for payment.",
        },
    },
    "Invoices": {
        "description": "Invoices issued to your partner account for earnings.",
        "docs_url": "https://integrations.impact.com/partner-api-reference/reference/invoices/invoices",
        "columns": {
            "Id": "Unique identifier for the invoice.",
            "CreatedDate": "When the invoice was created.",
            "RecipientId": "Identifier of the invoice recipient.",
            "RecipientName": "Name of the invoice recipient.",
            "Currency": "ISO 4217 currency code of the invoice.",
            "TotalAmount": "Total invoice amount.",
            "TotalVatAmount": "Total VAT included in the invoice.",
            "LineItems": "Per-program line items making up the invoice.",
        },
    },
}
