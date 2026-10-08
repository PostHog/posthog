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
    "error_tracking_issues": {
        "description": (
            "A grouped error from Datadog Error Tracking, combining APM traces, logs, and RUM. "
            "The table is rebuilt on every sync from the last 14 days of activity, so it holds issues with errors in that window."
        ),
        "docs_url": "https://docs.datadoghq.com/api/latest/error-tracking/#search-error-tracking-issues",
        "columns": {
            "id": "Unique identifier for the error tracking issue.",
            "error_type": "Type or class of the error, for example an exception name.",
            "error_message": "Message of the error that defines the issue.",
            "file_path": "Path of the source file where the error occurred.",
            "function_name": "Name of the function where the error occurred.",
            "service": "Name of the service the error comes from.",
            "platform": "Platform the error comes from (for example BACKEND, BROWSER, ANDROID, or IOS).",
            "languages": "Programming languages of the code the error comes from.",
            "state": "Triage state of the issue (OPEN, ACKNOWLEDGED, RESOLVED, IGNORED, or EXCLUDED).",
            "is_crash": "Whether the error crashed the application.",
            "first_seen": "Time the issue was first seen, as an ISO 8601 UTC string.",
            "last_seen": "Time the issue was last seen, as an ISO 8601 UTC string.",
            "first_seen_version": "Application version in which the issue was first seen.",
            "last_seen_version": "Application version in which the issue was last seen.",
            "regression": "Details of the latest regression of the issue: when it regressed, in which version, and when it was resolved.",
            "window_total_count": "Number of error events for the issue in the synced window. When the window was split to stay under the API limit, the counts of the parts are added up.",
            "window_impacted_sessions": "Number of sessions affected in the synced window. When the window was split, this is the largest count of any part, so it can be lower than the true number.",
            "window_impacted_users": "Number of users affected in the synced window. When the window was split, this is the largest count of any part, so it can be lower than the true number.",
        },
    },
    "error_spans": {
        "description": (
            "An APM span with an error status. Only spans matching status:error are synced, "
            "because span volume is too high to sync in full."
        ),
        "docs_url": "https://docs.datadoghq.com/api/latest/spans/#get-a-list-of-spans",
        "columns": {
            "id": "Unique identifier for the span.",
            "service": "Name of the service that emitted the span.",
            "resource_name": "Resource the span measured, for example an endpoint or a query.",
            "operation_name": "Name of the operation the span measured.",
            "resource_hash": "Hash of the span's resource.",
            "env": "Environment the span was recorded in.",
            "host": "Host that emitted the span.",
            "trace_id": "Identifier of the trace the span belongs to.",
            "span_id": "Identifier of the span within its trace.",
            "parent_id": "Identifier of the parent span, if any.",
            "status": "Status of the span. Always error in this table.",
            "error": "Error details of the span, such as the error type.",
            "custom": "Custom span attributes, including error message and stack trace when the tracer sets them.",
            "tags": "Tags attached to the span.",
            "start_timestamp": "Time at which the span started, as an ISO 8601 UTC string.",
            "end_timestamp": "Time at which the span ended, as an ISO 8601 UTC string.",
        },
    },
    "error_logs": {
        "description": (
            "A log event with the error status. Only logs matching status:error are synced. "
            "Use the logs table for every log level."
        ),
        "docs_url": "https://docs.datadoghq.com/api/latest/logs/#search-logs",
        "columns": {
            "id": "Unique identifier for the log event.",
            "service": "Name of the service that emitted the log.",
            "host": "Host that emitted the log.",
            "message": "The log message body.",
            "status": "Severity status of the log. Always error in this table.",
            "tags": "Tags attached to the log event.",
            "timestamp": "Time at which the log event occurred.",
        },
    },
    "monitor_alerts": {
        "description": (
            "A Datadog monitor alert event that is firing (status error). "
            "Only events matching source:alert status:error are synced. "
            "The table is rebuilt on every sync from the last 7 days."
        ),
        "docs_url": "https://docs.datadoghq.com/api/latest/events/#get-a-list-of-events",
        "columns": {
            "id": "Unique identifier for the event.",
            "type": "JSON:API resource type of the event.",
            "timestamp": "Time at which the alert event occurred, as an ISO 8601 UTC string.",
            "message": "Free-text notification body of the alert.",
            "tags": "Tags attached to the event.",
            "attributes": (
                "Nested object with the alert details: status (error means firing), title, monitor_id, priority, "
                "service, evt (type of monitor), and monitor (id, name, type, alert cycle key, state transition, "
                "result links)."
            ),
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
    "metrics": {
        "description": "A metric name that has actively reported data to Datadog in the lookback window.",
        "docs_url": "https://docs.datadoghq.com/api/latest/metrics/#get-active-metrics-list",
        "columns": {
            "metric": "Name of the actively reporting metric.",
        },
    },
    "usage_hourly": {
        "description": "Hourly usage for one product family, for one organization.",
        "docs_url": "https://docs.datadoghq.com/api/latest/usage-metering/#get-hourly-usage-by-product-family",
        "columns": {
            "id": "Unique identifier of the usage record.",
            "timestamp": "The hour the usage was measured in, UTC.",
            "product_family": "The product the usage is reported for.",
            "org_name": "Name of the organization the usage belongs to.",
            "public_id": "Public identifier of the organization.",
            "account_name": "Name of the account the organization belongs to.",
            "account_public_id": "Public identifier of the account.",
            "region": "Datadog region the organization belongs to.",
            "measurements": "Measured usage values for the product family in the hour, by usage type.",
        },
    },
    "usage_summary": {
        "description": "Daily usage across every billing dimension, aggregated over all organizations in the account.",
        "docs_url": "https://docs.datadoghq.com/api/latest/usage-metering/#get-usage-across-your-account",
        "columns": {
            "date": "The day the usage was measured on.",
            "orgs": "Per-organization breakdown of the day's usage.",
        },
    },
    "usage_billable_summary": {
        "description": "Billable usage for one organization over one billing period.",
        "docs_url": "https://docs.datadoghq.com/api/latest/usage-metering/#get-billable-usage-across-your-account",
        "columns": {
            "org_name": "Name of the organization.",
            "public_id": "Public identifier of the organization.",
            "account_name": "Name of the account the organization belongs to.",
            "account_public_id": "Public identifier of the account.",
            "start_date": "First date of billable usage in the period.",
            "end_date": "Last date of billable usage in the period.",
            "num_orgs": "Number of organizations covered by the summary.",
            "usage": "Billable usage amounts for the period, by billing dimension.",
        },
    },
    "usage_estimated_cost": {
        "description": "Estimated cost for the current and previous month. Datadog delays it by up to 72 hours from when the cost was incurred.",
        "docs_url": "https://docs.datadoghq.com/api/latest/usage-metering/#get-estimated-cost-across-your-account",
        "columns": {
            "id": "Unique identifier of the cost record.",
            "date": "The month the cost applies to.",
            "org_name": "Name of the organization the cost belongs to.",
            "public_id": "Public identifier of the organization.",
            "account_name": "Name of the account the organization belongs to.",
            "account_public_id": "Public identifier of the account.",
            "charges": "Breakdown of the estimated charges by product.",
            "total_cost": "Total estimated cost for the month.",
        },
    },
    "usage_historical_cost": {
        "description": "Final cost per month, per organization. Datadog publishes a month by the 16th of the month after it.",
        "docs_url": "https://docs.datadoghq.com/api/latest/usage-metering/#get-historical-cost-across-your-account",
        "columns": {
            "id": "Unique identifier of the cost record.",
            "date": "The month the cost applies to.",
            "org_name": "Name of the organization the cost belongs to.",
            "public_id": "Public identifier of the organization.",
            "account_name": "Name of the account the organization belongs to.",
            "account_public_id": "Public identifier of the account.",
            "charges": "Breakdown of the charges by product.",
            "total_cost": "Total cost for the month.",
        },
    },
    "slo_corrections": {
        "description": "A correction that excludes a time window from an SLO's error budget, for example a maintenance window.",
        "docs_url": "https://docs.datadoghq.com/api/latest/service-level-objective-corrections/#get-all-slo-corrections",
        "columns": {
            "id": "Unique identifier for the SLO correction.",
            "slo_id": "Identifier of the SLO the correction applies to.",
            "category": "Why the correction was made (e.g. Scheduled Maintenance, Deployment).",
            "description": "Description of the correction.",
            "start": "Start of the corrected window, in epoch seconds.",
            "end": "End of the corrected window, in epoch seconds.",
            "duration": "Length of a recurring correction, in seconds.",
            "rrule": "Recurrence rule for a repeating correction.",
            "timezone": "Timezone the correction window is expressed in.",
            "creator": "User who created the correction.",
            "created_at": "Time the correction was created, in epoch seconds.",
            "modified_at": "Time the correction was last modified, in epoch seconds.",
        },
    },
    "slo_history": {
        "description": "Error-budget history for one SLO over the synced window, including its SLI value against each configured threshold.",
        "docs_url": "https://docs.datadoghq.com/api/latest/service-level-objectives/#get-an-slos-history",
        "columns": {
            "slo_id": "Identifier of the SLO the history belongs to.",
            "from_ts": "Start of the history window, in epoch seconds.",
            "to_ts": "End of the history window, in epoch seconds.",
            "type": "Source type of the SLO (e.g. metric, monitor).",
            "overall": "SLI value and error budget across the whole window.",
            "thresholds": "SLI value and error budget per configured timeframe.",
            "groups": "SLI data per group, for grouped monitor SLOs.",
            "monitors": "SLI data per monitor, for multi-monitor SLOs.",
            "group_by": "Grouping parameters, for metric SLOs with a group-by clause.",
        },
    },
    "teams": {
        "description": "A Datadog team, the owner handle attached to monitors, incidents, SLOs and services.",
        "docs_url": "https://docs.datadoghq.com/api/latest/teams/#get-all-teams",
        "columns": {
            "id": "Unique identifier for the team.",
            "name": "Display name of the team.",
            "handle": "Handle used to reference the team on other resources.",
            "description": "Markdown description shown on the team's homepage.",
            "avatar": "Avatar character for the team.",
            "user_count": "Number of users in the team.",
            "link_count": "Number of links attached to the team.",
            "is_managed": "Whether team membership is managed externally.",
            "created_at": "Time the team was created.",
            "modified_at": "Time the team was last modified.",
        },
    },
    "team_memberships": {
        "description": "A user's membership of a team, including the role they hold in it.",
        "docs_url": "https://docs.datadoghq.com/api/latest/teams/#get-team-memberships",
        "columns": {
            "id": "Unique identifier for the membership.",
            "team_id": "Identifier of the team the membership belongs to.",
            "role": "Role the user holds in the team (e.g. admin).",
            "provisioned_by": "How the membership was provisioned (e.g. service_account, saml_mapping).",
            "provisioned_by_id": "Identifier of the user or service account that provisioned the membership.",
            "relationships": "Links to the team and user the membership joins.",
        },
    },
}
