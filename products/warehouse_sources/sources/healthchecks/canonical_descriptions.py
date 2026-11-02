from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the Healthchecks.io Management API v3 docs: https://healthchecks.io/docs/api/
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "checks": {
        "description": "Each check monitors one cron job or scheduled task, tracking its current status and configuration.",
        "docs_url": "https://healthchecks.io/docs/api/",
        "columns": {
            "id": "Stable identifier for the check: its UUID for full API keys, or its unique_key for read-only keys.",
            "uuid": "Unique identifier of the check. Omitted when using a read-only API key.",
            "unique_key": "Stable, read-only identifier of the check. Present only when using a read-only API key.",
            "name": "Human-readable name of the check.",
            "slug": "URL-friendly version of the check's name.",
            "tags": "Space-separated list of tags assigned to the check.",
            "desc": "Free-form description of the check.",
            "grace": "Grace period, in seconds, before a late check is reported as down.",
            "n_pings": "Total number of pings the check has received.",
            "status": "Current status: new, up, grace, down, or paused.",
            "started": "Whether the check is currently in the middle of a run (a start signal was received).",
            "last_ping": "ISO 8601 timestamp of the last received ping.",
            "next_ping": "ISO 8601 timestamp when the next ping is expected.",
            "manual_resume": "Whether a paused check must be resumed manually rather than by the next ping.",
            "methods": "Allowed HTTP methods for pinging the check.",
            "timeout": "Expected period between pings, in seconds (for simple checks).",
            "schedule": "Cron expression describing the check's schedule (for cron checks).",
            "tz": "Timezone the cron schedule is evaluated in.",
            "ping_url": "URL to ping to signal a successful run. Omitted when using a read-only API key.",
            "update_url": "API URL to update the check. Omitted when using a read-only API key.",
            "channels": "Comma-separated list of integration IDs assigned to the check.",
        },
    },
    "channels": {
        "description": "Notification integrations (email, SMS, webhook, chat, ...) that alerts are delivered through.",
        "docs_url": "https://healthchecks.io/docs/api/",
        "columns": {
            "id": "Unique identifier of the integration.",
            "name": "Human-readable name of the integration.",
            "kind": "Type of integration (e.g. email, sms, webhook, slack).",
        },
    },
    "flips": {
        "description": "Status transitions (up/down) for each check over time. The most analytics-valuable stream.",
        "docs_url": "https://healthchecks.io/docs/api/",
        "columns": {
            "check_id": "Identifier of the check this flip belongs to (its UUID or unique_key).",
            "timestamp": "ISO 8601 timestamp when the status change occurred.",
            "up": "New status after the flip: 1 for up, 0 for down.",
        },
    },
    "pings": {
        "description": "Recent execution log for each check. Limited to the plan-bounded retention window (100 free / 1000 paid).",
        "docs_url": "https://healthchecks.io/docs/api/",
        "columns": {
            "check_id": "Identifier of the check this ping belongs to (its UUID).",
            "type": "Ping type: success, start, fail, log, or ign (ignored).",
            "date": "ISO 8601 timestamp when the ping was received.",
            "n": "Sequential ping number, monotonically increasing per check.",
            "scheme": "Protocol the ping was made over (http, https, or email).",
            "remote_addr": "IP address the ping originated from.",
            "method": "HTTP method used for the ping.",
            "ua": "User agent string of the ping request.",
            "rid": "Client-supplied run ID (rid query parameter), if any.",
            "body_url": "API URL to fetch the ping's request body, if a body was stored.",
            "duration": "For success pings following a start ping, the measured run duration in seconds.",
        },
    },
}
