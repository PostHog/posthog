"""Canonical, documentation-sourced descriptions for Hyros endpoints and columns.

Sourced from the official Hyros REST API reference (https://api-docs.hyros.com). Keyed by the
resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Hyros table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Leads": {
        "description": "A person Hyros has attributed to a source, with their tags, stage and first/last touch attribution.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "id": "Unique identifier for the lead.",
            "email": "Email address of the lead.",
            "creationDate": "Date the lead joined, in ISO 8601.",
            "lastUpdatedDate": "Date the lead was last updated (tag, stage, or attribution change).",
            "tags": "Tags currently applied to the lead.",
            "ips": "IP addresses associated with the lead.",
            "phoneNumbers": "Phone numbers associated with the lead.",
            "firstName": "Lead's first name.",
            "lastName": "Lead's last name.",
            "currentStage": "Most recent stage applied to the lead, with its name and assignment date.",
            "firstSource": "First attributed source that brought in the lead.",
            "lastSource": "Last attributed source that brought in the lead.",
            "originLead": "The origin lead this lead was merged into, when applicable.",
            "adOptimizationConsent": "Consent status for using this lead in ad platform optimization.",
        },
    },
    "Sales": {
        "description": "A sale attributed to a lead, with pricing, refund state, and first/last touch attribution.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "id": "Unique identifier for the sale.",
            "orderId": "Identifier of the order this sale belongs to.",
            "creationDate": "Date the sale was created.",
            "refundDate": "Date the sale was refunded, present only when refunded.",
            "qualified": "Whether the sale is qualified.",
            "score": "Attribution score of the sale.",
            "recurring": "Whether the sale is part of a recurring subscription.",
            "quantity": "Quantity of the product sold.",
            "lead": "The lead this sale is attributed to.",
            "firstSource": "First attributed source for this sale's lead.",
            "lastSource": "Last attributed source for this sale's lead.",
            "price": "Price details of the sale, including currency, discount and refunded amount.",
            "product": "Product sold in this sale.",
        },
    },
    "Calls": {
        "description": "A phone call attributed to a lead, with its qualification state and attribution.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "id": "Unique identifier for the call.",
            "tag": "Product tag associated with the call.",
            "qualified": "Deprecated. Whether the call was qualified. Use `state` instead.",
            "name": "Name of the call.",
            "externalId": "Identifier from the external integration that created the call.",
            "score": "Attribution score of the call.",
            "creationDate": "Date the call was processed.",
            "state": "Qualification state of the call (qualified, unqualified, cancelled, no show).",
            "lead": "The lead this call is attributed to.",
            "firstSource": "First attributed source for this call's lead.",
            "lastSource": "Last attributed source for this call's lead.",
        },
    },
    "Subscriptions": {
        "description": "A recurring subscription attributed to a lead, with its billing state and attribution.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "id": "Unique identifier for the subscription.",
            "startDate": "Date the subscription started.",
            "endDate": "Date the subscription ended.",
            "cancelAtDate": "Date the subscription is scheduled to cancel.",
            "trialStartDate": "Date the subscription's trial period started.",
            "trialEndDate": "Date the subscription's trial period ended.",
            "price": "Recurring price of the subscription.",
            "status": "Current billing status of the subscription.",
            "periodicity": "Billing interval of the subscription.",
            "planId": "Identifier of the plan the subscription is on.",
            "tag": "Product tag associated with the subscription.",
            "name": "Name of the subscription.",
            "lead": "The lead this subscription is attributed to.",
            "firstSource": "First attributed source for this subscription's lead.",
            "lastSource": "Last attributed source for this subscription's lead.",
        },
    },
    "Sources": {
        "description": "A traffic source Hyros tracks, either organic or tied to an ad platform account.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "name": "Name of the source.",
            "tag": 'Unique tag identifying the source (e.g. "@facebook-adset").',
            "disregarded": "Whether the source is disregarded when attributing a sale.",
            "organic": "Whether the source is marked as organic.",
            "adSource": "Underlying ad platform source (id and platform), when the source is ad-driven.",
            "creationDate": "Creation date of the source, as epoch milliseconds.",
        },
    },
    "Tags": {
        "description": "A tag created in Hyros, with the count of leads currently carrying it.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "name": "Name of the tag.",
            "amount": "Number of leads currently carrying this tag.",
        },
    },
    "Keywords": {
        "description": "A keyword tracked against a Google Ads ad group.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "id": "Unique identifier for the keyword.",
            "name": "Text of the keyword.",
            "adGroupId": "Identifier of the Google Ads ad group the keyword belongs to.",
            "adGroupName": "Name of the Google Ads ad group the keyword belongs to.",
        },
    },
    "Stages": {
        "description": "A lead stage defined in the account, with the count of leads currently in it.",
        "docs_url": "https://api-docs.hyros.com",
        "columns": {
            "name": "Name of the stage.",
            "amount": "Number of leads currently in this stage.",
        },
    },
}
