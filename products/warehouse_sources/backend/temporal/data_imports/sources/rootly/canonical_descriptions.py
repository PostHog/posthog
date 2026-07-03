from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://docs.rootly.com/api-reference"

# Descriptions are sourced from Rootly's public API reference. Partial coverage is fine — any
# endpoint, column, or table-level description not listed here falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "incidents": {
        "description": "Incidents tracked in Rootly, with their lifecycle status, severity, and timeline.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the incident.",
            "title": "Human-readable title of the incident.",
            "summary": "Short summary describing the incident.",
            "status": "Lifecycle status of the incident (e.g. started, mitigated, resolved, closed).",
            "severity": "Severity assigned to the incident.",
            "created_at": "When the incident record was created.",
            "updated_at": "When the incident was last updated.",
            "started_at": "When the incident is considered to have started.",
            "detected_at": "When the incident was detected.",
            "acknowledged_at": "When the incident was acknowledged.",
            "mitigated_at": "When the incident was mitigated.",
            "resolved_at": "When the incident was resolved.",
            "closed_at": "When the incident was closed.",
        },
    },
    "alerts": {
        "description": "Alerts ingested by Rootly from monitoring and on-call integrations.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the alert.",
            "summary": "Summary of the alert.",
            "status": "Status of the alert.",
            "source": "Integration or system the alert came from.",
            "created_at": "When the alert was created.",
            "updated_at": "When the alert was last updated.",
        },
    },
    "action_items": {
        "description": "Follow-up action items associated with incidents.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the action item.",
            "summary": "Description of the action item.",
            "status": "Completion status of the action item.",
            "priority": "Priority assigned to the action item.",
            "created_at": "When the action item was created.",
            "updated_at": "When the action item was last updated.",
        },
    },
    "post_mortems": {
        "description": "Post-incident retrospectives (post-mortems) documenting what happened and why.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the post-mortem.",
            "title": "Title of the post-mortem.",
            "status": "Status of the post-mortem (e.g. draft, published).",
            "created_at": "When the post-mortem was created.",
            "updated_at": "When the post-mortem was last updated.",
        },
    },
    "pulses": {
        "description": "Pulse events forming the activity timeline within Rootly.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the pulse event.",
            "summary": "Summary of the pulse event.",
            "source": "Source of the pulse event.",
            "created_at": "When the pulse event was created.",
            "updated_at": "When the pulse event was last updated.",
        },
    },
    "users": {
        "description": "Users belonging to the Rootly organization.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "Email address of the user.",
            "name": "Full name of the user.",
            "created_at": "When the user was created.",
            "updated_at": "When the user was last updated.",
        },
    },
    "teams": {
        "description": "Teams (groups) configured in Rootly.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Name of the team.",
            "created_at": "When the team was created.",
            "updated_at": "When the team was last updated.",
        },
    },
    "services": {
        "description": "Services that can be affected by incidents.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the service.",
            "name": "Name of the service.",
            "created_at": "When the service was created.",
            "updated_at": "When the service was last updated.",
        },
    },
    "functionalities": {
        "description": "Functionalities (product areas) that can be affected by incidents.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the functionality.",
            "name": "Name of the functionality.",
            "created_at": "When the functionality was created.",
            "updated_at": "When the functionality was last updated.",
        },
    },
    "environments": {
        "description": "Environments (e.g. production, staging) defined in Rootly.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the environment.",
            "name": "Name of the environment.",
        },
    },
    "severities": {
        "description": "Severity levels that can be assigned to incidents.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the severity.",
            "name": "Name of the severity level.",
            "severity": "Relative severity ranking.",
        },
    },
    "incident_types": {
        "description": "Incident type classifications.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the incident type.",
            "name": "Name of the incident type.",
        },
    },
    "schedules": {
        "description": "On-call schedules configured in Rootly.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the schedule.",
            "name": "Name of the schedule.",
            "created_at": "When the schedule was created.",
            "updated_at": "When the schedule was last updated.",
        },
    },
    "escalation_policies": {
        "description": "Escalation policies that route alerts to responders.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the escalation policy.",
            "name": "Name of the escalation policy.",
            "created_at": "When the escalation policy was created.",
            "updated_at": "When the escalation policy was last updated.",
        },
    },
    "workflows": {
        "description": "Automation workflows that run in response to incident lifecycle events.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the workflow.",
            "name": "Name of the workflow.",
            "enabled": "Whether the workflow is enabled.",
            "created_at": "When the workflow was created.",
            "updated_at": "When the workflow was last updated.",
        },
    },
    "causes": {
        "description": "Root-cause categories that can be attributed to incidents.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the cause.",
            "name": "Name of the cause.",
        },
    },
}
