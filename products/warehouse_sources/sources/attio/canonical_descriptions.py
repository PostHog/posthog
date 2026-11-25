"""Canonical, documentation-sourced descriptions for Attio endpoints and columns.

Sourced from the official Attio API reference (https://developers.attio.com/reference). Keyed by
the endpoint names in `settings.py` `ATTIO_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Attio table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "activities": {
        "description": "An activity type defined in the Attio workspace, such as a call or site visit. Lists the type definitions, not the individual activity records.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/activities/list-activities",
        "columns": {
            "id": "Composite identifier for the activity type (workspace and activity id).",
            "activity_id": "Unique identifier for the activity type.",
            "api_slug": "URL-safe slug used to reference the activity type in the API.",
            "singular_noun": "Singular display name of the activity type.",
            "plural_noun": "Plural display name of the activity type.",
            "extends": "The standard schemas this activity type extends.",
            "is_system_activity": "Whether Attio defines the activity type, as opposed to a workspace user.",
            "created_at": "Time at which the activity type was created.",
        },
    },
    "objects": {
        "description": "A system or custom object in the Attio workspace, such as people, companies, or a custom object.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/objects/list-objects",
        "columns": {
            "id": "Composite identifier for the object (workspace and object id).",
            "object_id": "Unique identifier for the object.",
            "api_slug": "Unique snake case slug used to reference the object in the API.",
            "singular_noun": "Singular display name of the object.",
            "plural_noun": "Plural display name of the object.",
            "created_at": "Time at which the object was created.",
        },
    },
    "attributes": {
        "description": "An attribute (field) defined on an Attio object or list, with its type and configuration.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/attributes/list-attributes",
        "columns": {
            "id": "Composite identifier for the attribute (workspace, object or list, and attribute id).",
            "object_id": "Identifier of the object or list the attribute belongs to.",
            "attribute_id": "Unique identifier for the attribute.",
            "target": "Whether the attribute belongs to an object (`objects`) or a list (`lists`).",
            "title": "Display title of the attribute.",
            "description": "Text description of the attribute.",
            "api_slug": "Unique snake case slug used as the key of the attribute's values on records and entries.",
            "type": "Value type of the attribute, such as text, number, select, status, or record-reference.",
            "is_system_attribute": "Whether Attio defines the attribute, as opposed to a workspace user or app.",
            "is_writable": "Whether values of the attribute can be written.",
            "is_required": "Whether new records or entries must have a value for the attribute.",
            "is_unique": "Whether new values of the attribute must be unique.",
            "is_multiselect": "Whether the attribute can hold more than one value.",
            "is_default_value_enabled": "Whether the attribute has a default value.",
            "is_archived": "Whether the attribute is archived.",
            "default_value": "Default value of the attribute.",
            "relationship": "The related attribute, for a two-way record reference.",
            "config": "Type-specific configuration, such as the currency or the allowed record types.",
            "created_at": "Time at which the attribute was created.",
        },
    },
    "select_options": {
        "description": "A select option of a select attribute on an Attio object or list.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/attributes/list-select-options",
        "columns": {
            "id": "Composite identifier for the option (workspace, object or list, attribute, and option id).",
            "object_id": "Identifier of the object or list the attribute belongs to.",
            "attribute_id": "Identifier of the select attribute.",
            "option_id": "Unique identifier for the select option.",
            "target": "Whether the attribute belongs to an object (`objects`) or a list (`lists`).",
            "title": "Display title of the select option.",
            "is_archived": "Whether the select option is archived.",
        },
    },
    "statuses": {
        "description": "A status of a status attribute on an Attio object or list, such as a deal or pipeline stage.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/attributes/list-statuses",
        "columns": {
            "id": "Composite identifier for the status (workspace, object or list, attribute, and status id).",
            "object_id": "Identifier of the object or list the attribute belongs to.",
            "attribute_id": "Identifier of the status attribute.",
            "status_id": "Unique identifier for the status.",
            "target": "Whether the attribute belongs to an object (`objects`) or a list (`lists`).",
            "title": "Display title of the status.",
            "is_archived": "Whether the status is archived.",
            "celebration_enabled": "Whether reaching the status shows a celebration effect in the Attio UI.",
            "target_time_in_status": "Target time for a record to spend in the status, as an ISO 8601 duration.",
        },
    },
    "list_entries": {
        "description": "An entry in an Attio list, linking a parent record to the list with list-specific values.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/entries/list-entries",
        "columns": {
            "id": "Composite identifier for the entry (workspace, list, and entry id).",
            "list_id": "Identifier of the list the entry is in.",
            "entry_id": "Unique identifier for the entry.",
            "parent_record_id": "Identifier of the record that the entry belongs to.",
            "parent_object": "Slug or identifier of the object of the parent record.",
            "entry_values": "The list attribute values stored on the entry, such as its stage, keyed by attribute slug.",
            "created_at": "Time at which the entry was created.",
        },
    },
    "threads": {
        "description": "A thread of comments on an Attio record or list entry.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/threads/list-threads",
        "columns": {
            "id": "Composite identifier for the thread (workspace and thread id).",
            "thread_id": "Unique identifier for the thread.",
            "comments": "The comments in the thread, oldest first. Holds at most 80 comments.",
            "created_at": "Time at which the thread was created.",
        },
    },
    "meetings": {
        "description": "A calendar meeting in Attio, with its participants and linked records.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/meetings/list-meetings",
        "columns": {
            "id": "Composite identifier for the meeting (workspace and meeting id).",
            "meeting_id": "Unique identifier for the meeting.",
            "title": "Title of the meeting.",
            "description": "Description of the meeting.",
            "is_all_day": "Whether the meeting is an all-day event.",
            "start": "When the meeting starts, with its timezone.",
            "end": "When the meeting ends, with its timezone. The end is exclusive.",
            "participants": "The participants of the meeting, with their email address, status, and organizer flag.",
            "linked_records": "The records the meeting is linked to.",
            "created_by_actor": "The actor that created the meeting.",
            "created_at": "Time at which the meeting was created.",
        },
    },
    "call_recordings": {
        "description": "A call recording of an Attio meeting.",
        "docs_url": "https://docs.attio.com/rest-api/endpoint-reference/call-recordings/list-call-recordings",
        "columns": {
            "id": "Composite identifier for the call recording (workspace, meeting, and call recording id).",
            "meeting_id": "Identifier of the meeting the call recording belongs to.",
            "call_recording_id": "Unique identifier for the call recording.",
            "status": "Processing status of the call recording: `processing`, `completed`, or `failed`.",
            "web_url": "URL linking to the call recording in the Attio UI.",
            "created_by_actor": "The actor that created the call recording.",
            "created_at": "Time at which the call recording was created.",
        },
    },
}
