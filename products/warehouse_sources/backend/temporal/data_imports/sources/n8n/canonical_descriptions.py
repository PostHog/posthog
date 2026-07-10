"""Canonical, documentation-sourced descriptions for n8n endpoints and columns.

Sourced from the official n8n public API reference (https://docs.n8n.io/api/api-reference/).
Keyed by the endpoint names in `settings.py` `N8N_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced n8n table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflows": {
        "description": "Automation workflows defined in the n8n instance.",
        "docs_url": "https://docs.n8n.io/api/api-reference/",
        "columns": {
            "id": "Unique identifier for the workflow.",
            "name": "Human-readable name of the workflow.",
            "active": "Whether the workflow is currently active (its triggers are enabled).",
            "isArchived": "Whether the workflow has been archived.",
            "nodes": "The nodes that make up the workflow.",
            "connections": "How the workflow's nodes are wired together.",
            "settings": "Workflow-level settings (error workflow, timezone, execution order, etc.).",
            "staticData": "Persisted static data used by the workflow's nodes across executions.",
            "tags": "Tags assigned to the workflow.",
            "triggerCount": "Number of active trigger nodes in the workflow.",
            "versionId": "Identifier of the current workflow version, used for optimistic locking.",
            "meta": "Workflow metadata such as onboarding and template information.",
            "createdAt": "Time at which the workflow was created.",
            "updatedAt": "Time at which the workflow was last updated.",
        },
    },
    "executions": {
        "description": "Individual runs of workflows, one row per execution.",
        "docs_url": "https://docs.n8n.io/api/api-reference/",
        "columns": {
            "id": "Unique identifier for the execution.",
            "finished": "Whether the execution finished running.",
            "mode": "How the execution was triggered (e.g. manual, trigger, webhook, retry).",
            "retryOf": "The id of the execution this run is a retry of, if any.",
            "retrySuccessId": "The id of the successful execution produced when retrying this one.",
            "status": "Execution status (e.g. success, error, running, waiting, canceled).",
            "startedAt": "Time at which the execution started.",
            "stoppedAt": "Time at which the execution stopped. Null while still running.",
            "waitTill": "Time until which a waiting execution is paused, if applicable.",
            "workflowId": "The id of the workflow this execution belongs to.",
            "customData": "Custom key-value data attached to the execution.",
        },
    },
    "tags": {
        "description": "Tags used to organize and group workflows.",
        "docs_url": "https://docs.n8n.io/api/api-reference/",
        "columns": {
            "id": "Unique identifier for the tag.",
            "name": "The tag's name.",
            "createdAt": "Time at which the tag was created.",
            "updatedAt": "Time at which the tag was last updated.",
        },
    },
    "users": {
        "description": "Users of the n8n instance.",
        "docs_url": "https://docs.n8n.io/api/api-reference/",
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "The user's email address.",
            "firstName": "The user's first name.",
            "lastName": "The user's last name.",
            "isPending": "Whether the user's invitation is still pending acceptance.",
            "role": "The user's global role on the instance (e.g. owner, admin, member).",
            "createdAt": "Time at which the user was created.",
            "updatedAt": "Time at which the user was last updated.",
        },
    },
    "variables": {
        "description": "Instance-level environment variables usable across workflows.",
        "docs_url": "https://docs.n8n.io/api/api-reference/",
        "columns": {
            "id": "Unique identifier for the variable.",
            "key": "The variable's key.",
            "value": "The variable's value.",
            "type": "The variable's type.",
            "project": "The project the variable belongs to, if scoped to one.",
        },
    },
    "projects": {
        "description": "Projects that group workflows, credentials, and variables.",
        "docs_url": "https://docs.n8n.io/api/api-reference/",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "The project's name.",
            "type": "The project's type (e.g. personal or team).",
        },
    },
}
