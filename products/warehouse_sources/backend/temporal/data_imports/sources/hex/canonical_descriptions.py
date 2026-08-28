from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://learn.hex.tech/docs/api-integrations/api/reference"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A Hex project (notebook or app) in the workspace, including ownership, status, categories, usage analytics, and schedule metadata.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique UUID for the Hex project.",
            "title": "Title of the project.",
            "description": "Description of the project, if set.",
            "type": "Type of the project (e.g. PROJECT or COMPONENT).",
            "creator": "User who created the project (object with the creator's email).",
            "owner": "User who owns the project (object with the owner's email).",
            "status": "Workspace-defined project status, if set (object with the status name).",
            "categories": "Workspace-defined categories assigned to the project.",
            "reviews": "Whether reviews are required for the project.",
            "analytics": "Usage analytics for the project: published app views over trailing windows, last viewed time, and when published results were last updated.",
            "lastEditedAt": "UTC timestamp of when the project was last edited.",
            "lastPublishedAt": "UTC timestamp of when the project was last published, if ever.",
            "createdAt": "UTC timestamp of when the project was created.",
            "archivedAt": "UTC timestamp of when the project was archived, if archived.",
            "trashedAt": "UTC timestamp of when the project was moved to trash, if trashed.",
            "schedules": "Configured run schedules for the project (cadence, timezone, and enablement).",
        },
    },
    "project_runs": {
        "description": "An execution of a published Hex project triggered via the API, a schedule, or an app refresh, with its status and timing.",
        "docs_url": _DOCS_URL,
        "columns": {
            "projectId": "UUID of the Hex project this run belongs to.",
            "projectVersion": "Version of the project that was run.",
            "runId": "Unique UUID for the run.",
            "runUrl": "URL to view the run in Hex.",
            "status": "Current status of the run (PENDING, RUNNING, ERRORED, COMPLETED, KILLED, or UNABLE_TO_ALLOCATE_KERNEL).",
            "runTrigger": "How the run was triggered: API, SCHEDULED, or APP_REFRESH.",
            "startTime": "UTC timestamp of when the run started.",
            "endTime": "UTC timestamp of when the run finished.",
            "elapsedTime": "Total elapsed time for the run in milliseconds.",
            "traceId": "Trace ID for correlating the run with Hex support.",
            "notifications": "Notification recipients configured for the run.",
        },
    },
    "users": {
        "description": "A member of the Hex workspace with their role and last login time.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique UUID for the user.",
            "name": "Display name of the user, if set.",
            "email": "Email address of the user.",
            "role": "Workspace role of the user (e.g. ADMIN, EDITOR, MEMBER, GUEST).",
            "lastLoginDate": "UTC timestamp of the user's most recent login, if any.",
        },
    },
    "groups": {
        "description": "A permission group in the Hex workspace, used to manage access to projects and collections.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique UUID for the group.",
            "name": "Name of the group.",
            "createdAt": "UTC timestamp of when the group was created.",
        },
    },
    "collections": {
        "description": "A collection in the Hex workspace, used to organize and share sets of projects.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique UUID for the collection.",
            "name": "Name of the collection.",
            "description": "Description of the collection.",
            "creator": "User who created the collection (object with the creator's id and email).",
            "sharing": "Sharing configuration for the collection (users, groups, and workspace access).",
        },
    },
}
