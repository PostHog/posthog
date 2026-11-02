"""Canonical, documentation-sourced descriptions for SentinelOne endpoints and columns.

Sourced from the SentinelOne Management API v2.1 reference (available in each tenant's
console under `/api-doc`) and its public mirrors. Keyed by the endpoint names in
`settings.py` `SENTINELONE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced SentinelOne table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "threats": {
        "description": "A threat detected by SentinelOne, with detection details, classification, and mitigation status.",
        "columns": {
            "id": "Unique identifier for the threat.",
            "threatInfo": "Detection details: threat name, classification, confidence level, analyst verdict, incident status, and mitigation status.",
            "agentDetectionInfo": "Snapshot of the detecting agent at detection time (site, group, OS, policy).",
            "agentRealtimeInfo": "Current state of the agent the threat was detected on.",
            "mitigationStatus": "Mitigation actions taken for the threat and their results.",
            "indicators": "Behavioral indicators that contributed to the detection.",
            "createdAt": "Time at which the threat was created (hoisted from threatInfo).",
            "updatedAt": "Time at which the threat was last updated (hoisted from threatInfo).",
        },
    },
    "agents": {
        "description": "A SentinelOne agent — an endpoint (workstation or server) with its inventory, health, and protection state.",
        "columns": {
            "id": "Unique identifier for the agent.",
            "computerName": "Hostname of the endpoint.",
            "agentVersion": "Installed SentinelOne agent version.",
            "osName": "Operating system name of the endpoint.",
            "osType": "Operating system family (windows, macos, linux).",
            "isActive": "Whether the agent is currently active.",
            "infected": "Whether the endpoint has unresolved threats.",
            "networkStatus": "Network quarantine state of the endpoint (connected, disconnected).",
            "siteId": "Identifier of the site the agent belongs to.",
            "groupId": "Identifier of the group the agent belongs to.",
            "lastActiveDate": "Time the agent last communicated with the console.",
            "registeredAt": "Time the agent registered with the console.",
            "createdAt": "Time at which the agent record was created.",
            "updatedAt": "Time at which the agent record was last updated.",
        },
    },
    "activities": {
        "description": "The activity log — an append-only audit trail of console and agent events (logins, policy changes, mitigations, and more).",
        "columns": {
            "id": "Unique identifier for the activity.",
            "activityType": "Numeric code identifying the kind of activity.",
            "primaryDescription": "Human-readable description of the activity.",
            "secondaryDescription": "Additional context for the activity.",
            "userId": "Identifier of the console user who performed the activity, if any.",
            "agentId": "Identifier of the agent the activity relates to, if any.",
            "siteId": "Identifier of the site the activity occurred in.",
            "threatId": "Identifier of the related threat, if any.",
            "data": "Structured payload with activity-specific fields.",
            "createdAt": "Time at which the activity occurred.",
        },
    },
    "groups": {
        "description": "A group — a policy-scoped collection of agents within a site.",
        "columns": {
            "id": "Unique identifier for the group.",
            "name": "Name of the group.",
            "siteId": "Identifier of the site the group belongs to.",
            "type": "How membership is managed (static or dynamic).",
            "filterId": "Identifier of the dynamic filter driving membership, if any.",
            "rank": "Priority of the group among a site's dynamic groups.",
            "totalAgents": "Number of agents in the group.",
            "createdAt": "Time at which the group was created.",
            "updatedAt": "Time at which the group was last updated.",
        },
    },
    "sites": {
        "description": "A site — a tenant subdivision with its own licensing, policies, and users.",
        "columns": {
            "id": "Unique identifier for the site.",
            "name": "Name of the site.",
            "accountId": "Identifier of the account the site belongs to.",
            "accountName": "Name of the account the site belongs to.",
            "activeLicenses": "Number of licenses in use in the site.",
            "totalLicenses": "Number of licenses allocated to the site.",
            "state": "Lifecycle state of the site (active, expired, deleted).",
            "siteType": "License type of the site (trial, paid).",
            "expiration": "Time at which the site's license expires.",
            "createdAt": "Time at which the site was created.",
            "updatedAt": "Time at which the site was last updated.",
        },
    },
}
