from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://support.gainsight.com/gainsight_nxt/API_and_Developer_Docs"
_COMPANY_DOCS_URL = (
    "https://support.gainsight.com/gainsight_nxt/API_and_Developer_Docs/Company_and_Relationship_API/"
    "Company_API_Documentation"
)
_TIMELINE_DOCS_URL = "https://support.gainsight.com/gainsight_nxt/API_and_Developer_Docs/Timeline_API/Timeline_APIs"

# Curated from the Gainsight NXT API docs. Each tenant adds its own custom fields on top of these,
# which fall through to the LLM enrichment path. Date fields are returned by the API as
# epoch-millisecond integers and normalized to timestamps before loading.
_SHARED_COLUMNS = {
    "Gsid": "Unique Gainsight identifier for the record.",
    "CreatedDate": "When the record was created.",
    "ModifiedDate": "When the record was last modified.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "company": {
        "description": "Customer companies tracked in Gainsight CS, the root object most other records hang off.",
        "docs_url": _COMPANY_DOCS_URL,
        "columns": {
            **_SHARED_COLUMNS,
            "Name": "Company name.",
            "Industry": "Industry the company operates in.",
            "ARR": "Annual recurring revenue for the company.",
            "Employees": "Reported number of employees.",
            "LifecycleInWeeks": "How long the company has been a customer, in weeks.",
            "OriginalContractDate": "Date of the company's original contract.",
            "RenewalDate": "Date the company's contract renews.",
            "Stage": "Lifecycle stage of the company, returned as a dropdown item identifier.",
            "Status": "Status of the company, returned as a dropdown item identifier.",
            "Csm": "Identifier of the assigned customer success manager, looked up against gsuser.",
            "Parentcompany": "Identifier of the parent company, looked up against company.",
        },
    },
    "company_person": {
        "description": "Links a person to a company — the external contacts associated with a customer company.",
        "docs_url": _DOCS_URL,
        "columns": _SHARED_COLUMNS,
    },
    "relationship": {
        "description": (
            "Relationship records, which track a distinct engagement, product, or team within a company "
            "separately from the company itself."
        ),
        "docs_url": _DOCS_URL,
        "columns": _SHARED_COLUMNS,
    },
    "relationship_person": {
        "description": "Links a person to a relationship — the external contacts associated with a relationship.",
        "docs_url": _DOCS_URL,
        "columns": _SHARED_COLUMNS,
    },
    "gsuser": {
        "description": "Gainsight internal users, including the customer success managers assigned to companies.",
        "docs_url": _DOCS_URL,
        "columns": _SHARED_COLUMNS,
    },
    "activity_timeline": {
        "description": (
            "Timeline activities — the logged calls, meetings, emails, and updates recorded against a company "
            "or relationship."
        ),
        "docs_url": _TIMELINE_DOCS_URL,
        "columns": {
            **_SHARED_COLUMNS,
            "contextname": "What the activity was logged against, e.g. Company or Relationship.",
            "GsCompanyId": "Identifier of the company the activity belongs to.",
            "GsRelationshipId": "Identifier of the relationship the activity belongs to, when logged on one.",
            "AuthorId": "Identifier of the Gainsight user who logged the activity.",
            "InternalAttendees": "Internal attendees recorded on the activity.",
            "ExternalAttendees": "External attendees recorded on the activity.",
        },
    },
    "call_to_action": {
        "description": "Calls to Action (CTAs) — the tasks and risks raised against companies and relationships.",
        "docs_url": _DOCS_URL,
        "columns": _SHARED_COLUMNS,
    },
    "cta_group": {
        "description": "Success Plans, which group related Calls to Action toward a customer objective.",
        "docs_url": _DOCS_URL,
        "columns": _SHARED_COLUMNS,
    },
    "email_logs": {
        "description": "Log of emails sent from Gainsight.",
        "docs_url": _DOCS_URL,
        "columns": _SHARED_COLUMNS,
    },
}
