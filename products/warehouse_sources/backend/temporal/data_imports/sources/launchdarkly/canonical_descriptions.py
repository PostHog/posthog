"""Canonical, documentation-sourced descriptions for LaunchDarkly endpoints and columns.

Sourced from the official LaunchDarkly REST API reference (https://apidocs.launchdarkly.com).
Keyed by the endpoint names in `settings.py` `LAUNCHDARKLY_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced LaunchDarkly table. Fan-out endpoints carry an injected
`_project_key` column identifying the project the row was fetched from. Columns absent here fall
back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A LaunchDarkly project — a container for environments, feature flags, and metrics.",
        "docs_url": "https://apidocs.launchdarkly.com/tag/Projects",
        "columns": {
            "_id": "Unique identifier for the project.",
            "key": "The project's unique key.",
            "name": "The project's human-readable name.",
            "tags": "Tags applied to the project.",
            "environments": "The environments belonging to the project.",
        },
    },
    "members": {
        "description": "A member of the LaunchDarkly account.",
        "docs_url": "https://apidocs.launchdarkly.com/tag/Account-members",
        "columns": {
            "_id": "Unique identifier for the member.",
            "email": "The member's email address.",
            "firstName": "The member's first name.",
            "lastName": "The member's last name.",
            "role": "The member's built-in role (e.g. reader, writer, admin, owner).",
            "customRoles": "Custom roles assigned to the member.",
            "_pendingInvite": "Whether the member has a pending invitation.",
            "_lastSeen": "Time the member was last active, as an epoch-millisecond timestamp.",
        },
    },
    "auditlog": {
        "description": "An entry in the LaunchDarkly audit log recording a change made in the account.",
        "docs_url": "https://apidocs.launchdarkly.com/tag/Audit-log",
        "columns": {
            "_id": "Unique identifier for the audit log entry.",
            "date": "Time the change occurred, as an epoch-millisecond timestamp.",
            "kind": "The kind of resource the entry relates to.",
            "name": "Name of the resource that was changed.",
            "description": "Human-readable description of the change.",
            "member": "The member who made the change.",
            "titleVerb": "The action verb describing what happened.",
            "accesses": "The set of actions performed in this change.",
        },
    },
    "environments": {
        "description": "An environment within a LaunchDarkly project (e.g. production, staging).",
        "docs_url": "https://apidocs.launchdarkly.com/tag/Environments",
        "columns": {
            "_id": "Unique identifier for the environment.",
            "_project_key": "Key of the project this environment belongs to (injected during sync).",
            "key": "The environment's unique key within its project.",
            "name": "The environment's human-readable name.",
            "color": "The environment's display color.",
            "tags": "Tags applied to the environment.",
            "apiKey": "The environment's SDK API key.",
            "mobileKey": "The environment's mobile SDK key.",
            "defaultTtl": "Default time-to-live for the environment's flag settings.",
        },
    },
    "metrics": {
        "description": "A metric used to measure the impact of feature flags and experiments.",
        "docs_url": "https://apidocs.launchdarkly.com/tag/Metrics",
        "columns": {
            "_id": "Unique identifier for the metric.",
            "_project_key": "Key of the project this metric belongs to (injected during sync).",
            "key": "The metric's unique key within its project.",
            "name": "The metric's human-readable name.",
            "description": "Description of the metric.",
            "kind": "The metric's kind (e.g. custom, pageview, click).",
            "tags": "Tags applied to the metric.",
            "isNumeric": "Whether the metric measures a numeric value.",
            "unit": "The unit of the metric's measured value.",
        },
    },
    "flags": {
        "description": "A LaunchDarkly feature flag and its targeting configuration across environments.",
        "docs_url": "https://apidocs.launchdarkly.com/tag/Feature-flags",
        "columns": {
            "_project_key": "Key of the project this flag belongs to (injected during sync).",
            "key": "The flag's unique key within its project.",
            "name": "The flag's human-readable name.",
            "description": "Description of the flag.",
            "kind": "The flag's kind (boolean or multivariate).",
            "tags": "Tags applied to the flag.",
            "variations": "The set of variations the flag can serve.",
            "temporary": "Whether the flag is intended to be temporary.",
            "maintainerId": "ID of the member who maintains the flag.",
            "environments": "Per-environment targeting and rollout configuration for the flag.",
            "creationDate": "Time the flag was created, as an epoch-millisecond timestamp.",
        },
    },
}
