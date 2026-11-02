from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://apidocs.zenduty.com/"

# Descriptions are sourced from Zenduty's public API reference and product docs. Partial coverage is
# fine — any endpoint, column, or table-level description not listed here falls back to LLM enrichment.
# Team-nested tables additionally carry a `_zenduty_team_id` column: the `unique_id` of the parent team
# the row was fetched under (part of the composite primary key).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "teams": {
        "description": "Teams in your Zenduty account. Each team owns its own services, escalation policies, schedules, and members.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier (UUID) for the team.",
            "name": "Name of the team.",
            "creation_date": "When the team was created.",
        },
    },
    "account_members": {
        "description": "Members (users) of your Zenduty account, with their contact details and account role.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the account member.",
            "user": "The underlying user record (email, name, username).",
            "role": "The member's account-level role.",
        },
    },
    "incidents": {
        "description": "Incidents across your Zenduty account, with their status, urgency, and timing — the basis for MTTR/MTTA and incident-volume analysis.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the incident.",
            "incident_number": "Sequential, human-readable incident number.",
            "title": "Title/summary of the incident.",
            "status": "Lifecycle status of the incident (e.g. triggered, acknowledged, resolved).",
            "urgency": "Urgency assigned to the incident.",
            "service": "The service the incident belongs to.",
            "escalation_policy": "The escalation policy applied to the incident.",
            "creation_date": "When the incident was created.",
        },
    },
    "services": {
        "description": "Services within a team. Each service maps to an escalation policy that dictates how its incidents escalate.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the service.",
            "name": "Name of the service.",
            "escalation_policy": "The escalation policy governing this service.",
            "team": "The team the service belongs to.",
            "creation_date": "When the service was created.",
        },
    },
    "escalation_policies": {
        "description": "Escalation policies for a team — the ordered rules (schedules and users) that decide who is notified as an incident escalates.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the escalation policy.",
            "name": "Name of the escalation policy.",
            "rules": "Ordered escalation rules (targets and delays).",
        },
    },
    "schedules": {
        "description": "On-call schedules for a team, defining rotations and who is on call at a given time.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the schedule.",
            "name": "Name of the schedule.",
            "time_zone": "Time zone the schedule is evaluated in.",
        },
    },
    "team_members": {
        "description": "Membership rows linking users to a team, including their role within that team.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the team membership.",
            "user": "The user who is a member of the team.",
            "role": "The user's role within the team.",
        },
    },
    "roles": {
        "description": "Incident roles defined for a team (e.g. incident commander, communications lead).",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the role.",
            "title": "Title of the role.",
            "description": "What the role is responsible for.",
        },
    },
    "postmortems": {
        "description": "Post-incident retrospectives (postmortems) authored for a team's incidents.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the postmortem.",
            "title": "Title of the postmortem.",
            "author": "The author of the postmortem.",
        },
    },
    "maintenance_windows": {
        "description": "Scheduled maintenance windows for a team, during which alerting for affected services is suppressed.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the maintenance window.",
            "name": "Name of the maintenance window.",
            "start_time": "When the maintenance window begins.",
            "end_time": "When the maintenance window ends.",
        },
    },
    "slas": {
        "description": "Service-level agreements configured for a team, used to track response and resolution targets.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the SLA.",
            "name": "Name of the SLA.",
        },
    },
    "tags": {
        "description": "Tags defined for a team, used to categorize incidents and services.",
        "docs_url": _DOCS,
        "columns": {
            "unique_id": "Unique identifier for the tag.",
            "name": "Name of the tag.",
        },
    },
}
