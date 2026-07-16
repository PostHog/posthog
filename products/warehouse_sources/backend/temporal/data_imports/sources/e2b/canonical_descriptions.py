"""Canonical, documentation-sourced descriptions for E2B endpoints and columns.

Sourced from the official E2B OpenAPI spec (https://github.com/e2b-dev/infra/blob/main/spec/openapi.yml)
and the E2B API reference (https://e2b.dev/docs). Keyed by the endpoint names in `settings.py`
`E2B_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table. Columns absent here fall
back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sandboxes": {
        "description": "Running and paused sandboxes for the team. Terminated sandboxes are not listed here.",
        "docs_url": "https://e2b.dev/docs",
        "columns": {
            "sandboxID": "Identifier of the sandbox.",
            "templateID": "Identifier of the template the sandbox was created from.",
            "alias": "Alias of the template.",
            "clientID": "Identifier of the client (deprecated).",
            "startedAt": "Time when the sandbox was started.",
            "endAt": "Time when the sandbox will expire.",
            "cpuCount": "Number of virtual CPUs allocated to the sandbox.",
            "memoryMB": "Memory allocated to the sandbox, in MiB.",
            "diskSizeMB": "Disk size allocated to the sandbox, in MiB.",
            # `metadata` is deliberately not synced — it can hold user-stored secrets. See `SENSITIVE_FIELDS`.
            "state": "State of the sandbox (running or paused).",
            "envdVersion": "Version of the envd daemon running in the sandbox.",
        },
    },
    "templates": {
        "description": "Sandbox templates available to the team (public and team-private).",
        "docs_url": "https://e2b.dev/docs",
        "columns": {
            "templateID": "Identifier of the template.",
            "buildID": "Identifier of the last successful build for the template.",
            "cpuCount": "Number of virtual CPUs the template provisions.",
            "memoryMB": "Memory the template provisions, in MiB.",
            "diskSizeMB": "Disk size the template provisions, in MiB.",
            "public": "Whether the template is public or only accessible by the team.",
            "aliases": "Aliases of the template (deprecated).",
            "names": "Names of the template (namespace/alias format when namespaced).",
            "createdAt": "Time when the template was created.",
            "updatedAt": "Time when the template was last updated.",
            "createdBy": "The team member who created the template.",
            "lastSpawnedAt": "Time when the template was last used to start a sandbox.",
            "spawnCount": "Number of times the template has been used.",
            "buildCount": "Number of times the template has been built.",
            "envdVersion": "Version of the envd daemon baked into the template.",
            "buildStatus": "Status of the template's most recent build.",
        },
    },
    "snapshots": {
        "description": "Snapshots of paused sandboxes for the team.",
        "docs_url": "https://e2b.dev/docs",
        "columns": {
            "snapshotID": "Identifier of the snapshot template including the tag.",
            "names": "Full names of the snapshot template including team namespace and tag.",
        },
    },
}
