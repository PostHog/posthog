from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the Zendesk Sell (Base CRM) Core API docs: https://developer.zendesk.com/api-reference/sales-crm/
# Partial coverage is fine — any endpoint/column not listed falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "People and companies in your Sell account. A contact can be a person or an organization.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/contacts/",
        "columns": {
            "id": "Unique identifier of the contact.",
            "is_organization": "Whether the contact is an organization (true) or a person (false).",
            "name": "Organization name (set when is_organization is true).",
            "first_name": "Contact's first name (for people).",
            "last_name": "Contact's last name (for people).",
            "email": "Primary email address.",
            "phone": "Primary phone number.",
            "owner_id": "Identifier of the user that owns the contact.",
            "created_at": "Time the contact was created, in UTC ISO-8601.",
            "updated_at": "Time the contact was last updated, in UTC ISO-8601.",
        },
    },
    "deals": {
        "description": "Sales opportunities tracked through your pipeline.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/deals/",
        "columns": {
            "id": "Unique identifier of the deal.",
            "name": "Name of the deal.",
            "value": "Monetary value of the deal.",
            "currency": "Currency of the deal value (ISO 4217).",
            "stage_id": "Identifier of the pipeline stage the deal is in.",
            "contact_id": "Identifier of the primary contact for the deal.",
            "owner_id": "Identifier of the user that owns the deal.",
            "hot": "Whether the deal is marked as hot.",
            "created_at": "Time the deal was created, in UTC ISO-8601.",
            "updated_at": "Time the deal was last updated, in UTC ISO-8601.",
        },
    },
    "leads": {
        "description": "Prospects that have not yet been qualified into contacts and deals.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/leads/",
        "columns": {
            "id": "Unique identifier of the lead.",
            "first_name": "Lead's first name.",
            "last_name": "Lead's last name.",
            "organization_name": "Lead's organization name.",
            "status": "Current status of the lead.",
            "email": "Primary email address.",
            "owner_id": "Identifier of the user that owns the lead.",
            "created_at": "Time the lead was created, in UTC ISO-8601.",
            "updated_at": "Time the lead was last updated, in UTC ISO-8601.",
        },
    },
    "tasks": {
        "description": "To-do items associated with contacts, leads, or deals.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/tasks/",
        "columns": {
            "id": "Unique identifier of the task.",
            "content": "Task description.",
            "due_date": "When the task is due.",
            "completed": "Whether the task has been completed.",
            "owner_id": "Identifier of the user that owns the task.",
            "created_at": "Time the task was created, in UTC ISO-8601.",
            "updated_at": "Time the task was last updated, in UTC ISO-8601.",
        },
    },
    "notes": {
        "description": "Free-form notes attached to contacts, leads, or deals.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/notes/",
        "columns": {
            "id": "Unique identifier of the note.",
            "content": "Note text.",
            "resource_type": "Type of resource the note is attached to (contact, lead, or deal).",
            "resource_id": "Identifier of the resource the note is attached to.",
            "created_at": "Time the note was created, in UTC ISO-8601.",
            "updated_at": "Time the note was last updated, in UTC ISO-8601.",
        },
    },
    "calls": {
        "description": "Logged phone calls associated with contacts, leads, or deals.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/calls/",
        "columns": {
            "id": "Unique identifier of the call.",
            "duration": "Call duration in seconds.",
            "phone_number": "Phone number that was called.",
            "outcome_id": "Identifier of the call outcome.",
            "made_at": "When the call was made.",
            "created_at": "Time the call record was created, in UTC ISO-8601.",
        },
    },
    "orders": {
        "description": "Orders placed against a deal, grouping the line items sold.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/orders/",
        "columns": {
            "id": "Unique identifier of the order.",
            "deal_id": "Identifier of the deal the order belongs to.",
            "discount": "Order-level discount percentage.",
            "created_at": "Time the order was created, in UTC ISO-8601.",
            "updated_at": "Time the order was last updated, in UTC ISO-8601.",
        },
    },
    "products": {
        "description": "Catalog of products that can be added to deals as line items.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/products/",
        "columns": {
            "id": "Unique identifier of the product.",
            "name": "Product name.",
            "sku": "Stock keeping unit.",
            "active": "Whether the product is active in the catalog.",
            "created_at": "Time the product was created, in UTC ISO-8601.",
            "updated_at": "Time the product was last updated, in UTC ISO-8601.",
        },
    },
    "users": {
        "description": "Users (agents) in the Zendesk Sell account.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/users/",
        "columns": {
            "id": "Unique identifier of the user.",
            "name": "User's full name.",
            "email": "User's email address.",
            "role": "User's role in the account.",
            "status": "Whether the user is active or inactive.",
            "created_at": "Time the user was created, in UTC ISO-8601.",
        },
    },
    "pipelines": {
        "description": "Sales pipelines that group deal stages.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/pipelines/",
        "columns": {
            "id": "Unique identifier of the pipeline.",
            "name": "Pipeline name.",
        },
    },
    "stages": {
        "description": "Stages within a pipeline that deals move through.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/stages/",
        "columns": {
            "id": "Unique identifier of the stage.",
            "name": "Stage name.",
            "pipeline_id": "Identifier of the pipeline the stage belongs to.",
            "position": "Order of the stage within its pipeline.",
        },
    },
    "tags": {
        "description": "Tags used to label contacts, leads, and deals.",
        "docs_url": "https://developer.zendesk.com/api-reference/sales-crm/resources/tags/",
        "columns": {
            "id": "Unique identifier of the tag.",
            "name": "Tag name.",
            "resource_type": "Type of resource the tag applies to.",
        },
    },
}
