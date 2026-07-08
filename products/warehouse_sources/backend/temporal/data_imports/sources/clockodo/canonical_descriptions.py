from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the official Clockodo API documentation
# (https://www.clockodo.com/en/api/). Partial coverage is fine — anything not listed falls back
# to LLM enrichment, which is given the docs_url and column data types.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "customers": {
        "description": "Customers (companies/clients) that work is tracked against.",
        "docs_url": "https://www.clockodo.com/en/api/customers/",
        "columns": {
            "id": "Unique identifier of the customer.",
            "name": "Name of the customer.",
            "number": "Free-text customer number.",
            "active": "Whether the customer is active.",
            "billable_default": "Default billability for new projects of this customer.",
            "note": "Free-text note on the customer.",
        },
    },
    "projects": {
        "description": "Projects belonging to customers; the unit time entries are booked to.",
        "docs_url": "https://www.clockodo.com/en/api/projects/",
        "columns": {
            "id": "Unique identifier of the project.",
            "name": "Name of the project.",
            "number": "Free-text project number.",
            "customers_id": "Identifier of the customer this project belongs to.",
            "active": "Whether the project is active.",
            "billable_default": "Default billability for new entries of this project.",
            "budget_money": "Money budget for the project.",
            "completed": "Whether the project has been marked completed.",
        },
    },
    "services": {
        "description": "Services (types of work) that can be booked on time entries.",
        "docs_url": "https://www.clockodo.com/en/api/services/",
        "columns": {
            "id": "Unique identifier of the service.",
            "name": "Name of the service.",
            "number": "Free-text service number.",
            "active": "Whether the service is active.",
        },
    },
    "lumpsum_services": {
        "description": "Lump-sum (flat-rate) services that can be booked as fixed-price entries.",
        "docs_url": "https://www.clockodo.com/en/api/lumpsum-services/",
        "columns": {
            "id": "Unique identifier of the lump-sum service.",
            "name": "Name of the lump-sum service.",
            "price": "Flat-rate price of the service.",
            "active": "Whether the lump-sum service is active.",
        },
    },
    "users": {
        "description": "Co-workers (users) in the Clockodo account.",
        "docs_url": "https://www.clockodo.com/en/api/users/",
        "columns": {
            "id": "Unique identifier of the user.",
            "name": "Display name of the user.",
            "email": "Email address of the user.",
            "role": "Role of the user in the account.",
            "active": "Whether the user is active.",
            "number": "Free-text personnel number.",
        },
    },
    "teams": {
        "description": "Teams that users are grouped into.",
        "docs_url": "https://www.clockodo.com/en/api/teams/",
        "columns": {
            "id": "Unique identifier of the team.",
            "name": "Name of the team.",
        },
    },
    "surcharges": {
        "description": "Surcharge rules (e.g. night/weekend premiums) configured in the account.",
        "docs_url": "https://www.clockodo.com/en/api/surcharges/",
        "columns": {
            "id": "Unique identifier of the surcharge rule.",
            "name": "Name of the surcharge rule.",
        },
    },
    "entries": {
        "description": "Time and lump-sum entries — the individual tracked records of work.",
        "docs_url": "https://www.clockodo.com/en/api/entries/",
        "columns": {
            "id": "Unique identifier of the entry.",
            "customers_id": "Identifier of the customer the entry is booked to.",
            "projects_id": "Identifier of the project the entry is booked to.",
            "services_id": "Identifier of the service the entry is booked to.",
            "users_id": "Identifier of the user who created the entry.",
            "billable": "Billability of the entry.",
            "text": "Free-text description of the entry.",
            "time_since": "Start time of the entry (ISO 8601).",
            "time_until": "End time of the entry (ISO 8601).",
            "duration": "Duration of the entry in seconds.",
            "time_insert": "Time the entry was created (ISO 8601).",
            "time_last_change": "Time the entry was last modified (ISO 8601).",
        },
    },
}
