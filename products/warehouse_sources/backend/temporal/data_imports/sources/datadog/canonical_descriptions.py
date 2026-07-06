"""Canonical, documentation-sourced descriptions for Datadog endpoints and columns.

Sourced from the official Datadog API reference (https://docs.datadoghq.com/api/latest/). Keyed by the
endpoint names in `settings.py` `DATADOG_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Datadog table. v2 endpoints have their JSON:API `attributes` flattened to the root, so column
names below reflect the flattened shape. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "logs": {
        "description": "A single log event ingested into Datadog Log Management.",
        "docs_url": "https://docs.datadoghq.com/api/latest/logs/#search-logs",
        "columns": {
            "id": "Unique identifier for the log event.",
            "timestamp": "Time at which the log event occurred.",
            "message": "The log message body.",
            "status": "Severity status of the log (e.g. info, warn, error).",
            "service": "Name of the service that emitted the log.",
            "host": "Host that emitted the log.",
            "tags": "Tags attached to the log event.",
            "attributes": "Structured attributes parsed from the log.",
        },
    },
    "audit_logs": {
        "description": "An audit trail event recording a change or action in the Datadog account.",
        "docs_url": "https://docs.datadoghq.com/api/latest/audit/#search-audit-logs-events",
        "columns": {
            "id": "Unique identifier for the audit event.",
            "timestamp": "Time at which the audited action occurred.",
            "message": "Description of the audited action.",
            "service": "Service or product area the action relates to.",
            "tags": "Tags attached to the audit event.",
        },
    },
    "events": {
        "description": "An event from the Datadog event stream (alerts, deployments, comments, and more).",
        "docs_url": "https://docs.datadoghq.com/api/latest/events/#get-a-list-of-events",
        "columns": {
            "id": "Unique identifier for the event.",
            "timestamp": "Time at which the event occurred.",
            "title": "Title of the event.",
            "message": "Body text of the event.",
            "tags": "Tags attached to the event.",
            "aggregation_key": "Key used to group related events together.",
        },
    },
    "dashboards": {
        "description": "A Datadog dashboard — a configurable set of widgets visualizing metrics and logs.",
        "docs_url": "https://docs.datadoghq.com/api/latest/dashboards/#get-all-dashboards",
        "columns": {
            "id": "Unique identifier for the dashboard.",
            "title": "Title of the dashboard.",
            "description": "Description of the dashboard.",
            "url": "Relative URL of the dashboard within Datadog.",
            "layout_type": "Layout type of the dashboard (e.g. ordered, free).",
            "author_handle": "Handle of the user who created the dashboard.",
            "created_at": "Time at which the dashboard was created.",
            "modified_at": "Time at which the dashboard was last modified.",
            "is_read_only": "Whether the dashboard is read-only.",
        },
    },
    "monitors": {
        "description": "A monitor that watches a metric, log, or check and alerts when conditions are met.",
        "docs_url": "https://docs.datadoghq.com/api/latest/monitors/#get-all-monitor-details",
        "columns": {
            "id": "Unique identifier for the monitor.",
            "name": "Name of the monitor.",
            "type": "Type of the monitor (e.g. metric alert, log alert).",
            "query": "The query that defines the monitor's alerting condition.",
            "message": "Notification message sent when the monitor triggers.",
            "overall_state": "Current overall state of the monitor (e.g. OK, Alert, No Data).",
            "tags": "Tags attached to the monitor.",
            "created": "Time at which the monitor was created.",
            "modified": "Time at which the monitor was last modified.",
        },
    },
    "users": {
        "description": "A user account in the Datadog organization.",
        "docs_url": "https://docs.datadoghq.com/api/latest/users/#list-all-users",
        "columns": {
            "id": "Unique identifier for the user.",
            "name": "The user's full name.",
            "email": "The user's email address.",
            "handle": "The user's handle (login identifier).",
            "status": "Status of the user account (e.g. active, pending, disabled).",
            "disabled": "Whether the user account is disabled.",
            "created_at": "Time at which the user account was created.",
            "modified_at": "Time at which the user account was last modified.",
        },
    },
    "incidents": {
        "description": "An incident tracked in Datadog Incident Management.",
        "docs_url": "https://docs.datadoghq.com/api/latest/incidents/#get-a-list-of-incidents",
        "columns": {
            "id": "Unique identifier for the incident.",
            "title": "Title of the incident.",
            "severity": "Severity level of the incident.",
            "state": "Current state of the incident (e.g. active, stable, resolved).",
            "customer_impacted": "Whether customers were impacted by the incident.",
            "created": "Time at which the incident was created.",
            "modified": "Time at which the incident was last modified.",
            "resolved": "Time at which the incident was resolved, if applicable.",
        },
    },
    "slos": {
        "description": "A service level objective (SLO) defining a reliability target over a time window.",
        "docs_url": "https://docs.datadoghq.com/api/latest/service-level-objectives/#get-all-slos",
        "columns": {
            "id": "Unique identifier for the SLO.",
            "name": "Name of the SLO.",
            "description": "Description of the SLO.",
            "type": "Type of the SLO (e.g. metric, monitor).",
            "tags": "Tags attached to the SLO.",
            "created_at": "Time at which the SLO was created, as a Unix timestamp.",
            "modified_at": "Time at which the SLO was last modified, as a Unix timestamp.",
        },
    },
    "synthetic_tests": {
        "description": "A Synthetic monitoring test (API or browser test) that probes endpoints or flows.",
        "docs_url": "https://docs.datadoghq.com/api/latest/synthetics/#get-the-list-of-all-synthetic-tests",
        "columns": {
            "public_id": "Public identifier for the synthetic test.",
            "name": "Name of the synthetic test.",
            "type": "Type of the test (e.g. api, browser).",
            "subtype": "Subtype of the test (e.g. http, ssl, dns).",
            "status": "Status of the test (e.g. live, paused).",
            "tags": "Tags attached to the test.",
        },
    },
    "downtimes": {
        "description": "A scheduled downtime that mutes monitor alerts over a time window.",
        "docs_url": "https://docs.datadoghq.com/api/latest/downtimes/#get-all-downtimes",
        "columns": {
            "id": "Unique identifier for the downtime.",
            "message": "Message attached to the downtime.",
            "scope": "Scope of monitors the downtime applies to.",
            "status": "Current status of the downtime (e.g. active, canceled, scheduled).",
            "created": "Time at which the downtime was created.",
            "modified": "Time at which the downtime was last modified.",
        },
    },
}
