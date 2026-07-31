"""Canonical, documentation-sourced descriptions for Dovetail endpoints and columns.

Sourced from the official Dovetail REST API reference (https://developers.dovetail.com/reference).
Keyed by the resource names in `settings.py` `DOVETAIL_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Dovetail table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Projects": {
        "description": "A Dovetail project - the top-level container for organizing qualitative "
        "research, holding data, docs, highlights, tags, and insights related to a specific "
        "research initiative.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-projects",
        "columns": {
            "id": "Unique identifier for the project.",
            "url": "URL of the project in the Dovetail web app.",
            "title": "Title of the project.",
            "type": "Resource type, always 'project'.",
            "author": "The user who created the project (id and name).",
            "created_at": "Time at which the project was created, in ISO 8601 format.",
            "deleted": "Whether the project has been deleted.",
            "folder": "The folder containing the project, if any (id).",
        },
    },
    "Data": {
        "description": "A piece of research data (interview transcript, note, or other captured "
        "customer feedback) stored in Dovetail. Metadata only - the content body is not included "
        "and must be fetched via the export endpoint.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-data",
        "columns": {
            "id": "Unique identifier for the data entry.",
            "url": "URL of the data entry in the Dovetail web app.",
            "title": "Title of the data entry.",
            "type": "Resource type, always 'data'.",
            "project": "The project the data entry belongs to (id and title).",
            "created_at": "Time at which the data entry was created, in ISO 8601 format.",
            "deleted": "Whether the data entry has been deleted.",
            "folder": "The folder containing the data entry, if any (id).",
        },
    },
    "Docs": {
        "description": "A Dovetail doc - a synthesized research artifact (report, insight, or "
        "written analysis). Metadata only - the document body is not included and must be "
        "fetched via the export endpoint.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-docs",
        "columns": {
            "id": "Unique identifier for the doc.",
            "url": "URL of the doc in the Dovetail web app.",
            "title": "Title of the doc.",
            "type": "Resource type, always 'doc'.",
            "created_at": "Time at which the doc was created, in ISO 8601 format.",
            "folder": "The folder containing the doc, if any (id).",
        },
    },
    "Highlights": {
        "description": "A highlight - a tagged excerpt of a transcript or note captured during "
        "qualitative analysis, optionally categorized with one or more tags.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-highlights",
        "columns": {
            "id": "Unique identifier for the highlight.",
            "url": "URL of the parent note containing this highlight in the Dovetail web app.",
            "note_id": "Identifier of the note (data entry) the highlight belongs to, if any.",
            "tags": "Tags applied to the highlight (id and title for each).",
            "text": "Text content of the highlight excerpt.",
            "type": "Resource type, always 'highlight'.",
            "start_time": "Start timestamp (seconds) of the highlight within its source media, if any.",
            "end_time": "End timestamp (seconds) of the highlight within its source media, if any.",
            "created_at": "Time at which the highlight was created, in ISO 8601 format.",
            "updated_at": "Time at which the highlight was last updated, in ISO 8601 format.",
        },
    },
    "Tags": {
        "description": "A tag used to categorize highlights during qualitative analysis (e.g. "
        "'Usability Issue', 'Feature Request'). Each tag belongs to a specific project.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-tags",
        "columns": {
            "id": "Unique identifier for the tag.",
            "url": "URL of the tag in the Dovetail web app.",
            "title": "Title (label) of the tag.",
            "project_id": "Identifier of the project the tag belongs to.",
            "created_at": "Time at which the tag was created, in ISO 8601 format.",
        },
    },
    "Contacts": {
        "description": "A contact - a research participant or customer tracked in Dovetail's "
        "contact management, with custom field values.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-contacts",
        "columns": {
            "id": "Unique identifier for the contact.",
            "url": "URL of the contact in the Dovetail web app.",
            "name": "Name of the contact.",
            "created_at": "Time at which the contact was created, in ISO 8601 format.",
            "fields": "Custom field values associated with the contact (label, value, and type per field).",
        },
    },
    "Users": {
        "description": "A user (team member) with access to the Dovetail workspace.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-users",
        "columns": {
            "id": "Unique identifier for the user.",
            "url": "URL of the user in the Dovetail web app.",
            "name": "Name of the user.",
            "email": "Email address of the user.",
            "job_title": "Job title of the user, if set.",
            "role": "Workspace role of the user: CONTRIBUTOR, MANAGER, or VIEWER.",
            "workspace_admin": "Whether the user is a workspace administrator.",
            "created_at": "Time at which the user was created, in ISO 8601 format.",
            "updated_at": "Time at which the user was last updated, in ISO 8601 format.",
        },
    },
    "DocComments": {
        "description": "A comment left on a Dovetail doc, aggregated across every doc in the workspace.",
        "docs_url": "https://developers.dovetail.com/reference/get_v1-docs-doc-id-comments",
        "columns": {
            "id": "Unique identifier for the comment.",
            "doc_id": "Identifier of the doc the comment belongs to.",
            "url": "URL of the doc this comment belongs to in the Dovetail web app.",
            "body": "Text content of the comment.",
            "author": "The user who wrote the comment (id and name).",
            "created_at": "Time at which the comment was created, in ISO 8601 format.",
            "updated_at": "Time at which the comment was last updated, in ISO 8601 format.",
        },
    },
}
