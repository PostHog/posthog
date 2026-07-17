from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://uptimerobot.com/api/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "monitors": {
        "description": "A monitored endpoint (website, ping, port, keyword, or heartbeat check) with its current status and uptime ratios.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the monitor.",
            "friendly_name": "Display name given to the monitor.",
            "url": "The URL or IP address being monitored.",
            "type": "Monitor type: 1 = HTTP(S), 2 = keyword, 3 = ping, 4 = port, 5 = heartbeat.",
            "sub_type": "For port monitors, the service checked: 1 = HTTP, 2 = HTTPS, 3 = FTP, 4 = SMTP, 5 = POP3, 6 = IMAP, 99 = custom port.",
            "keyword_type": "For keyword monitors, whether the check alerts when the keyword exists (1) or does not exist (2).",
            "keyword_value": "For keyword monitors, the keyword searched for in the response body.",
            "port": "For port monitors, the port number checked.",
            "interval": "Interval between checks, in seconds.",
            "status": "Current status: 0 = paused, 1 = not checked yet, 2 = up, 8 = seems down, 9 = down.",
            "create_datetime": "Unix timestamp of when the monitor was created.",
            "custom_uptime_ratio": "Dash-separated uptime ratios for the last 1, 7, 30, and 365 days (e.g. 100.000-99.987-99.998-99.999).",
            "all_time_uptime_ratio": "Uptime ratio since the monitor was created, as a percentage.",
        },
    },
    "monitor_logs": {
        "description": "Up/down/pause event log entries for each monitor, one row per event.",
        "docs_url": _DOCS_URL,
        "columns": {
            "monitor_id": "Identifier of the monitor the log entry belongs to.",
            "type": "Event type: 1 = down, 2 = up, 98 = monitor started, 99 = monitor paused.",
            "datetime": "Unix timestamp of when the event occurred.",
            "duration": "Duration of the event state, in seconds.",
            "reason": "Reason for the event, with a code and human-readable detail (e.g. HTTP status or timeout).",
        },
    },
    "response_times": {
        "description": "Response-time samples recorded for each monitor's checks.",
        "docs_url": _DOCS_URL,
        "columns": {
            "monitor_id": "Identifier of the monitor the sample belongs to.",
            "datetime": "Unix timestamp of when the response time was recorded.",
            "value": "Response time in milliseconds.",
        },
    },
    "alert_contacts": {
        "description": "Contacts notified when a monitor changes state (email, SMS, webhook, Slack, etc.).",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the alert contact.",
            "friendly_name": "Display name given to the alert contact.",
            "type": "Contact channel: 1 = SMS, 2 = email, 3 = Twitter, 5 = webhook, 6 = Pushbullet, 7 = Zapier, 9 = Pushover, 11 = Slack, and other integration types.",
            "status": "Contact status: 0 = not activated, 1 = paused, 2 = active.",
            "value": "The contact's address for the channel (email address, phone number, webhook URL, etc.).",
        },
    },
    "maintenance_windows": {
        "description": "Scheduled maintenance windows during which monitors pause and alerts are suppressed.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the maintenance window.",
            "friendly_name": "Display name given to the maintenance window.",
            "type": "Recurrence: 1 = once, 2 = daily, 3 = weekly, 4 = monthly.",
            "value": "For weekly/monthly windows, the days it applies to (e.g. 2-4-5 for Tuesday, Thursday, Friday).",
            "start_time": "Start time of the window (Unix timestamp for one-off windows, HH:mm for recurring ones).",
            "duration": "Duration of the maintenance window, in minutes.",
            "status": "Window status: 0 = paused, 1 = active.",
        },
    },
    "status_pages": {
        "description": "Public status pages (PSPs) that display the status of selected monitors.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Unique identifier of the status page.",
            "friendly_name": "Display name given to the status page.",
            "standard_url": "The default stats.uptimerobot.com URL of the status page.",
            "custom_url": "Custom domain configured for the status page, if any.",
            "monitors": "Monitors shown on the status page (0 means all monitors).",
            "sort": "Sort order of monitors on the page: 1 = friendly name (a-z), 2 = friendly name (z-a), 3 = status (up-down-paused), 4 = status (down-up-paused).",
            "status": "Status page status: 0 = paused, 1 = active.",
        },
    },
}
