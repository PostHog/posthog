"""Canonical, documentation-sourced descriptions for Opsgenie endpoints and columns.

Sourced from the official Opsgenie REST API reference (https://docs.opsgenie.com/docs/api-overview).
Keyed by the endpoint names in `settings.py` `OPSGENIE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Opsgenie table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "alerts": {
        "description": "An alert created in Opsgenie by an integration, the API, or a user, representing an event that may need attention.",
        "docs_url": "https://docs.opsgenie.com/docs/alert-api",
        "columns": {
            "id": "Unique identifier of the alert.",
            "tinyId": "Short sequential id of the alert, unique within the account.",
            "alias": "Client-defined identifier used to deduplicate alerts.",
            "message": "Alert text shown to responders.",
            "status": "Current status of the alert: open or closed.",
            "acknowledged": "Whether the alert has been acknowledged.",
            "isSeen": "Whether the alert has been seen by at least one responder.",
            "tags": "Tags attached to the alert.",
            "snoozed": "Whether the alert is currently snoozed.",
            "snoozedUntil": "Time until which the alert is snoozed, if snoozed.",
            "count": "Number of times the alert has occurred (deduplicated on alias).",
            "lastOccurredAt": "Time the alert last occurred.",
            "createdAt": "Time the alert was created; the incremental cursor.",
            "updatedAt": "Time the alert was last updated.",
            "source": "Source of the alert (e.g. the integration or user that created it).",
            "owner": "Username of the alert's owner.",
            "priority": "Priority of the alert: P1 (critical) through P5 (informational).",
            "responders": "Teams, users, escalations, or schedules the alert was routed to.",
            "integration": "The integration that created the alert.",
            "report": "Acknowledge/close timing report for the alert.",
        },
    },
    "incidents": {
        "description": "An incident representing a service outage or degradation that requires coordinated response.",
        "docs_url": "https://docs.opsgenie.com/docs/incident-api",
        "columns": {
            "id": "Unique identifier of the incident.",
            "tinyId": "Short sequential id of the incident, unique within the account.",
            "message": "Incident text shown to responders.",
            "status": "Current status of the incident: open, resolved, or closed.",
            "tags": "Tags attached to the incident.",
            "createdAt": "Time the incident was created; the incremental cursor.",
            "updatedAt": "Time the incident was last updated.",
            "priority": "Priority of the incident: P1 (critical) through P5 (informational).",
            "ownerTeam": "Name of the team that owns the incident.",
            "responders": "Teams and users responding to the incident.",
            "impactedServices": "Ids of the services impacted by the incident.",
            "extraProperties": "Additional key-value details attached to the incident.",
        },
    },
    "users": {
        "description": "A user account in the Opsgenie organization.",
        "docs_url": "https://docs.opsgenie.com/docs/user-api",
        "columns": {
            "id": "Unique identifier of the user.",
            "username": "Email address the user signs in with.",
            "fullName": "Full display name of the user.",
            "role": "Role of the user (e.g. Admin, User, or a custom role).",
            "blocked": "Whether the user account is blocked.",
            "verified": "Whether the user's email address has been verified.",
            "timeZone": "Time zone of the user.",
            "locale": "Locale of the user.",
            "userAddress": "Address details of the user.",
            "createdAt": "Time the user account was created.",
        },
    },
    "teams": {
        "description": "A team that owns alerts, services, and on-call schedules.",
        "docs_url": "https://docs.opsgenie.com/docs/team-api",
        "columns": {
            "id": "Unique identifier of the team.",
            "name": "Name of the team.",
            "description": "Description of the team.",
        },
    },
    "schedules": {
        "description": "An on-call schedule defining who is on call and when.",
        "docs_url": "https://docs.opsgenie.com/docs/schedule-api",
        "columns": {
            "id": "Unique identifier of the schedule.",
            "name": "Name of the schedule.",
            "description": "Description of the schedule.",
            "timezone": "Time zone the schedule's rotations are evaluated in.",
            "enabled": "Whether the schedule is enabled.",
            "ownerTeam": "The team that owns the schedule.",
            "rotations": "Rotations that make up the schedule.",
        },
    },
    "escalations": {
        "description": "An escalation policy describing how unacknowledged alerts are escalated.",
        "docs_url": "https://docs.opsgenie.com/docs/escalation-api",
        "columns": {
            "id": "Unique identifier of the escalation.",
            "name": "Name of the escalation.",
            "description": "Description of the escalation.",
            "rules": "Ordered rules describing who is notified at each escalation step.",
            "ownerTeam": "The team that owns the escalation.",
            "repeat": "Repeat settings applied when the escalation completes without acknowledgment.",
        },
    },
    "services": {
        "description": "A business service used to track incident impact.",
        "docs_url": "https://docs.opsgenie.com/docs/service-api",
        "columns": {
            "id": "Unique identifier of the service.",
            "name": "Name of the service.",
            "description": "Description of the service.",
            "teamId": "Id of the team that owns the service.",
            "tags": "Tags attached to the service.",
        },
    },
    "integrations": {
        "description": "An integration that creates alerts in Opsgenie (e.g. a monitoring tool or email integration).",
        "docs_url": "https://docs.opsgenie.com/docs/integration-api",
        "columns": {
            "id": "Unique identifier of the integration.",
            "name": "Name of the integration.",
            "type": "Type of the integration (e.g. API, Email, or a vendor integration).",
            "enabled": "Whether the integration is enabled.",
            "teamId": "Id of the team the integration is assigned to, if any.",
        },
    },
}
