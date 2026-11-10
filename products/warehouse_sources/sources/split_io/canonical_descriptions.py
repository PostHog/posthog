"""Canonical, documentation-sourced descriptions for Split (Harness FME) endpoints and columns.

Sourced from the official Split Admin API reference (https://docs.split.io/reference).
Keyed by the endpoint names in `settings.py` `SPLIT_IO_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Split table. Fan-out endpoints carry an injected
`_workspace_id` column identifying the workspace the row was fetched from. Columns absent here
fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
        "description": "A member of the Split organization.",
        "docs_url": "https://docs.split.io/reference/users-overview",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "status": "The user's status (e.g. ACTIVE, DEACTIVATED).",
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
    "attributes": {
        "description": "An attribute defined on a Split traffic type, used in targeting rules and to describe identities.",
        "docs_url": "https://docs.split.io/reference/attributes-overview",
        "columns": {
            "id": "Identifier of the attribute, unique within its traffic type.",
            "_workspace_id": "Id of the workspace the traffic type belongs to (injected during sync).",
            "_traffic_type_id": "Id of the traffic type this attribute belongs to (injected during sync).",
            "organizationId": "Id of the organization that owns the attribute.",
            "trafficTypeId": "Id of the traffic type this attribute belongs to.",
            "displayName": "Display name of the attribute.",
            "description": "Human-readable description of the attribute.",
            "dataType": "Data type of the attribute's values (e.g. string, number, datetime, set).",
            "isSearchable": "Whether the attribute can be used to search for identities.",
            "suggestedValues": "Values suggested for the attribute in the Split UI.",
        },
    },
    "feature_flag_definitions": {
        "description": "The configuration of a feature flag in one environment: treatments, targeting rules, default rule and traffic allocation.",
        "docs_url": "https://docs.split.io/reference/feature-flag-definition",
        "columns": {
            "name": "Name of the feature flag, unique within its workspace.",
            "_workspace_id": "Id of the workspace the flag belongs to (injected during sync).",
            "_environment_id": "Id of the environment this definition applies to (injected during sync).",
            "environment": "The environment this definition applies to, with its id and name.",
            "trafficType": "The traffic type the flag is evaluated against, with its id and name.",
            "killed": "Whether the flag is killed in this environment, which serves the default treatment to all traffic.",
            "treatments": "The treatments the flag can serve in this environment.",
            "defaultTreatment": "The treatment served when the flag is killed or traffic is not allocated.",
            "trafficAllocation": "Percentage of traffic that the targeting rules evaluate.",
            "rules": "Targeting rules, each with a condition and the bucket distribution it serves.",
            "defaultRule": "Bucket distribution of treatments served when no targeting rule matches.",
            "lastTrafficReceivedAt": "Time the flag last received traffic in this environment, as an epoch-millisecond timestamp.",
            "creationTime": "Time the definition was created, as an epoch-millisecond timestamp.",
            "lastUpdateTime": "Time the definition was last updated, as an epoch-millisecond timestamp.",
        },
    },
    "segment_keys": {
        "description": "A key that is a member of a segment in one environment. One row per segment, environment and key.",
        "docs_url": "https://docs.split.io/reference/get-segment-keys-in-environment",
        "columns": {
            "key": "The key (for example a user or account id) that is a member of the segment.",
            "_workspace_id": "Id of the workspace the segment belongs to (injected during sync).",
            "_environment_id": "Id of the environment the segment membership applies to (injected during sync).",
            "_segment_name": "Name of the segment the key belongs to (injected during sync).",
        },
    },
}
