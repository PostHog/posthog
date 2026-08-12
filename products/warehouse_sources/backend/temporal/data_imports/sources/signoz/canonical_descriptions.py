from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "logs": {
        "description": "Raw log records ingested into SigNoz, one row per log line.",
        "docs_url": "https://signoz.io/docs/logs-management/logs-api/overview/",
        "columns": {
            "id": "Unique identifier of the log record.",
            "timestamp": "Time the log record was produced.",
            "body": "The log message body.",
            "severity_text": "Severity level as text (e.g. INFO, ERROR).",
            "severity_number": "Numeric severity level per the OpenTelemetry log data model.",
            "trace_id": "Trace ID of the request the log was emitted in, if correlated.",
            "span_id": "Span ID of the operation the log was emitted in, if correlated.",
            "trace_flags": "W3C trace flags of the correlated trace context.",
            "scope_name": "Name of the instrumentation scope that produced the log.",
            "scope_version": "Version of the instrumentation scope that produced the log.",
            "attributes_string": "String-valued log attributes.",
            "attributes_number": "Number-valued log attributes.",
            "attributes_bool": "Boolean-valued log attributes.",
            "resources_string": "Resource attributes of the emitting service (e.g. service name, host).",
        },
    },
    "traces": {
        "description": "Spans from distributed traces ingested into SigNoz, one row per span.",
        "docs_url": "https://signoz.io/docs/traces-management/trace-api/payload-model/",
        "columns": {
            "trace_id": "Identifier of the trace the span belongs to.",
            "span_id": "Unique identifier of the span within its trace.",
            "parent_span_id": "Span ID of the parent span; empty for root spans.",
            "timestamp": "Start time of the span.",
            "name": "Operation name of the span.",
            "duration_nano": "Duration of the span in nanoseconds.",
        },
    },
    "alert_rules": {
        "description": "Alert rule definitions configured in SigNoz.",
        "docs_url": "https://signoz.io/docs/userguide/alerts-management/",
        "columns": {
            "id": "Unique identifier of the alert rule.",
            "state": "Current evaluation state of the rule (e.g. inactive, pending, firing).",
            "alert": "Name of the alert rule.",
            "alertType": "Signal the rule evaluates (metrics, logs, traces, or exceptions).",
            "ruleType": "Rule engine type (threshold or PromQL).",
            "evalWindow": "Time window the rule condition is evaluated over.",
            "frequency": "How often the rule is evaluated.",
            "condition": "Rule condition, including the composite query and target threshold.",
            "labels": "Labels attached to alerts fired by the rule.",
            "annotations": "Annotations attached to alerts fired by the rule.",
            "disabled": "Whether the rule is disabled.",
            "preferredChannels": "Notification channels the rule routes alerts to.",
            "createAt": "Time the rule was created.",
            "createBy": "User who created the rule.",
            "updateAt": "Time the rule was last updated.",
            "updateBy": "User who last updated the rule.",
        },
    },
    "dashboards": {
        "description": "Dashboard definitions configured in SigNoz.",
        "docs_url": "https://signoz.io/docs/userguide/manage-dashboards/",
        "columns": {
            "id": "Unique identifier of the dashboard.",
            "data": "Full dashboard definition (layout, panels, variables).",
            "locked": "Whether the dashboard is locked against edits.",
            "createdAt": "Time the dashboard was created.",
            "createdBy": "User who created the dashboard.",
            "updatedAt": "Time the dashboard was last updated.",
            "updatedBy": "User who last updated the dashboard.",
        },
    },
    "notification_channels": {
        # The receiver config `data` field is intentionally not imported: it holds secrets
        # (Slack webhook URLs, PagerDuty keys) that must not land in a warehouse table.
        "description": "Notification channels alerts can be routed to (Slack, PagerDuty, webhook, etc.). The receiver configuration payload is omitted because it contains credentials.",
        "docs_url": "https://signoz.io/docs/userguide/alerts-management/",
        "columns": {
            "id": "Unique identifier of the notification channel.",
            "name": "Name of the notification channel.",
            "type": "Channel type (e.g. slack, pagerduty, webhook, email).",
            "createdAt": "Time the channel was created.",
            "updatedAt": "Time the channel was last updated.",
        },
    },
}
