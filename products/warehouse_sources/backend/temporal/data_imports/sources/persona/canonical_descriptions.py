from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the public Persona API docs (https://docs.withpersona.com/reference). Column names use
# the snake_case form the warehouse stores after normalizing Persona's kebab-case attributes.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "inquiries": {
        "description": "An individual identity verification session a person goes through, tracking its status from creation to approval or decline.",
        "docs_url": "https://docs.withpersona.com/reference/inquiries",
        "columns": {
            "id": "Unique identifier for the inquiry (prefixed `inq_`).",
            "status": "Current state of the inquiry (e.g. created, pending, completed, approved, declined, expired).",
            "reference_id": "Your own identifier for the person, set when the inquiry was created.",
            "created_at": "Timestamp when the inquiry was created.",
            "started_at": "Timestamp when the person began the inquiry flow.",
            "completed_at": "Timestamp when the person completed the inquiry flow.",
            "expired_at": "Timestamp when the inquiry expired, if it did.",
            "name_first": "First name collected or verified during the inquiry.",
            "name_last": "Last name collected or verified during the inquiry.",
            "birthdate": "Date of birth collected or verified during the inquiry.",
        },
    },
    "accounts": {
        "description": "A persistent record of an individual, grouping all of their inquiries, verifications, and other activity over time.",
        "docs_url": "https://docs.withpersona.com/reference/accounts",
        "columns": {
            "id": "Unique identifier for the account (prefixed `acc_`).",
            "reference_id": "Your own identifier associated with this account.",
            "created_at": "Timestamp when the account was created.",
            "updated_at": "Timestamp when the account was last updated.",
        },
    },
    "cases": {
        "description": "A manual review workflow used to investigate and resolve flagged inquiries, accounts, or transactions.",
        "docs_url": "https://docs.withpersona.com/reference/cases",
        "columns": {
            "id": "Unique identifier for the case (prefixed `case_`).",
            "status": "Current state of the case (e.g. open, in progress, resolved).",
            "created_at": "Timestamp when the case was created.",
            "updated_at": "Timestamp when the case was last updated.",
            "resolved_at": "Timestamp when the case was resolved, if it was.",
        },
    },
    "transactions": {
        "description": "A record of a transaction evaluated by Persona, used for transaction monitoring and fraud/AML analysis.",
        "docs_url": "https://docs.withpersona.com/reference/transactions",
        "columns": {
            "id": "Unique identifier for the transaction (prefixed `txn_`).",
            "status": "Current state of the transaction.",
            "created_at": "Timestamp when the transaction was created.",
            "updated_at": "Timestamp when the transaction was last updated.",
        },
    },
    "events": {
        "description": "An append-only audit log of everything that happened in your Persona account (inquiry created, verification passed, case resolved, etc.).",
        "docs_url": "https://docs.withpersona.com/reference/events",
        "columns": {
            "id": "Unique identifier for the event (prefixed `evt_`).",
            "name": "The event type (e.g. inquiry.created, verification.passed).",
            "created_at": "Timestamp when the event occurred.",
        },
    },
    "inquiry_templates": {
        "description": "A reusable configuration that defines the steps, checks, and branding of an inquiry flow.",
        "docs_url": "https://docs.withpersona.com/reference/inquiry-templates",
        "columns": {
            "id": "Unique identifier for the inquiry template (prefixed `itmpl_`).",
            "status": "Whether the template is active or archived.",
            "created_at": "Timestamp when the template was created.",
            "updated_at": "Timestamp when the template was last updated.",
        },
    },
}
