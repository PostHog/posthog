"""Canonical, documentation-sourced descriptions for Codemagic endpoints and columns.

Sourced from the official Codemagic REST API docs (https://docs.codemagic.io/rest-api/) plus the
build object shape confirmed via a live response shared in
https://github.com/orgs/codemagic-ci-cd/discussions/1941 (GET /builds is not itself documented —
see the comment on `ENDPOINTS["Builds"]` in `settings.py`). Keyed by the resource names in
`settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced Codemagic table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Applications": {
        "description": "A Git repository added to Codemagic as a buildable application.",
        "docs_url": "https://docs.codemagic.io/rest-api/applications/",
        "columns": {
            "_id": "Unique identifier for the application.",
            "appName": "Name of the application, usually derived from the repository name.",
            "branches": "Branches available on the application's repository.",
            "workflowIds": "Identifiers of the Workflow Editor workflows configured for this application.",
            "workflows": "Workflow Editor workflows configured for this application, keyed by workflow id.",
        },
    },
    "Builds": {
        "description": "A single build run of an application on Codemagic.",
        "docs_url": "https://docs.codemagic.io/rest-api/builds/",
        "columns": {
            "_id": "Unique identifier for the build.",
            "index": "Sequential build number for the application.",
            "appId": "Identifier of the application this build ran for.",
            "status": "Current status of the build (e.g. finished, failed, canceled, building).",
            "version": "Build version, if configured for the workflow.",
            "branch": "Git branch the build ran against.",
            "startedAt": "Time the build started running, or null if it never started.",
            "finishedAt": "Time the build finished, or null while still running.",
            "createdAt": "Time the build was created (queued).",
            "workflowId": "Identifier of the Workflow Editor workflow used, or null for codemagic.yaml workflows.",
            "fileWorkflowId": "Workflow name as defined in codemagic.yaml, set only for YAML-configured builds.",
            "instanceType": "Build machine instance type the build ran on (e.g. mac_mini_m2).",
            "startedBy": "What triggered the build (e.g. a user, a webhook, the API).",
            "commit": "Git commit information for the build, including hash, author, message, and branch or tag.",
            "config": "Workflow configuration snapshot used for the build.",
            "artefacts": "Build artifacts produced by the build (e.g. app binaries), if any.",
            "labels": "Labels attached to the build.",
        },
    },
}
