from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the My Hours API v1.1 docs (https://documenter.getpostman.com/view/8879268/TVmV4YYU)
# and the My Hours connector reference. Partial coverage is fine — uncovered columns fall back to
# LLM enrichment.
_DOCS_URL = "https://documenter.getpostman.com/view/8879268/TVmV4YYU"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clients": {
        "description": "A client (customer) that projects and time logs can be billed against.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "The unique ID of the client.",
            "name": "The client's name.",
            "contactName": "The client's primary contact person.",
            "contactEmail": "The client's contact email address.",
            "customId": "A user-defined external identifier for the client.",
            "archived": "Whether the client has been archived.",
            "dateArchived": "When the client was archived, if applicable.",
        },
    },
    "projects": {
        "description": "A project that time is tracked against, optionally linked to a client.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "The unique ID of the project.",
            "name": "The project name.",
            "clientId": "The ID of the client this project belongs to.",
            "clientName": "The name of the client this project belongs to.",
            "customId": "A user-defined external identifier for the project.",
            "billable": "Whether time logged to the project is billable by default.",
            "budgetType": "The project's budget type.",
            "budgetValue": "The configured budget amount for the project.",
            "budgetSpent": "How much of the project's budget has been used.",
            "budgetSpentPercentage": "The share of the project's budget used, as a percentage.",
            "totalTimeLogged": "Total time logged to the project, in seconds.",
            "billableTimeLogged": "Billable time logged to the project, in seconds.",
            "totalAmount": "Total billable amount accrued on the project.",
            "totalCost": "Total labor cost accrued on the project.",
            "laborCost": "Labor cost accrued on the project.",
            "roundType": "How logged time is rounded on the project.",
            "roundInterval": "The rounding interval applied to logged time.",
            "dateCreated": "When the project was created.",
            "archived": "Whether the project has been archived.",
            "dateArchived": "When the project was archived, if applicable.",
        },
    },
    "tags": {
        "description": "A label used to categorise time logs.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "The unique ID of the tag.",
            "name": "The tag name.",
            "hexColor": "The tag's display colour, as a hex code.",
            "archived": "Whether the tag has been archived.",
            "dateArchived": "When the tag was archived, if applicable.",
        },
    },
    "users": {
        "description": "A member of the My Hours account (team member) who logs time.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "The unique ID of the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "active": "Whether the user is currently active.",
            "accountOwner": "Whether the user owns the account.",
            "admin": "Whether the user has administrator privileges.",
            "isProjectManager": "Whether the user is a project manager.",
            "roleType": "The user's role type.",
            "rate": "The user's labor rate.",
            "billableRate": "The user's billable rate.",
            "customId": "A user-defined external identifier for the user.",
            "archived": "Whether the user has been archived.",
            "dateArchived": "When the user was archived, if applicable.",
        },
    },
}
