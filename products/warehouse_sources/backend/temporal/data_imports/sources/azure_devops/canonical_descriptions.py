"""Canonical, documentation-sourced descriptions for Azure DevOps endpoints and columns.

Sourced from the official Azure DevOps REST API reference (https://learn.microsoft.com/en-us/rest/api/azure/devops).
Keyed by the endpoint names in `settings.py` `AZURE_DEVOPS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Azure DevOps table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A team project in the Azure DevOps organization — a container for repos, builds, and work items.",
        "docs_url": "https://learn.microsoft.com/en-us/rest/api/azure/devops/core/projects/list",
        "columns": {
            "id": "Unique identifier for the project.",
            "name": "Name of the project.",
            "description": "Description of the project.",
            "url": "API URL of the project.",
            "state": "State of the project (e.g. wellFormed, createPending, deleting).",
            "revision": "Revision number of the project, incremented on each change.",
            "visibility": "Visibility of the project (private or public).",
            "lastUpdateTime": "Time at which the project was last updated.",
        },
    },
    "repositories": {
        "description": "A Git repository within an Azure DevOps project.",
        "docs_url": "https://learn.microsoft.com/en-us/rest/api/azure/devops/git/repositories/list",
        "columns": {
            "id": "Unique identifier for the repository.",
            "name": "Name of the repository.",
            "url": "API URL of the repository.",
            "project": "The project the repository belongs to.",
            "defaultBranch": "The repository's default branch (e.g. refs/heads/main).",
            "size": "Size of the repository in bytes.",
            "remoteUrl": "HTTPS clone URL of the repository.",
            "sshUrl": "SSH clone URL of the repository.",
            "webUrl": "URL of the repository in the Azure DevOps web UI.",
            "isDisabled": "Whether the repository is disabled.",
        },
    },
    "builds": {
        "description": "A build run produced by a build pipeline in Azure DevOps.",
        "docs_url": "https://learn.microsoft.com/en-us/rest/api/azure/devops/build/builds/list",
        "columns": {
            "id": "Unique identifier for the build.",
            "buildNumber": "Human-readable build number.",
            "status": "Status of the build (e.g. inProgress, completed, cancelling, notStarted).",
            "result": "Result of a completed build (e.g. succeeded, failed, canceled, partiallySucceeded).",
            "queueTime": "Time at which the build was queued.",
            "startTime": "Time at which the build started running.",
            "finishTime": "Time at which the build finished.",
            "sourceBranch": "The branch the build was run against.",
            "sourceVersion": "The commit the build was run against.",
            "definition": "The build pipeline definition that produced the build.",
            "project": "The project the build belongs to.",
            "requestedFor": "The identity the build was requested for.",
            "reason": "Reason the build was triggered (e.g. manual, individualCI, schedule).",
        },
    },
    "pull_requests": {
        "description": "A Git pull request in Azure DevOps.",
        "docs_url": "https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-requests/get-pull-requests-by-project",
        "columns": {
            "pullRequestId": "Unique identifier for the pull request.",
            "title": "Title of the pull request.",
            "description": "Description of the pull request.",
            "status": "Status of the pull request (active, abandoned, or completed).",
            "createdBy": "The identity that created the pull request.",
            "creationDate": "Time at which the pull request was created.",
            "closedDate": "Time at which the pull request was closed.",
            "sourceRefName": "The source branch of the pull request.",
            "targetRefName": "The target branch of the pull request.",
            "mergeStatus": "Status of the merge of the source into the target branch.",
            "isDraft": "Whether the pull request is a draft.",
            "repository": "The repository the pull request belongs to.",
        },
    },
    "work_item_revisions": {
        "description": "A historical revision of a work item, from the reporting (append-only) feed.",
        "docs_url": "https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/reporting-work-item-revisions/read-reporting-revisions-get",
        "columns": {
            "id": "Identifier of the work item this revision belongs to.",
            "rev": "Revision number of the work item.",
            "fields": "The work item field values at this revision (title, state, assigned to, etc.).",
            "changed_date": "Time at which this revision was made.",
            "url": "API URL of the work item revision.",
        },
    },
}
