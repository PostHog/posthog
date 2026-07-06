"""Canonical, documentation-sourced descriptions for Attio endpoints and columns.

Sourced from the official Attio API reference (https://developers.attio.com/reference). Keyed by
the endpoint names in `settings.py` `ATTIO_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Attio table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by Attio object records (companies, people, deals, etc.); merged into those entries.
_RECORD_COLUMNS = {
    "id": "Composite identifier for the record (workspace, object, and record id).",
    "record_id": "Unique identifier for the record within its object.",
    "created_at": "Time at which the record was created.",
    "values": "The attribute values stored on the record, keyed by attribute slug.",
    "web_url": "URL linking to the record in the Attio UI.",
}


def _record_columns(**overrides: str) -> dict[str, str]:
    return {**_RECORD_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "companies": {
        "description": "A company record in the Attio CRM.",
        "docs_url": "https://developers.attio.com/reference/post_v2-objects-object-records-query",
        "columns": _record_columns(),
    },
    "people": {
        "description": "A person record in the Attio CRM.",
        "docs_url": "https://developers.attio.com/reference/post_v2-objects-object-records-query",
        "columns": _record_columns(),
    },
    "deals": {
        "description": "A deal record in the Attio CRM, tracking a sales opportunity.",
        "docs_url": "https://developers.attio.com/reference/post_v2-objects-object-records-query",
        "columns": _record_columns(),
    },
    "users": {
        "description": "A user record in the Attio CRM, representing a product user.",
        "docs_url": "https://developers.attio.com/reference/post_v2-objects-object-records-query",
        "columns": _record_columns(),
    },
    "workspaces": {
        "description": "A workspace record in the Attio CRM, representing a customer account or workspace.",
        "docs_url": "https://developers.attio.com/reference/post_v2-objects-object-records-query",
        "columns": _record_columns(),
    },
    "lists": {
        "description": "A list in Attio, used to track records through a pipeline or collection.",
        "docs_url": "https://developers.attio.com/reference/get_v2-lists",
        "columns": {
            "id": "Composite identifier for the list (workspace and list id).",
            "list_id": "Unique identifier for the list.",
            "name": "Display name of the list.",
            "api_slug": "URL-safe slug used to reference the list in the API.",
            "parent_object": "The object type whose records this list tracks.",
            "workspace_access": "The default access level members have to the list.",
            "created_at": "Time at which the list was created.",
        },
    },
    "notes": {
        "description": "A note attached to a record in Attio.",
        "docs_url": "https://developers.attio.com/reference/get_v2-notes",
        "columns": {
            "id": "Composite identifier for the note (workspace and note id).",
            "note_id": "Unique identifier for the note.",
            "parent_object": "The object type the note is attached to.",
            "parent_record_id": "ID of the record the note is attached to.",
            "title": "Title of the note.",
            "content_plaintext": "Plain-text content of the note.",
            "created_by_actor": "The actor (user or system) that created the note.",
            "created_at": "Time at which the note was created.",
        },
    },
    "tasks": {
        "description": "A task in Attio, optionally linked to records and assignees.",
        "docs_url": "https://developers.attio.com/reference/get_v2-tasks",
        "columns": {
            "id": "Composite identifier for the task (workspace and task id).",
            "task_id": "Unique identifier for the task.",
            "content_plaintext": "Plain-text content of the task.",
            "is_completed": "Whether the task has been completed.",
            "deadline_at": "Time by which the task is due.",
            "linked_records": "Records the task is linked to.",
            "assignees": "The actors the task is assigned to.",
            "created_by_actor": "The actor that created the task.",
            "created_at": "Time at which the task was created.",
        },
    },
    "workspace_members": {
        "description": "A member of the Attio workspace.",
        "docs_url": "https://developers.attio.com/reference/get_v2-workspace-members",
        "columns": {
            "id": "Composite identifier for the workspace member (workspace and member id).",
            "workspace_member_id": "Unique identifier for the workspace member.",
            "first_name": "The member's first name.",
            "last_name": "The member's last name.",
            "email_address": "The member's email address.",
            "access_level": "The member's access level in the workspace (admin, member, suspended).",
            "created_at": "Time at which the member was added to the workspace.",
        },
    },
}
