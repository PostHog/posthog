"""Canonical, documentation-sourced descriptions for incident.io endpoints and columns.

Sourced from the official incident.io API reference (https://api-docs.incident.io). Keyed by the
endpoint names in `settings.py` `INCIDENT_IO_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced incident.io table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "incidents": {
        "description": "An incident tracked in incident.io, with its status, severity, and timeline.",
        "docs_url": "https://api-docs.incident.io/tag/Incidents-V2",
        "columns": {
            "id": "Unique identifier for the incident.",
            "name": "The incident's name.",
            "summary": "Summary describing what the incident is about.",
            "reference": "Human-readable reference for the incident (e.g. INC-123).",
            "incident_status": "The current status of the incident (e.g. triage, investigating, resolved, closed).",
            "severity": "The severity assigned to the incident.",
            "incident_type": "The type of the incident.",
            "mode": "Whether the incident is real, a test, a tutorial, or retrospective.",
            "visibility": "Whether the incident is public or private.",
            "permalink": "Link to the incident in the incident.io dashboard.",
            "slack_channel_id": "Identifier of the Slack channel created for the incident.",
            "slack_channel_name": "Name of the Slack channel created for the incident.",
            "incident_role_assignments": "Users assigned to incident roles (e.g. lead, reporter).",
            "custom_field_entries": "Values of custom fields set on the incident.",
            "created_at": "Time at which the incident was created.",
            "updated_at": "Time at which the incident was last updated.",
        },
    },
    "incident_updates": {
        "description": "A status update posted to the timeline of an incident in incident.io.",
        "docs_url": "https://api-docs.incident.io/tag/Incident-Updates-V2",
        "columns": {
            "id": "Unique identifier for the incident update.",
            "incident_id": "Identifier of the incident this update belongs to.",
            "message": "The message content of the update.",
            "new_incident_status": "The incident status set by this update.",
            "new_severity": "The incident severity set by this update.",
            "updater": "The user who posted the update.",
            "created_at": "Time at which the update was posted.",
        },
    },
    "follow_ups": {
        "description": "A follow-up action item created from an incident in incident.io.",
        "docs_url": "https://api-docs.incident.io/tag/Follow-ups-V2",
        "columns": {
            "id": "Unique identifier for the follow-up.",
            "incident_id": "Identifier of the incident this follow-up came from.",
            "title": "The follow-up's title.",
            "description": "Description of the follow-up action.",
            "status": "Current status of the follow-up (e.g. outstanding, completed, deleted).",
            "assignee": "The user the follow-up is assigned to.",
            "priority": "The priority assigned to the follow-up.",
            "external_issue_reference": "Reference to the linked external issue (e.g. Jira, GitHub).",
            "completed_at": "Time at which the follow-up was completed.",
            "created_at": "Time at which the follow-up was created.",
            "updated_at": "Time at which the follow-up was last updated.",
        },
    },
    "alerts": {
        "description": "An alert ingested into incident.io that may be attached to or trigger an incident.",
        "docs_url": "https://api-docs.incident.io/tag/Alerts-V2",
        "columns": {
            "id": "Unique identifier for the alert.",
            "title": "The alert's title.",
            "description": "Description of the alert.",
            "status": "Current status of the alert (e.g. firing, resolved).",
            "alert_source_id": "Identifier of the source that created the alert.",
            "deduplication_key": "Key used to deduplicate repeated alerts.",
            "attributes": "Custom attribute values attached to the alert.",
            "created_at": "Time at which the alert was created.",
            "updated_at": "Time at which the alert was last updated.",
            "resolved_at": "Time at which the alert was resolved.",
        },
    },
    "escalations": {
        "description": "An escalation in incident.io that pages on-call responders for an alert or incident.",
        "docs_url": "https://api-docs.incident.io/tag/Escalations-V2",
        "columns": {
            "id": "Unique identifier for the escalation.",
            "title": "The escalation's title.",
            "status": "Current status of the escalation (e.g. pending, triggered, acknowledged, resolved).",
            "priority": "The priority of the escalation.",
            "created_at": "Time at which the escalation was created.",
            "updated_at": "Time at which the escalation was last updated.",
        },
    },
    "users": {
        "description": "A user in the incident.io organization.",
        "docs_url": "https://api-docs.incident.io/tag/Users-V2",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "slack_user_id": "Identifier of the user's linked Slack account.",
            "role": "The user's role in the organization (e.g. viewer, responder, administrator).",
        },
    },
    "schedules": {
        "description": "An on-call schedule defining who is on-call and when in incident.io.",
        "docs_url": "https://api-docs.incident.io/tag/Schedules-V2",
        "columns": {
            "id": "Unique identifier for the schedule.",
            "name": "The schedule's name.",
            "timezone": "The timezone the schedule's rotations are defined in.",
            "config": "The rotation configuration for the schedule.",
            "current_shifts": "The shifts currently active on the schedule.",
            "created_at": "Time at which the schedule was created.",
            "updated_at": "Time at which the schedule was last updated.",
        },
    },
    "severities": {
        "description": "A severity level that can be assigned to incidents in incident.io.",
        "docs_url": "https://api-docs.incident.io/tag/Severities-V1",
        "columns": {
            "id": "Unique identifier for the severity.",
            "name": "The severity's name (e.g. Minor, Major, Critical).",
            "description": "Description of when this severity applies.",
            "rank": "Numeric rank used to order severities by seriousness.",
            "created_at": "Time at which the severity was created.",
            "updated_at": "Time at which the severity was last updated.",
        },
    },
    "incident_roles": {
        "description": "A role that can be assigned to responders during an incident in incident.io.",
        "docs_url": "https://api-docs.incident.io/tag/Incident-Roles-V2",
        "columns": {
            "id": "Unique identifier for the incident role.",
            "name": "The role's name (e.g. Incident Lead).",
            "description": "Description of the role's responsibilities.",
            "instructions": "Instructions shown to the person assigned this role.",
            "shortform": "Short form of the role name.",
            "required": "Whether this role must be assigned for every incident.",
            "role_type": "The type of the role (e.g. lead, reporter, custom).",
            "created_at": "Time at which the role was created.",
            "updated_at": "Time at which the role was last updated.",
        },
    },
    "incident_statuses": {
        "description": "A status an incident can be in within incident.io (e.g. triage, investigating, closed).",
        "docs_url": "https://api-docs.incident.io/tag/Incident-Statuses-V1",
        "columns": {
            "id": "Unique identifier for the incident status.",
            "name": "The status's name.",
            "description": "Description of what the status represents.",
            "category": "The lifecycle category of the status (e.g. active, post-incident, closed).",
            "rank": "Numeric rank used to order statuses.",
            "created_at": "Time at which the status was created.",
            "updated_at": "Time at which the status was last updated.",
        },
    },
    "incident_types": {
        "description": "A type that categorizes incidents in incident.io, controlling which custom fields apply.",
        "docs_url": "https://api-docs.incident.io/tag/Incident-Types-V1",
        "columns": {
            "id": "Unique identifier for the incident type.",
            "name": "The incident type's name.",
            "description": "Description of the incident type.",
            "is_default": "Whether this is the default incident type.",
            "created_at": "Time at which the type was created.",
            "updated_at": "Time at which the type was last updated.",
        },
    },
    "custom_fields": {
        "description": "A custom field that can be set on incidents in incident.io.",
        "docs_url": "https://api-docs.incident.io/tag/Custom-Fields-V2",
        "columns": {
            "id": "Unique identifier for the custom field.",
            "name": "The custom field's name.",
            "description": "Description of the custom field.",
            "field_type": "The data type of the field (e.g. single_select, multi_select, text, link, numeric).",
            "options": "Available options for select-type custom fields.",
            "created_at": "Time at which the custom field was created.",
            "updated_at": "Time at which the custom field was last updated.",
        },
    },
}
