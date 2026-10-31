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
    "incident_alerts": {
        "description": "An alert grouped under an incident: one event from a monitoring tool, before de-duplication into the incident.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": _columns(
            incident_id="ID of the incident the alert was listed under.",
            created_at="Time at which the alert was first triggered.",
            status="Current status of the alert: triggered or resolved.",
            alert_key="The alert's de-duplication key.",
            service="The service the alert belongs to.",
            incident="The incident the alert is grouped under.",
            suppressed="Whether the alert is suppressed. Suppressed alerts are not created with a parent incident.",
            severity="Magnitude of the problem as reported by the monitoring tool: info, warning, error, or critical.",
            integration="The integration that sent the alert.",
            body="Data that describes the alert, including the details sent by the monitoring tool.",
            first_trigger_log_entry="The log entry that recorded the first trigger of the alert.",
        ),
    },
    "change_events": {
        "description": "A change event, such as a deploy or a configuration change, sent to PagerDuty by an integration.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": _columns(
            summary="Short text summary of the change.",
            timestamp="Time at which the emitting tool detected or generated the change.",
            source="Unique name of the location where the change occurred.",
            services="Services the change event is associated with.",
            integration="The integration that received the change event.",
            routing_key="Integration key of the service integration that received the event.",
            links="Links included with the change event.",
            images="Images included with the change event.",
            custom_details="Additional details about the change, as sent by the emitting tool.",
        ),
    },
    "team_members": {
        "description": "A membership row that joins a user to a team, with the user's role on that team.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": {
            "team_id": "ID of the team.",
            "user_id": "ID of the user who is a member of the team.",
            "user": "Reference to the user who is a member of the team.",
            "role": "The user's role on the team (e.g. manager, responder, observer).",
        },
    },
    "oncalls": {
        "description": "An on-call entry: a user who is on call for a level of an escalation policy at the time of the sync.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": {
            "id": "Identifier built from the escalation policy, escalation level, user, schedule, and start time.",
            "user_id": "ID of the user who is on call.",
            "user": "Reference to the user who is on call.",
            "escalation_policy_id": "ID of the escalation policy the user is on call for.",
            "escalation_policy": "Reference to the escalation policy the user is on call for.",
            "escalation_level": "The escalation level of the on-call user within the escalation policy.",
            "schedule_id": "ID of the schedule that puts the user on call. Empty when the escalation rule targets the user directly.",
            "schedule": "Reference to the schedule that puts the user on call, if any.",
            "start": "Start of the on-call period. Empty for a permanent on-call.",
            "end": "End of the on-call period. Empty when the user does not go off call.",
        },
    },
    "incident_notes": {
        "description": "A note a responder added to an incident, such as a status update or postmortem context.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": {
            "id": "Unique identifier for the note within its incident.",
            "incident_id": "ID of the incident the note is attached to.",
            "user_id": "ID of the user who wrote the note.",
            "user": "Reference to the user who wrote the note.",
            "channel": "The means by which the note was created.",
            "content": "The note content.",
            "created_at": "Time at which the note was submitted.",
            "updated_at": "Time at which the note was last updated.",
        },
    },
    "business_services": {
        "description": "A business service: a capability that spans several technical services and can be owned by several teams.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": _columns(
            name="The name of the business service.",
            description="The user-provided description of the business service.",
            point_of_contact="The point of contact assigned to the business service.",
            team="Reference to the team that owns the business service, if any.",
        ),
    },
    "maintenance_windows": {
        "description": "A maintenance window: a period during which one or more services do not create incidents.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": _columns(
            sequence_number="The order in which the maintenance window was created.",
            start_time="Time at which the services stop creating incidents.",
            end_time="Time at which the services start creating incidents again.",
            description="Description of the maintenance window.",
            created_by="Reference to the user who created the maintenance window.",
            services="Services that the maintenance window applies to.",
            teams="Teams associated with the maintenance window.",
        ),
    },
    "incident_analytics": {
        "description": "Per-incident metrics from the PagerDuty Analytics API, such as time to acknowledge, time to resolve, engaged time, and escalation counts.",
        "docs_url": "https://developer.pagerduty.com/api-reference",
        "columns": {
            "id": "ID of the incident.",
            "incident_number": "The PagerDuty incident number.",
            "created_at": "Time at which the incident was created.",
            "updated_at": "Time at which the analytics process last updated the row; the incremental cursor. It differs from the incident's own updated_at.",
            "resolved_at": "Time at which the incident was resolved.",
            "status": "The incident status: triggered, acknowledged, or resolved.",
            "urgency": "Notification level of the incident.",
            "major": "Whether the incident is a major incident.",
            "service_id": "ID of the service that the incident triggered on.",
            "team_id": "ID of the team the incident was assigned to.",
            "escalation_policy_id": "ID of the escalation policy the incident was assigned to.",
            "priority_id": "ID of the incident's priority level.",
            "seconds_to_first_ack": "Seconds from the start of the incident to the first acknowledgement.",
            "seconds_to_engage": "Seconds from the first engagement of a user to the last added responder engaging.",
            "seconds_to_mobilize": "Seconds from the start of the incident to the last additional responder acknowledging.",
            "seconds_to_resolve": "Seconds from when the incident was triggered until it was resolved.",
            "engaged_seconds": "Total engaged time across all responders for the incident.",
            "snoozed_seconds": "Total seconds the incident was snoozed.",
            "user_defined_effort_seconds": "Total response effort in seconds, as defined by the user.",
            "escalation_count": "Number of times the incident escalated between responders on an escalation policy.",
            "timeout_escalation_count": "Number of timeout escalations in the incident.",
            "manual_escalation_count": "Number of manual escalations in the incident.",
            "assignment_count": "Number of times responders were assigned the incident, including through reassignment or escalation.",
            "reassignment_count": "Number of reassignments in the incident.",
            "acknowledgement_count": "Number of acknowledgements in the incident.",
            "total_interruptions": "Number of unique interruptions in the incident.",
            "business_hour_interruptions": "Number of unique interruptions during business hours (8am-6pm Mon-Fri, in the user's time zone).",
            "off_hour_interruptions": "Number of unique interruptions during off hours (6pm-10pm Mon-Fri and all day Sat-Sun, in the user's time zone).",
            "sleep_hour_interruptions": "Number of unique interruptions during sleep hours (10pm-8am every day, in the user's time zone).",
            "total_notifications": "Number of notifications sent for the incident.",
            "auto_resolved": "Whether the incident resolved automatically.",
        },
    },
}
