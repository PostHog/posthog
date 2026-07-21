from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "monitors": {
        "description": "A Cronitor monitor: a cron job, heartbeat, or uptime check, with its configuration and current read-only state.",
        "docs_url": "https://cronitor.io/docs/monitor-api",
        "columns": {
            "key": "Unique identifier of the monitor, used in API URLs.",
            "name": "Display name of the monitor. Defaults to the key.",
            "type": "Monitor type, e.g. job, check, or heartbeat.",
            "schedule": "The schedule the monitor is expected to run on (e.g. a cron expression).",
            "created": "ISO 8601 timestamp of when the monitor was created.",
            "passing": "Whether the monitor is currently passing its assertions.",
            "running": "Whether the job is currently running (job monitors only).",
            "paused": "Whether alerting for the monitor is paused.",
            "disabled": "Whether the monitor is disabled.",
            "initialized": "Whether the monitor has received telemetry at least once.",
            "group": "Key of the group the monitor belongs to.",
            "next_expected_at": "Timestamp of when the next telemetry event is expected per the schedule.",
            "latest_event": "The most recent telemetry event, with stamp, state, message, and duration.",
            "latest_issue": "The most recent issue (alert) raised for the monitor, if any.",
            "assertions": "The assertions evaluated against the monitor's telemetry.",
            "notify": "Alert notification configuration for the monitor.",
            "tags": "Tags attached to the monitor.",
        },
    },
    "invocations": {
        "description": "Recent invocations (runs) of each job monitor, from the monitor detail's latest_invocations. A snapshot of recent history, refreshed each sync.",
        "docs_url": "https://cronitor.io/docs/monitor-api",
        "columns": {
            "monitor_key": "Key of the monitor this invocation belongs to.",
            "series": "Series identifier linking the run and complete telemetry events of one invocation.",
            "started_at": "When the job run started.",
            "ended_at": "When the job run completed, if it has.",
            "duration": "Total duration of the run in milliseconds.",
        },
    },
    "metrics": {
        "description": "Time-series reliability metrics per monitor, from the Metrics API. One row per monitor, dimension, and timestamp.",
        "docs_url": "https://cronitor.io/docs/metrics-api",
        "columns": {
            "monitor_key": "Key of the monitor the data point belongs to.",
            "dimension": "Dimension the data point is grouped by, e.g. env:production.",
            "stamp": "Unix timestamp of the data point.",
            "duration_p50": "Median run duration in the interval, in milliseconds.",
            "duration_p90": "90th-percentile run duration in the interval, in milliseconds.",
            "success_rate": "Share of runs in the interval that completed successfully.",
            "run_count": "Number of runs recorded in the interval.",
        },
    },
}
