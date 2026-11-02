"""Canonical, documentation-sourced descriptions for Grafana IRM endpoints and columns.

Sourced from the Grafana IRM OnCall API reference and the Grafana Incident API reference
(https://grafana.com/docs/grafana-cloud/alerting-and-irm/irm/reference/). Keyed by the endpoint
names in `settings.py` `GRAFANA_IRM_ENDPOINTS`. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ONCALL_DOCS = "https://grafana.com/docs/grafana-cloud/alerting-and-irm/irm/reference/oncall-api/"
_INCIDENT_DOCS = "https://grafana.com/docs/grafana-cloud/alerting-and-irm/irm/reference/incident-api/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "alert_groups": {
        "description": "A group of related alerts received by an OnCall integration, handled as one unit through escalation, acknowledgement and resolution.",
        "docs_url": f"{_ONCALL_DOCS}alertgroups/",
        "columns": {
            "id": "Unique identifier for the alert group.",
            "integration_id": "ID of the integration that received the alerts.",
            "route_id": "ID of the route that matched the alert group.",
            "alerts_count": "Number of alerts in the alert group.",
            "state": "Current state of the alert group: new, acknowledged, resolved or silenced.",
            "created_at": "When the alert group started.",
            "resolved_at": "When the alert group was resolved, if it was.",
            "acknowledged_at": "When the alert group was acknowledged, if it was.",
            "acknowledged_by": "ID of the user who acknowledged the alert group.",
            "resolved_by": "ID of the user who resolved the alert group.",
            "silenced_at": "When the alert group was silenced, if it was.",
            "title": "Title of the alert group.",
            "permalinks": "Links to the alert group in connected chat tools such as Slack and Telegram.",
            "last_alert": "The most recent alert in the group, including its raw payload.",
        },
    },
    "alerts": {
        "description": "A single alert received by an OnCall integration, with its raw payload. Alerts are grouped into alert groups.",
        "docs_url": f"{_ONCALL_DOCS}alerts/",
        "columns": {
            "id": "Unique identifier for the alert.",
            "alert_group_id": "ID of the alert group the alert belongs to.",
            "created_at": "When the alert was received.",
            "payload": "Raw payload the monitoring system sent with the alert.",
        },
    },
    "resolution_notes": {
        "description": "A note attached to an alert group that explains how it was resolved.",
        "docs_url": f"{_ONCALL_DOCS}resolution_notes/",
        "columns": {
            "id": "Unique identifier for the resolution note.",
            "alert_group_id": "ID of the alert group the note belongs to.",
            "author": "ID of the user who wrote the note.",
            "source": "Where the note was written, for example web or slack.",
            "created_at": "When the note was created.",
            "text": "Text of the note.",
        },
    },
    "integrations": {
        "description": "A monitoring integration that sends alerts into OnCall, with its default route and message templates.",
        "docs_url": f"{_ONCALL_DOCS}integrations/",
        "columns": {
            "id": "Unique identifier for the integration.",
            "name": "Name of the integration.",
            "team_id": "ID of the team that owns the integration.",
            "type": "Integration type, for example grafana, alertmanager or webhook.",
            "default_route": "The route used when no other route matches.",
            "templates": "Templates that format alerts for each notification channel.",
        },
    },
    "routes": {
        "description": "A rule that sends matching alerts from an integration to an escalation chain.",
        "docs_url": f"{_ONCALL_DOCS}routes/",
        "columns": {
            "id": "Unique identifier for the route.",
            "integration_id": "ID of the integration the route belongs to.",
            "escalation_chain_id": "ID of the escalation chain alerts are sent to.",
            "routing_regex": "Regular expression that alert payloads must match.",
            "position": "Order in which the route is checked.",
            "is_the_last_route": "Whether this is the default route of the integration.",
        },
    },
    "escalation_chains": {
        "description": "A named sequence of escalation policies that decides who is notified and when.",
        "docs_url": f"{_ONCALL_DOCS}escalation_chains/",
        "columns": {
            "id": "Unique identifier for the escalation chain.",
            "name": "Name of the escalation chain.",
            "team_id": "ID of the team that owns the escalation chain.",
        },
    },
    "escalation_policies": {
        "description": "A single step of an escalation chain, such as waiting or notifying users or schedules.",
        "docs_url": f"{_ONCALL_DOCS}escalation_policies/",
        "columns": {
            "id": "Unique identifier for the escalation policy.",
            "escalation_chain_id": "ID of the escalation chain the step belongs to.",
            "position": "Order of the step in its escalation chain.",
            "type": "Kind of step, for example wait, notify_persons or notify_on_call_from_schedule.",
        },
    },
    "schedules": {
        "description": "An on-call schedule that defines who is on call at any time.",
        "docs_url": f"{_ONCALL_DOCS}schedules/",
        "columns": {
            "id": "Unique identifier for the schedule.",
            "name": "Name of the schedule.",
            "type": "Schedule type: web, ical or calendar.",
            "team_id": "ID of the team that owns the schedule.",
            "time_zone": "Time zone of the schedule.",
            "on_call_now": "IDs of the users on call when the table was synced.",
            "shifts": "IDs of the on-call shifts in the schedule.",
        },
    },
    "on_call_shifts": {
        "description": "A shift or rotation that belongs to one or more on-call schedules.",
        "docs_url": f"{_ONCALL_DOCS}on_call_shifts/",
        "columns": {
            "id": "Unique identifier for the shift.",
            "name": "Name of the shift.",
            "type": "Shift type: single_event, recurrent_event or rolling_users.",
            "start": "When the shift starts.",
            "duration": "Length of the shift in seconds.",
            "frequency": "How often a recurrent shift repeats.",
            "users": "IDs of the users on the shift.",
        },
    },
    "shift_swaps": {
        "description": "A request from one user to hand over their on-call shifts for a period to another user.",
        "docs_url": f"{_ONCALL_DOCS}shift_swaps/",
        "columns": {
            "id": "Unique identifier for the shift swap request.",
            "schedule": "ID of the schedule the swap applies to.",
            "beneficiary": "ID of the user who asked for the swap.",
            "benefactor": "ID of the user who took the swap, empty while it is open.",
            "status": "State of the request, for example open, taken or deleted.",
            "swap_start": "Start of the period to swap.",
            "swap_end": "End of the period to swap.",
            "created_at": "When the request was created.",
            "updated_at": "When the request was last updated.",
        },
    },
    "users": {
        "description": "A Grafana user known to OnCall.",
        "docs_url": f"{_ONCALL_DOCS}users/",
        "columns": {
            "id": "OnCall identifier for the user.",
            "grafana_id": "Grafana identifier for the user.",
            "email": "Email address of the user.",
            "username": "Grafana username of the user.",
            "role": "Role of the user in OnCall.",
            "timezone": "Time zone of the user.",
            "teams": "IDs of the teams the user belongs to.",
        },
    },
    "teams": {
        "description": "A Grafana team as seen by OnCall.",
        "docs_url": f"{_ONCALL_DOCS}teams/",
    },
    "user_groups": {
        "description": "A Slack user group that OnCall can notify.",
        "docs_url": f"{_ONCALL_DOCS}user_groups/",
    },
    "incidents": {
        "description": "A Grafana incident: a declared problem with its severity, status, timeline bounds and people involved.",
        "docs_url": _INCIDENT_DOCS,
        "columns": {
            "incidentID": "Unique identifier for the incident.",
            "title": "High-level description of the incident.",
            "description": "Brief description of the incident.",
            "summary": "Short recap of the incident.",
            "status": "Current status of the incident.",
            "severityID": "ID of the incident severity.",
            "severityLabel": "Label of the incident severity.",
            "isDrill": "Whether the incident is a drill.",
            "labels": "Labels attached to the incident.",
            "createdTime": "When the incident was created.",
            "modifiedTime": "When the incident was last modified.",
            "closedTime": "When the incident was closed.",
            "incidentStart": "When the incident began.",
            "incidentEnd": "When the incident ended.",
            "createdByUser": "The user who created the incident.",
            "fieldValues": "Values of the custom fields set on the incident.",
            "incidentMembershipPreview": "Summary of the people involved in the incident.",
            "slug": "URL-friendly path segment for the incident.",
            "version": "Number of times the incident has been updated.",
        },
    },
    "incident_activity": {
        "description": "An entry in an incident's timeline, such as a status change, a note or a role assignment.",
        "docs_url": _INCIDENT_DOCS,
        "columns": {
            "activityItemID": "Unique identifier for the activity item.",
            "incidentID": "ID of the incident the item belongs to.",
            "activityKind": "Kind of activity, for example incidentCreated or userNote.",
            "body": "Text of the activity item.",
            "createdTime": "When the activity item was created.",
            "eventTime": "When the event described by the item happened.",
            "user": "The user who created the item.",
            "subjectUser": "The user the item is about, if any.",
            "tags": "Tags attached to the item.",
            "url": "Link attached to the item.",
        },
    },
    "incident_membership": {
        "description": "A person involved in an incident and the role they hold in it. Covers every participant, not only the important roles in the incident membership preview.",
        "docs_url": _INCIDENT_DOCS,
        "columns": {
            "incidentID": "ID of the incident.",
            "roleID": "ID of the role the user holds in the incident.",
            "userID": "ID of the user, copied from the nested user object.",
            "role": "The role the user holds in the incident.",
            "user": "The user involved in the incident.",
        },
    },
    "incident_roles": {
        "description": "A role that people can hold in an incident, such as commander or investigator.",
        "docs_url": _INCIDENT_DOCS,
        "columns": {
            "roleID": "Unique identifier for the role.",
            "orgID": "ID of the organization that owns the role.",
            "name": "Name of the role.",
            "description": "Description of the role.",
            "important": "Whether the role is important.",
            "mandatory": "Whether the role is mandatory.",
            "archived": "Whether the role is archived.",
            "createdAt": "When the role was created.",
            "updatedAt": "When the role was last updated.",
        },
    },
    "incident_custom_fields": {
        "description": "A custom field that can be set on incidents. Resolves the field UUIDs in incident field values.",
        "docs_url": _INCIDENT_DOCS,
        "columns": {
            "uuid": "Unique identifier for the field.",
            "name": "Name of the field.",
            "slug": "URL-friendly identifier for the field.",
            "description": "Description of the field.",
            "type": "Data type of the field.",
            "domainName": "Domain the field belongs to.",
            "selectoptions": "Options a user can pick from, for select-type fields.",
            "required": "Whether the field is required.",
            "archived": "Whether the field is archived.",
            "immutable": "Whether the field can be changed.",
            "source": "Where the field comes from.",
            "externalID": "ID of the field in an external system.",
            "version": "Version of the field definition.",
        },
    },
}
