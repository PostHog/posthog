from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Secoda API docs (https://docs.secoda.co/api/reference).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tables": {
        "description": "A table catalogued in Secoda from a connected data integration.",
        "docs_url": "https://docs.secoda.co/api/reference/tables",
        "columns": {
            "id": "The unique ID of the table.",
            "title": "The table name.",
            "description": "The table's documented description.",
            "integration": "The ID of the integration the table was ingested from.",
            "database": "The database the table belongs to.",
            "schema": "The schema the table belongs to.",
            "url": "The Secoda URL for the table.",
            "created_at": "When the table was first catalogued in Secoda.",
            "updated_at": "When the table's metadata was last updated.",
        },
    },
    "columns": {
        "description": "A column belonging to a catalogued table in Secoda.",
        "docs_url": "https://docs.secoda.co/api/reference/columns",
        "columns": {
            "id": "The unique ID of the column.",
            "title": "The column name.",
            "description": "The column's documented description.",
            "type": "The column's data type.",
            "parent": "The ID of the table the column belongs to.",
            "integration": "The ID of the integration the column was ingested from.",
            "created_at": "When the column was first catalogued in Secoda.",
            "updated_at": "When the column's metadata was last updated.",
        },
    },
    "collections": {
        "description": "A collection used to group and organise resources in Secoda.",
        "docs_url": "https://docs.secoda.co/api/reference/collections",
        "columns": {
            "id": "The unique ID of the collection.",
            "title": "The collection name.",
            "description": "The collection's description.",
            "owners": "The users who own the collection.",
            "created_at": "When the collection was created.",
            "updated_at": "When the collection was last updated.",
        },
    },
    "users": {
        "description": "A user in the Secoda workspace.",
        "docs_url": "https://docs.secoda.co/api/reference/users",
        "columns": {
            "id": "The unique ID of the user.",
            "email": "The user's email address.",
            "first_name": "The user's first name.",
            "last_name": "The user's last name.",
            "display_name": "The user's display name.",
            "role": "The user's workspace role.",
            "is_active": "Whether the user account is active.",
        },
    },
    "groups": {
        "description": "A user group (team) in the Secoda workspace.",
        "docs_url": "https://docs.secoda.co/api/reference/groups",
        "columns": {
            "id": "The unique ID of the group.",
            "name": "The group name.",
            "icon": "The group's icon.",
            "users": "The users that belong to the group.",
            "created_at": "When the group was created.",
        },
    },
    "tags": {
        "description": "A tag used to label and categorise resources in Secoda.",
        "docs_url": "https://docs.secoda.co/api/reference/tags",
        "columns": {
            "id": "The unique ID of the tag.",
            "name": "The tag name.",
            "color": "The tag's display colour.",
            "created_at": "When the tag was created.",
        },
    },
}
