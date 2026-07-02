from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated, documentation-sourced descriptions for Agile CRM's well-known tables. Keyed by the schema
# name returned by `get_schemas` (matching the `ENDPOINTS` catalog). Partial coverage is fine — any
# missing table or column falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "People stored in Agile CRM (contacts of type PERSON), with their properties, tags and score.",
        "docs_url": "https://github.com/agilecrm/rest-api#contacts-api",
        "columns": {
            "id": "Unique identifier for the contact.",
            "type": "Contact type — PERSON for contacts.",
            "created_time": "Unix epoch timestamp of when the contact was created.",
            "updated_time": "Unix epoch timestamp of when the contact was last updated.",
            "star_value": "Star rating (0-5) assigned to the contact.",
            "lead_score": "Lead score assigned to the contact.",
            "tags": "Tags applied to the contact.",
            "properties": "Custom and system properties (name, email, phone, etc.) of the contact.",
            "owner_id": "Identifier of the Agile CRM user who owns the contact.",
        },
    },
    "companies": {
        "description": "Companies stored in Agile CRM (contacts of type COMPANY).",
        "docs_url": "https://github.com/agilecrm/rest-api#contacts-api",
        "columns": {
            "id": "Unique identifier for the company.",
            "type": "Contact type — COMPANY for companies.",
            "created_time": "Unix epoch timestamp of when the company was created.",
            "updated_time": "Unix epoch timestamp of when the company was last updated.",
            "tags": "Tags applied to the company.",
            "properties": "Custom and system properties of the company.",
            "owner_id": "Identifier of the Agile CRM user who owns the company.",
        },
    },
    "deals": {
        "description": "Deals (opportunities) tracked in the Agile CRM sales pipeline.",
        "docs_url": "https://github.com/agilecrm/rest-api#deals-api",
        "columns": {
            "id": "Unique identifier for the deal.",
            "name": "Name of the deal.",
            "expected_value": "Expected monetary value of the deal.",
            "probability": "Probability (percentage) of the deal closing.",
            "milestone": "Current milestone (stage) of the deal in its pipeline.",
            "pipeline_id": "Identifier of the pipeline the deal belongs to.",
            "close_date": "Unix epoch timestamp of the deal's expected close date.",
            "created_time": "Unix epoch timestamp of when the deal was created.",
            "owner_id": "Identifier of the Agile CRM user who owns the deal.",
        },
    },
    "tasks": {
        "description": "Tasks created in Agile CRM and assigned to users or contacts.",
        "docs_url": "https://github.com/agilecrm/rest-api#tasks-api",
        "columns": {
            "id": "Unique identifier for the task.",
            "subject": "Subject / title of the task.",
            "type": "Task type (e.g. CALL, EMAIL, FOLLOW_UP).",
            "priority_type": "Priority of the task (HIGH, NORMAL, LOW).",
            "status": "Status of the task (e.g. YET_TO_START, IN_PROGRESS, COMPLETED).",
            "due": "Unix epoch timestamp of the task's due date.",
            "created_time": "Unix epoch timestamp of when the task was created.",
            "owner_id": "Identifier of the Agile CRM user who owns the task.",
        },
    },
    "events": {
        "description": "Calendar events scheduled in Agile CRM.",
        "docs_url": "https://github.com/agilecrm/rest-api#events-api",
        "columns": {
            "id": "Unique identifier for the event.",
            "title": "Title of the event.",
            "start": "Unix epoch timestamp of the event start time.",
            "end": "Unix epoch timestamp of the event end time.",
            "is_event_starts_today": "Whether the event starts today.",
            "color": "Display color of the event.",
            "created_time": "Unix epoch timestamp of when the event was created.",
        },
    },
}
