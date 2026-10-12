from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Height API docs (https://height.notion.site/API-documentation).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
_HEIGHT_DOCS_URL = "https://height.notion.site/API-documentation-643aea5bf01742de9232ed5b8b23a91b"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "A member of your Height workspace.",
        "docs_url": _HEIGHT_DOCS_URL,
        "columns": {
            "id": "The unique ID of the user.",
            "email": "The user's email address.",
            "username": "The user's username.",
            "firstname": "The user's first name.",
            "lastname": "The user's last name.",
            "state": "The account state of the user (for example, enabled or disabled).",
            "access": "The user's access level in the workspace.",
            "createdAt": "When the user was created.",
        },
    },
    "lists": {
        "description": "A list (or smart list) that groups tasks in Height, such as a project or view.",
        "docs_url": _HEIGHT_DOCS_URL,
        "columns": {
            "id": "The unique ID of the list.",
            "name": "The name of the list.",
            "description": "The list's description.",
            "type": "The type of list (for example, list or smartlist).",
            "appType": "The Height app the list belongs to.",
            "key": "The short key used in the list's URL.",
            "url": "The web URL of the list.",
            "createdAt": "When the list was created.",
        },
    },
    "field_templates": {
        "description": "A custom field definition (field template) applied to tasks in Height.",
        "docs_url": _HEIGHT_DOCS_URL,
        "columns": {
            "id": "The unique ID of the field template.",
            "name": "The name of the field template.",
            "type": "The field's data type (for example, text, number, or options).",
            "appType": "The Height app the field template belongs to.",
            "labels": "The set of labels (options) available for a labels-type field.",
            "createdAt": "When the field template was created.",
        },
    },
}
