"""Canonical, documentation-sourced descriptions for Wrike endpoints and columns.

Sourced from the official Wrike REST API v4 reference (https://developers.wrike.com/). Keyed by the
endpoint names in `settings.py` `WRIKE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Wrike table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tasks": {
        "description": "A task in Wrike — a unit of work with an assignee, status, and dates.",
        "docs_url": "https://developers.wrike.com/api/v4/tasks/",
        "columns": {
            "id": "Unique identifier for the task.",
            "title": "The task's title.",
            "description": "The task's description.",
            "status": "Workflow status of the task (e.g. Active, Completed, Deferred, Cancelled).",
            "importance": "Priority of the task (High, Normal, or Low).",
            "createdDate": "Time at which the task was created.",
            "updatedDate": "Time at which the task was last updated.",
            "completedDate": "Time at which the task was completed, if applicable.",
            "dates": "The task's scheduling dates (start, due, duration).",
            "responsibleIds": "IDs of the contacts responsible for the task.",
            "authorIds": "IDs of the contacts who created the task.",
            "parentIds": "IDs of the parent folders/projects containing the task.",
            "permalink": "Link to open the task in the Wrike web app.",
        },
    },
    "folders": {
        "description": "A folder or project in Wrike that organizes tasks and other folders.",
        "docs_url": "https://developers.wrike.com/api/v4/folders-projects/",
        "columns": {
            "id": "Unique identifier for the folder.",
            "title": "The folder's title.",
            "description": "The folder's description.",
            "scope": "Scope of the folder (e.g. WsFolder, RbFolder).",
            "childIds": "IDs of child folders contained within this folder.",
            "parentIds": "IDs of the parent folders containing this folder.",
            "project": "Project details if the folder is a project (status, owners, dates).",
            "color": "Color assigned to the folder.",
            "permalink": "Link to open the folder in the Wrike web app.",
        },
    },
    "contacts": {
        "description": "A contact in Wrike — a user or group within the account.",
        "docs_url": "https://developers.wrike.com/api/v4/contacts/",
        "columns": {
            "id": "Unique identifier for the contact.",
            "firstName": "The contact's first name.",
            "lastName": "The contact's last name.",
            "type": "Type of contact (Person or Group).",
            "profiles": "Profiles describing the contact's email and account roles.",
            "avatarUrl": "URL of the contact's avatar image.",
            "timezone": "The contact's time zone.",
            "locale": "The contact's locale.",
            "deleted": "Whether the contact has been deleted.",
        },
    },
    "workflows": {
        "description": "A workflow in Wrike defining the set of statuses tasks can move through.",
        "docs_url": "https://developers.wrike.com/api/v4/workflows/",
        "columns": {
            "id": "Unique identifier for the workflow.",
            "name": "The workflow's name.",
            "standard": "Whether this is the account's standard (default) workflow.",
            "hidden": "Whether the workflow is hidden.",
            "customStatuses": "The custom statuses defined within the workflow.",
        },
    },
    "custom_fields": {
        "description": "A custom field definition that can be applied to tasks and folders in Wrike.",
        "docs_url": "https://developers.wrike.com/api/v4/custom-fields/",
        "columns": {
            "id": "Unique identifier for the custom field.",
            "title": "The custom field's title.",
            "type": "Data type of the custom field (e.g. Text, Numeric, DropDown, Date).",
            "spaceId": "ID of the space the custom field belongs to, if space-scoped.",
            "settings": "Type-specific settings for the custom field (e.g. dropdown options).",
        },
    },
    "spaces": {
        "description": "A space in Wrike — a top-level container grouping related projects and folders.",
        "docs_url": "https://developers.wrike.com/api/v4/spaces/",
        "columns": {
            "id": "Unique identifier for the space.",
            "title": "The space's title.",
            "description": "The space's description.",
            "access": "Access level of the space (e.g. Public, Private).",
            "archived": "Whether the space is archived.",
            "avatarUrl": "URL of the space's avatar image.",
        },
    },
}
