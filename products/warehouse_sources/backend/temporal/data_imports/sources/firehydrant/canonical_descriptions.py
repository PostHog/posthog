from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated table/column descriptions sourced from the FireHydrant API docs
# (https://docs.firehydrant.com/reference/firehydrant-api). Keys are the endpoint/schema names
# returned by `get_schemas`. Partial coverage is fine — anything not listed falls back to LLM
# enrichment with the docs_url as context.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "incidents": {
        "description": "Incidents declared in FireHydrant, including their lifecycle, severity, impact, and assignments.",
        "docs_url": "https://docs.firehydrant.com/reference/list_incidents",
        "columns": {
            "id": "UUID of the incident.",
            "name": "Name of the incident.",
            "number": "Sequential incident number.",
            "summary": "Short summary of the incident.",
            "description": "Detailed description of the incident.",
            "current_milestone": "Slug of the incident's current lifecycle milestone.",
            "severity": "Severity assigned to the incident.",
            "priority": "Priority assigned to the incident.",
            "created_at": "The time the incident was opened.",
            "started_at": "The time the incident started.",
            "discarded_at": "The time the incident was archived, if any.",
            "incident_url": "URL of the incident in FireHydrant.",
        },
    },
    "alerts": {
        "description": "Alerts ingested by FireHydrant, including Signals alerts and third-party alerts.",
        "docs_url": "https://docs.firehydrant.com/reference/list_alerts",
        "columns": {
            "id": "UUID of the alert.",
            "summary": "Summary of the alert.",
            "description": "Description of the alert.",
            "status": "Current status of the alert.",
            "priority": "Priority of the alert.",
            "started_at": "The time the alert started.",
            "ended_at": "The time the alert ended, if any.",
        },
    },
    "changes": {
        "description": "Changes tracked in FireHydrant that may be correlated with incidents.",
        "docs_url": "https://docs.firehydrant.com/reference/list_changes",
        "columns": {
            "id": "UUID of the change.",
            "created_at": "The time the change record was created.",
            "updated_at": "The time the change record was last updated.",
        },
    },
    "change_events": {
        "description": "Discrete change events (e.g. deploys) recorded in FireHydrant.",
        "docs_url": "https://docs.firehydrant.com/reference/list_change_events",
        "columns": {
            "id": "UUID of the change event.",
            "summary": "Summary of the change event.",
            "starts_at": "The time the change event started.",
            "ends_at": "The time the change event ended.",
            "created_at": "The time the change event was created.",
        },
    },
    "environments": {
        "description": "Environments (e.g. production, staging) defined in your FireHydrant catalog.",
        "docs_url": "https://docs.firehydrant.com/reference/list_environments",
        "columns": {
            "id": "UUID of the environment.",
            "name": "Name of the environment.",
            "slug": "URL-friendly identifier for the environment.",
            "created_at": "The time the environment was created.",
        },
    },
    "functionalities": {
        "description": "Functionalities (capabilities your product provides) defined in your FireHydrant catalog.",
        "docs_url": "https://docs.firehydrant.com/reference/list_functionalities",
        "columns": {
            "id": "UUID of the functionality.",
            "name": "Name of the functionality.",
            "slug": "URL-friendly identifier for the functionality.",
            "created_at": "The time the functionality was created.",
        },
    },
    "services": {
        "description": "Services in your FireHydrant service catalog.",
        "docs_url": "https://docs.firehydrant.com/reference/list_services",
        "columns": {
            "id": "UUID of the service.",
            "name": "Name of the service.",
            "slug": "URL-friendly identifier for the service.",
            "created_at": "The time the service was created.",
        },
    },
    "teams": {
        "description": "Teams configured in FireHydrant.",
        "docs_url": "https://docs.firehydrant.com/reference/list_teams",
        "columns": {
            "id": "UUID of the team.",
            "name": "Name of the team.",
            "slug": "URL-friendly identifier for the team.",
            "created_at": "The time the team was created.",
        },
    },
    "users": {
        "description": "Users in your FireHydrant organization.",
        "docs_url": "https://docs.firehydrant.com/reference/list_users",
        "columns": {
            "id": "UUID of the user.",
            "name": "Name of the user.",
            "email": "Email address of the user.",
            "created_at": "The time the user was created.",
        },
    },
    "incident_roles": {
        "description": "Incident roles (e.g. Incident Commander) defined in FireHydrant.",
        "docs_url": "https://docs.firehydrant.com/reference/list_incident_roles",
        "columns": {
            "id": "UUID of the incident role.",
            "name": "Name of the incident role.",
            "created_at": "The time the incident role was created.",
        },
    },
    "incident_types": {
        "description": "Incident types that pre-fill incident attributes when declared.",
        "docs_url": "https://docs.firehydrant.com/reference/list_incident_types",
        "columns": {
            "id": "UUID of the incident type.",
            "name": "Name of the incident type.",
            "created_at": "The time the incident type was created.",
        },
    },
    "incident_tags": {
        "description": "Tags that can be applied to incidents.",
        "docs_url": "https://docs.firehydrant.com/reference/list_incident_tags",
        "columns": {
            "name": "Name of the tag (its unique identifier).",
        },
    },
    "priorities": {
        "description": "Incident priorities (e.g. P1, P2) defined in FireHydrant.",
        "docs_url": "https://docs.firehydrant.com/reference/list_priorities",
        "columns": {
            "slug": "Unique slug for the priority (e.g. P1).",
            "description": "Description of the priority.",
            "position": "Ordering position of the priority.",
            "created_at": "The time the priority was created.",
        },
    },
    "severities": {
        "description": "Incident severities defined in FireHydrant.",
        "docs_url": "https://docs.firehydrant.com/reference/list_severities",
        "columns": {
            "slug": "Unique slug for the severity (e.g. SEV1).",
            "description": "Description of the severity.",
            "position": "Ordering position of the severity.",
            "color": "Display color for the severity.",
            "created_at": "The time the severity was created.",
        },
    },
    "custom_field_definitions": {
        "description": "Definitions of the custom fields available on incidents.",
        "docs_url": "https://docs.firehydrant.com/reference/list_custom_fields_definitions",
        "columns": {
            "field_id": "Unique identifier for the custom field definition.",
            "slug": "URL-friendly identifier for the custom field.",
        },
    },
    "integrations": {
        "description": "Integrations connected to your FireHydrant organization.",
        "docs_url": "https://docs.firehydrant.com/reference/list_integrations",
        "columns": {
            "id": "UUID of the integration.",
            "created_at": "The time the integration was created.",
        },
    },
    "runbooks": {
        "description": "Runbooks that automate incident response steps.",
        "docs_url": "https://docs.firehydrant.com/reference/list_runbooks",
        "columns": {
            "id": "UUID of the runbook.",
            "name": "Name of the runbook.",
            "created_at": "The time the runbook was created.",
        },
    },
    "runbook_executions": {
        "description": "Executions of runbooks against incidents.",
        "docs_url": "https://docs.firehydrant.com/reference/list_runbooks_executions",
        "columns": {
            "id": "UUID of the runbook execution.",
            "created_at": "The time the runbook execution started.",
        },
    },
    "webhooks": {
        "description": "Webhooks configured to receive FireHydrant events.",
        "docs_url": "https://docs.firehydrant.com/reference/list_webhooks",
        "columns": {
            "id": "UUID of the webhook.",
            "created_at": "The time the webhook was created.",
        },
    },
    "signals_on_call": {
        "description": "FireHydrant Signals on-call schedules across the organization.",
        "docs_url": "https://docs.firehydrant.com/reference/list_signals_on_call",
        "columns": {
            "id": "Identifier of the on-call schedule.",
        },
    },
    "post_mortem_reports": {
        "description": "Retrospective (post-mortem) reports generated for incidents.",
        "docs_url": "https://docs.firehydrant.com/reference/list_post_mortems_reports",
        "columns": {
            "id": "UUID of the retrospective report.",
            "name": "Name of the retrospective report.",
            "created_at": "The time the report was created.",
        },
    },
    "scheduled_maintenances": {
        "description": "Scheduled maintenance windows tracked in FireHydrant.",
        "docs_url": "https://docs.firehydrant.com/reference/list_scheduled_maintenances",
        "columns": {
            "id": "UUID of the scheduled maintenance.",
            "name": "Name of the scheduled maintenance.",
            "created_at": "The time the scheduled maintenance was created.",
        },
    },
    "task_lists": {
        "description": "Reusable task lists that can be attached to incidents.",
        "docs_url": "https://docs.firehydrant.com/reference/list_task_lists",
        "columns": {
            "id": "UUID of the task list.",
            "name": "Name of the task list.",
            "created_at": "The time the task list was created.",
        },
    },
    "checklist_templates": {
        "description": "Checklist templates used during incident response.",
        "docs_url": "https://docs.firehydrant.com/reference/list_checklist_templates",
        "columns": {
            "id": "UUID of the checklist template.",
            "name": "Name of the checklist template.",
            "created_at": "The time the checklist template was created.",
        },
    },
}
