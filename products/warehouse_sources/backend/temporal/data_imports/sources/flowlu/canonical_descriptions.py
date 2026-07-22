from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Flowlu REST API docs (https://developers.flowlu.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A CRM account in Flowlu — an organization or contact you do business with.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the account.",
            "name": "The account's display name.",
            "type": "The account type (organization or contact).",
        },
    },
    "leads": {
        "description": "A CRM opportunity (Flowlu's API keeps the legacy 'lead' entity name) tracked through a sales pipeline.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the opportunity.",
            "name": "The opportunity's name.",
        },
    },
    "pipelines": {
        "description": "A CRM sales pipeline that opportunities move through.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the pipeline.",
            "name": "The pipeline's name.",
        },
    },
    "tasks": {
        "description": "A task in Flowlu's task management module.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the task.",
            "name": "The task's title.",
        },
    },
    "projects": {
        "description": "A project in Flowlu's project management module.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the project.",
            "name": "The project's name.",
        },
    },
    "invoices": {
        "description": "An invoice issued to a customer in Flowlu's finance module.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the invoice.",
        },
    },
    "estimates": {
        "description": "An estimate (quote) prepared for a customer in Flowlu's finance module.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the estimate.",
        },
    },
    "customer_payments": {
        "description": "A payment received from a customer, typically applied against an invoice.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the payment.",
        },
    },
    "transactions": {
        "description": "A money transaction (income or expense) recorded in Flowlu's finance module.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the transaction.",
        },
    },
    "agile_issues": {
        "description": "An issue (user story, task, or bug) on a Flowlu agile board.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the issue.",
            "name": "The issue's title.",
        },
    },
    "agile_sprints": {
        "description": "A sprint within a Flowlu agile project.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the sprint.",
            "name": "The sprint's name.",
        },
    },
    "timesheets": {
        "description": "A time-tracking entry logged against tasks or projects in Flowlu.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the timesheet entry.",
        },
    },
    "products": {
        "description": "A product or service from Flowlu's product catalog.",
        "docs_url": "https://developers.flowlu.com",
        "columns": {
            "id": "The unique ID of the product.",
            "name": "The product's name.",
        },
    },
}
