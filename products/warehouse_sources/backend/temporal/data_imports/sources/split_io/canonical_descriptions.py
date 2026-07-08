"""Canonical, documentation-sourced descriptions for Split (Harness FME) endpoints and columns.

Sourced from the official Split Admin API reference (https://docs.split.io/reference).
Keyed by the endpoint names in `settings.py` `SPLIT_IO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Split table. Fan-out endpoints carry an injected
`_workspace_id` column identifying the workspace the row was fetched from. Columns absent here
fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workspaces": {
        "description": "A Split workspace — a container for environments, traffic types, feature flags, and segments.",
        "docs_url": "https://docs.split.io/reference/workspaces-overview",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "The workspace's human-readable name.",
            "requiresTitleAndComments": "Whether changes in this workspace require a title and comments.",
        },
    },
    "environments": {
        "description": "An environment within a Split workspace (e.g. production, staging).",
        "docs_url": "https://docs.split.io/reference/environments-overview",
        "columns": {
            "id": "Unique identifier for the environment.",
            "_workspace_id": "Id of the workspace this environment belongs to (injected during sync).",
            "name": "The environment's name, unique within its workspace.",
            "production": "Whether the environment is flagged as a production environment.",
        },
    },
    "traffic_types": {
        "description": "A traffic type within a Split workspace — the kind of entity flags are evaluated against (e.g. user, account).",
        "docs_url": "https://docs.split.io/reference/traffic-types-overview",
        "columns": {
            "id": "Unique identifier for the traffic type.",
            "_workspace_id": "Id of the workspace this traffic type belongs to (injected during sync).",
            "name": "The traffic type's name, unique within its workspace.",
            "displayAttributeId": "The attribute used as the display name for keys of this traffic type.",
        },
    },
    "feature_flags": {
        "description": "A feature flag (split) within a Split workspace.",
        "docs_url": "https://docs.split.io/reference/feature-flags-overview",
        "columns": {
            "id": "Unique identifier for the feature flag.",
            "_workspace_id": "Id of the workspace this flag belongs to (injected during sync).",
            "name": "The flag's name, unique within its workspace.",
            "description": "Human-readable description of the flag.",
            "trafficType": "The traffic type the flag is evaluated against.",
            "creationTime": "Time the flag was created, as an epoch-millisecond timestamp.",
            "rolloutStatus": "The flag's rollout status (e.g. pre-production, ramping, 100% released).",
            "rolloutStatusTimestamp": "Time the rollout status last changed, as an epoch-millisecond timestamp.",
            "tags": "Tags applied to the flag.",
            "owners": "Users and groups that own the flag.",
        },
    },
    "segments": {
        "description": "A segment within a Split workspace — a manually curated list of keys flags can target.",
        "docs_url": "https://docs.split.io/reference/segments-overview",
        "columns": {
            "_workspace_id": "Id of the workspace this segment belongs to (injected during sync).",
            "name": "The segment's name, unique within its workspace.",
            "description": "Human-readable description of the segment.",
            "trafficType": "The traffic type of the keys in the segment.",
            "creationTime": "Time the segment was created, as an epoch-millisecond timestamp.",
            "tags": "Tags applied to the segment.",
        },
    },
    "rollout_statuses": {
        "description": "A rollout status available in a Split workspace, used to track a flag's lifecycle stage.",
        "docs_url": "https://docs.split.io/reference/rollout-statuses-overview",
        "columns": {
            "id": "Unique identifier for the rollout status.",
            "_workspace_id": "Id of the workspace this rollout status belongs to (injected during sync).",
            "name": "The rollout status's name.",
            "description": "Human-readable description of the rollout status.",
        },
    },
    "flag_sets": {
        "description": "A flag set within a Split workspace — a named grouping of feature flags evaluated together.",
        "docs_url": "https://docs.split.io/reference/flag-sets-overview",
        "columns": {
            "id": "Unique identifier for the flag set.",
            "_workspace_id": "Id of the workspace this flag set belongs to (injected during sync).",
            "name": "The flag set's name, unique within its workspace.",
            "description": "Human-readable description of the flag set.",
        },
    },
    "groups": {
        "description": "A group of users in the Split organization.",
        "docs_url": "https://docs.split.io/reference/groups-overview",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "The group's name, unique within the organization.",
            "description": "Human-readable description of the group.",
        },
    },
    "users": {
        "description": "An active member of the Split organization.",
        "docs_url": "https://docs.split.io/reference/users-overview",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "status": "The user's status (e.g. ACTIVE).",
            "groups": "Groups the user belongs to.",
            "2fa": "Whether the user has two-factor authentication enabled.",
        },
    },
    "change_requests": {
        "description": "A change request — a proposed change to a feature flag or segment awaiting approval.",
        "docs_url": "https://docs.split.io/reference/change-requests-overview",
        "columns": {
            "id": "Unique identifier for the change request.",
            "status": "The change request's status (e.g. REQUESTED, APPROVED, PUBLISHED, WITHDRAWN).",
            "title": "Title of the change request.",
            "comment": "Comment submitted with the change request.",
            "split": "The feature flag definition the change applies to, if any.",
            "segment": "The segment the change applies to, if any.",
            "operationType": "The kind of change being requested (e.g. UPDATE, ARCHIVE).",
            "approvers": "Users asked to approve the change.",
        },
    },
}
