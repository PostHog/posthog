"""Canonical, documentation-sourced descriptions for Apollo.io endpoints and columns.

Sourced from the official Apollo.io API reference (https://docs.apollo.io/reference). Keyed by the
endpoint names in `settings.py` `APOLLO_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Apollo table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A person saved in your Apollo account — a lead or prospect with contact details and enrichment data.",
        "docs_url": "https://docs.apollo.io/reference/search-for-contacts",
        "columns": {
            "id": "Unique identifier for the contact.",
            "first_name": "Contact's first name.",
            "last_name": "Contact's last name.",
            "name": "Contact's full name.",
            "title": "Contact's job title.",
            "email": "Contact's email address.",
            "email_status": "Verification status of the contact's email.",
            "organization_id": "Identifier of the organization the contact belongs to.",
            "organization_name": "Name of the organization the contact belongs to.",
            "account_id": "Identifier of the account the contact is linked to in Apollo.",
            "linkedin_url": "URL of the contact's LinkedIn profile.",
            "phone_numbers": "List of phone numbers associated with the contact.",
            "city": "City the contact is located in.",
            "state": "State or region the contact is located in.",
            "country": "Country the contact is located in.",
            "created_at": "Time the contact was created in Apollo.",
            "updated_at": "Time the contact was last updated — the cursor used for incremental sync.",
        },
    },
    "accounts": {
        "description": "A company saved in your Apollo account, with firmographic and enrichment data.",
        "docs_url": "https://docs.apollo.io/reference/organization-search",
        "columns": {
            "id": "Unique identifier for the account.",
            "name": "Name of the company.",
            "domain": "Primary web domain of the company.",
            "website_url": "Company's website URL.",
            "phone": "Primary phone number of the company.",
            "industry": "Industry the company operates in.",
            "estimated_num_employees": "Estimated number of employees at the company.",
            "linkedin_url": "URL of the company's LinkedIn page.",
            "city": "City the company's headquarters is located in.",
            "state": "State or region the company's headquarters is located in.",
            "country": "Country the company's headquarters is located in.",
            "owner_id": "Identifier of the Apollo user who owns the account.",
            "created_at": "Time the account was created in Apollo.",
            "updated_at": "Time the account was last updated — the cursor used for incremental sync.",
        },
    },
    "opportunities": {
        "description": "A sales deal tracked in Apollo's CRM, with its stage, value, and associated account.",
        "docs_url": "https://docs.apollo.io/reference/search-for-deals",
        "columns": {
            "id": "Unique identifier for the opportunity.",
            "name": "Name of the opportunity (deal).",
            "amount": "Monetary value of the opportunity.",
            "opportunity_stage_id": "Identifier of the deal stage the opportunity is in.",
            "owner_id": "Identifier of the Apollo user who owns the opportunity.",
            "account_id": "Identifier of the account the opportunity is associated with.",
            "is_closed": "Whether the opportunity has been closed.",
            "is_won": "Whether the opportunity was won.",
            "closed_date": "Date the opportunity was or is expected to be closed.",
            "created_at": "Time the opportunity was created in Apollo.",
            "updated_at": "Time the opportunity was last updated.",
        },
    },
}
