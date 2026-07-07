"""Canonical, documentation-sourced descriptions for PagerDuty endpoints and columns.

Sourced from the official PagerDuty REST API reference (https://developer.pagerduty.com/api-reference/).
Keyed by the endpoint names in `settings.py` `PAGERDUTY_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced PagerDuty table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most PagerDuty REST objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique identifier for the object.",
    "type": "String describing the object's PagerDuty type (e.g. 'incident', 'service').",
    "summary": "Short, human-readable label for the object.",
    "self": "API URL at which the object can be retrieved.",
    "html_url": "URL at which the object is viewable in the PagerDuty web UI.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "incidents": {
        "description": "An incident representing a problem on a service that requires response.",
        "docs_url": "https://developer.pagerduty.com/api-reference/9d0b4b12e36f9-list-incidents",
        "columns": _columns(
            incident_number="Sequential, human-readable number for the incident.",
            title="Title describing the incident.",
            description="Description of the incident.",
            status="Current status of the incident: triggered, acknowledged, or resolved.",
            urgency="Urgency of the incident: high or low.",
            created_at="Time at which the incident was created; the incremental cursor.",
            resolved_at="Time at which the incident was resolved, if applicable.",
            service="The service the incident is associated with.",
            assignments="Current assignments of the incident to responders.",
            escalation_policy="The escalation policy applied to the incident.",
            teams="Teams the incident is associated with.",
            priority="Priority assigned to the incident, if any.",
            last_status_change_at="Time at which the incident's status last changed.",
            incident_key="Deduplication key used to prevent duplicate incidents.",
        ),
    },
    "log_entries": {
        "description": "A log entry recording an action or change on an incident (triggered, acknowledged, notified, etc.).",
        "docs_url": "https://developer.pagerduty.com/api-reference/2bcc6065c3fc1-list-log-entries",
        "columns": _columns(
            created_at="Time at which the log entry was created.",
            agent="The user or service that caused the logged action.",
            channel="The means by which the action was performed (e.g. web, api, timeout).",
            incident="The incident the log entry belongs to.",
            service="The service associated with the log entry.",
            event_details="Additional details about the logged event.",
        ),
    },
    "services": {
        "description": "A service representing an application, component, or team monitored in PagerDuty.",
        "docs_url": "https://developer.pagerduty.com/api-reference/e960cca205c0f-list-services",
        "columns": _columns(
            name="The service's name.",
            description="Description of the service.",
            status="Current status of the service (e.g. active, warning, critical, disabled).",
            created_at="Time at which the service was created.",
            updated_at="Time at which the service was last updated.",
            escalation_policy="The escalation policy used by the service.",
            teams="Teams the service is associated with.",
            auto_resolve_timeout="Seconds after which an incident is auto-resolved, if set.",
            acknowledgement_timeout="Seconds after which an acknowledged incident re-triggers, if set.",
        ),
    },
    "users": {
        "description": "A user account in the PagerDuty account.",
        "docs_url": "https://developer.pagerduty.com/api-reference/4cf28d189a98e-list-users",
        "columns": _columns(
            name="The user's full name.",
            email="The user's email address.",
            role="The user's account role (e.g. admin, manager, responder, observer).",
            time_zone="The user's time zone.",
            job_title="The user's job title.",
            teams="Teams the user belongs to.",
            contact_methods="The user's configured contact methods.",
            notification_rules="Rules governing how and when the user is notified.",
        ),
    },
    "teams": {
        "description": "A team that groups users, services, and escalation policies in PagerDuty.",
        "docs_url": "https://developer.pagerduty.com/api-reference/d44a37c5e6113-list-teams",
        "columns": _columns(
            name="The team's name.",
            description="Description of the team.",
            parent="The parent team, if this team is nested.",
        ),
    },
    "escalation_policies": {
        "description": "An ordered set of escalation rules that determine who is notified when an incident is not handled.",
        "docs_url": "https://developer.pagerduty.com/api-reference/9b7e88f9c3df3-list-escalation-policies",
        "columns": _columns(
            name="The escalation policy's name.",
            description="Description of the escalation policy.",
            num_loops="Number of times the policy repeats if no one responds.",
            escalation_rules="Ordered rules defining who is escalated to and after how long.",
            services="Services that use this escalation policy.",
            teams="Teams the escalation policy is associated with.",
        ),
    },
    "schedules": {
        "description": "An on-call schedule defining which users are on call over time.",
        "docs_url": "https://developer.pagerduty.com/api-reference/8a08c0b16d98b-list-schedules",
        "columns": _columns(
            name="The schedule's name.",
            description="Description of the schedule.",
            time_zone="The time zone the schedule is defined in.",
            schedule_layers="Rotation layers defining who is on call and when.",
            teams="Teams the schedule is associated with.",
            escalation_policies="Escalation policies that reference this schedule.",
        ),
    },
    "priorities": {
        "description": "A priority level that can be assigned to incidents to rank their importance.",
        "docs_url": "https://developer.pagerduty.com/api-reference/f1a8d9d52f0f8-list-priorities",
        "columns": _columns(
            name="The priority's name (e.g. P1, P2).",
            description="Description of the priority.",
        ),
    },
    "vendors": {
        "description": "A third-party vendor that integrates with PagerDuty (e.g. a monitoring tool).",
        "docs_url": "https://developer.pagerduty.com/api-reference/8d6dd7e7e6f8e-list-vendors",
        "columns": _columns(
            name="The vendor's name.",
            description="Description of the vendor.",
            website_url="The vendor's website URL.",
            logo_url="URL of the vendor's logo.",
            integration_guide_url="URL of the vendor's PagerDuty integration guide.",
        ),
    },
}
