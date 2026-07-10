from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the PartnerStack Vendor API v2 docs (https://docs.partnerstack.com/reference).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "partnerships": {
        "description": "A partner enrolled in your PartnerStack program, including their profile and enrolment details.",
        "docs_url": "https://docs.partnerstack.com/reference/get_v2-partnerships",
        "columns": {
            "key": "The unique key of the partnership.",
            "email": "The partner's email address.",
            "first_name": "The partner's first name.",
            "last_name": "The partner's last name.",
            "company_name": "The partner's company name.",
            "group": "The partner group the partnership belongs to.",
            "stats": "Aggregate performance stats for the partnership.",
            "created": "When the partnership was created (epoch milliseconds).",
            "updated_at": "When the partnership was last updated (epoch milliseconds).",
        },
    },
    "customers": {
        "description": "A customer referred through your PartnerStack program and attributed to a partner.",
        "docs_url": "https://docs.partnerstack.com/reference/get_v2-customers",
        "columns": {
            "key": "The unique key of the customer.",
            "name": "The customer's name.",
            "email": "The customer's email address.",
            "provider_key": "The customer's identifier in your own system.",
            "partnership": "The partnership the customer is attributed to.",
            "created": "When the customer was created (epoch milliseconds).",
            "updated_at": "When the customer was last updated (epoch milliseconds).",
        },
    },
    "deals": {
        "description": "A deal submitted or attributed within your PartnerStack program.",
        "docs_url": "https://docs.partnerstack.com/reference/get_v2-deals",
        "columns": {
            "key": "The unique key of the deal.",
            "name": "The name of the deal.",
            "stage": "The current stage of the deal.",
            "amount": "The monetary value of the deal.",
            "currency": "The currency of the deal amount.",
            "partnership": "The partnership the deal is attributed to.",
            "created": "When the deal was created (epoch milliseconds).",
            "updated_at": "When the deal was last updated (epoch milliseconds).",
        },
    },
    "leads": {
        "description": "A lead submitted by a partner in your PartnerStack program.",
        "docs_url": "https://docs.partnerstack.com/reference/get_v2-leads",
        "columns": {
            "key": "The unique key of the lead.",
            "name": "The lead's name.",
            "email": "The lead's email address.",
            "company_name": "The lead's company name.",
            "partnership": "The partnership the lead is attributed to.",
            "created": "When the lead was created (epoch milliseconds).",
            "updated_at": "When the lead was last updated (epoch milliseconds).",
        },
    },
}
