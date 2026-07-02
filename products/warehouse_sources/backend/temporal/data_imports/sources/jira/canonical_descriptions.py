"""Canonical, documentation-sourced descriptions for Jira endpoints and columns.

Sourced from the official Jira Cloud REST API v3 reference
(https://developer.atlassian.com/cloud/jira/platform/rest/v3/). Keyed by the endpoint names in
`settings.py` `JIRA_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Jira table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "issues": {
        "description": "A Jira issue — a task, bug, story, or other unit of work tracked in a project.",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/#api-rest-api-3-search-jql-get",
        "columns": {
            "id": "Unique identifier for the issue.",
            "key": "Human-readable issue key (e.g. PROJ-123).",
            "self": "URL of the issue's REST resource.",
            "fields": "The issue's field values (summary, status, assignee, dates, custom fields, and more).",
            "expand": "Which parts of the issue were expanded in the response.",
        },
    },
    "projects": {
        "description": "A Jira project that groups issues and configuration.",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-projects/#api-rest-api-3-project-search-get",
        "columns": {
            "id": "Unique identifier for the project.",
            "key": "The project's key, used as a prefix for issue keys.",
            "name": "The project's name.",
            "projectTypeKey": "The project type (e.g. software, service_desk, business).",
            "lead": "The user who leads the project.",
            "simplified": "Whether the project is a simplified (team-managed) project.",
            "style": "The project style (classic or next-gen).",
            "isPrivate": "Whether the project is private.",
            "self": "URL of the project's REST resource.",
        },
    },
    "users": {
        "description": "A user account that can access the Jira site.",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-users/#api-rest-api-3-users-search-get",
        "columns": {
            "accountId": "Unique account identifier for the user.",
            "accountType": "The account type (e.g. atlassian, app, customer).",
            "displayName": "The user's display name.",
            "emailAddress": "The user's email address, if visible.",
            "active": "Whether the user account is active.",
            "self": "URL of the user's REST resource.",
        },
    },
    "fields": {
        "description": "A field (system or custom) available on Jira issues.",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-fields/#api-rest-api-3-field-get",
        "columns": {
            "id": "Unique identifier for the field.",
            "key": "The field's key.",
            "name": "The field's display name.",
            "custom": "Whether the field is a custom field.",
            "navigable": "Whether the field can appear in issue navigator columns.",
            "searchable": "Whether the field can be searched via JQL.",
            "schema": "The field's data type schema.",
        },
    },
    "issue_types": {
        "description": "A type that categorizes Jira issues (e.g. Bug, Story, Task, Epic).",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-types/#api-rest-api-3-issuetype-get",
        "columns": {
            "id": "Unique identifier for the issue type.",
            "name": "The issue type's name.",
            "description": "Description of the issue type.",
            "subtask": "Whether this issue type is a subtask type.",
            "hierarchyLevel": "The hierarchy level of the issue type (e.g. epic, standard, subtask).",
            "iconUrl": "URL of the issue type's icon.",
            "self": "URL of the issue type's REST resource.",
        },
    },
    "statuses": {
        "description": "A workflow status an issue can be in (e.g. To Do, In Progress, Done).",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-workflow-statuses/#api-rest-api-3-status-get",
        "columns": {
            "id": "Unique identifier for the status.",
            "name": "The status's name.",
            "description": "Description of the status.",
            "statusCategory": "The category the status belongs to (To Do, In Progress, Done).",
            "iconUrl": "URL of the status's icon.",
            "self": "URL of the status's REST resource.",
        },
    },
    "priorities": {
        "description": "A priority level that can be assigned to a Jira issue (e.g. Highest, High, Medium).",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-priorities/#api-rest-api-3-priority-get",
        "columns": {
            "id": "Unique identifier for the priority.",
            "name": "The priority's name.",
            "description": "Description of the priority.",
            "statusColor": "Hex color associated with the priority.",
            "iconUrl": "URL of the priority's icon.",
            "self": "URL of the priority's REST resource.",
        },
    },
    "resolutions": {
        "description": "A resolution that explains how an issue was closed (e.g. Done, Won't Do, Duplicate).",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-resolutions/#api-rest-api-3-resolution-get",
        "columns": {
            "id": "Unique identifier for the resolution.",
            "name": "The resolution's name.",
            "description": "Description of the resolution.",
            "self": "URL of the resolution's REST resource.",
        },
    },
    "dashboards": {
        "description": "A Jira dashboard that displays gadgets summarizing issues and activity.",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-dashboards/#api-rest-api-3-dashboard-get",
        "columns": {
            "id": "Unique identifier for the dashboard.",
            "name": "The dashboard's name.",
            "description": "Description of the dashboard.",
            "owner": "The user who owns the dashboard.",
            "view": "URL to view the dashboard.",
            "popularity": "Number of users who have favorited the dashboard.",
            "isFavourite": "Whether the requesting user has favorited the dashboard.",
            "self": "URL of the dashboard's REST resource.",
        },
    },
    "filters": {
        "description": "A saved JQL filter in Jira used to find a set of issues.",
        "docs_url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-filters/#api-rest-api-3-filter-search-get",
        "columns": {
            "id": "Unique identifier for the filter.",
            "name": "The filter's name.",
            "description": "Description of the filter.",
            "owner": "The user who owns the filter.",
            "jql": "The JQL query that defines the filter.",
            "viewUrl": "URL to view the filter's results.",
            "favourite": "Whether the requesting user has favorited the filter.",
            "favouritedCount": "Number of users who have favorited the filter.",
            "self": "URL of the filter's REST resource.",
        },
    },
}
