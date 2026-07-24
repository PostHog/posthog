from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://app.glassfrog.com/api/v3/docs"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "assignments": {
        "description": "An assignment of a person to a role, optionally with a focus.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the assignment.",
            "election": "Date the person was elected into the role, for elected roles.",
            "exclude_from_meetings": "Whether this assignment is excluded from circle meetings.",
            "focus": "The focus of the assignment when a role is filled with a specific focus.",
            "links": "Identifiers of the related person and role.",
        },
    },
    "checklist_items": {
        "description": "A recurring checklist item reviewed in a circle's tactical meetings.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the checklist item.",
            "description": "Text of the checklist item.",
            "frequency": "How often the item is reviewed (e.g. Weekly, Monthly).",
            "global": "Whether the item applies to all circles in the organization.",
            "link": "URL associated with the checklist item, if any.",
            "links": "Identifiers of the related circle and role.",
        },
    },
    "circles": {
        "description": "A circle (team) in the organization's governance structure.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the circle.",
            "name": "Name of the circle.",
            "short_name": "Abbreviated name of the circle.",
            "strategy": "The circle's strategy statement, if defined.",
            "organization_id": "Identifier of the organization the circle belongs to.",
            "links": "Identifiers of related resources: roles, policies, domain, and supported role.",
        },
    },
    "custom_fields": {
        "description": "A custom field attached to a role.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the custom field.",
            "field_name": "Name of the custom field.",
            "field_value": "Value of the custom field.",
            "links": "Identifier of the role the custom field is attached to.",
        },
    },
    "metrics": {
        "description": "A metric reported in a circle's tactical meetings.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the metric.",
            "description": "Text describing the metric.",
            "frequency": "How often the metric is reported (e.g. Weekly, Monthly).",
            "global": "Whether the metric applies to all circles in the organization.",
            "link": "URL associated with the metric, if any.",
            "role_name": "Name of the role responsible for reporting the metric.",
            "links": "Identifiers of the related circle and role.",
        },
    },
    "people": {
        "description": "A person (member) in the organization.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the person.",
            "name": "Full name of the person.",
            "email": "Email address of the person.",
            "external_id": "External identifier for the person, if set by the organization.",
            "tag_names": "Tags applied to the person.",
            "settings": "Per-person settings.",
            "links": "Identifiers of the circles the person belongs to and their organizations.",
        },
    },
    "projects": {
        "description": "A project tracked by a circle or role.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the project.",
            "description": "Text describing the project.",
            "status": "Current status of the project (e.g. Current, Future, Waiting, Done).",
            "waiting_on_who": "Who the project is waiting on, when status is Waiting.",
            "waiting_on_what": "What the project is waiting on, when status is Waiting.",
            "link": "URL associated with the project, if any.",
            "value": "Relative value rating assigned to the project.",
            "effort": "Relative effort rating assigned to the project.",
            "roi": "Value/effort ratio computed from the ratings.",
            "private_to_circle": "Whether the project is only visible inside its circle.",
            "created_at": "When the project was created.",
            "archived_at": "When the project was archived, if it has been.",
            "type": "Type of the project.",
            "links": "Identifiers of the related role, person, and circle.",
        },
    },
    "roles": {
        "description": "A role defined in the organization's governance structure.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier for the role.",
            "name": "Name of the role.",
            "is_core": "Whether this is a core role (e.g. Lead Link, Secretary, Facilitator).",
            "purpose": "The role's purpose statement.",
            "elected_until": "End date of the current election term, for elected roles.",
            "organization_id": "Identifier of the organization the role belongs to.",
            "tag_names": "Tags applied to the role.",
            "links": "Identifiers of related resources: circle, supporting circle, domains, accountabilities, and people filling the role.",
        },
    },
}
