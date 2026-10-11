from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions are taken from the StatusCake API v1 docs (https://developers.statuscake.com/api/).
# The "test_id" column on every per-test history table is injected by the connector (the raw
# history rows carry no test identifier), so it is documented here even though it isn't part of
# the raw endpoint payload.
_TEST_ID_COLUMN = "Identifier of the test this record belongs to (added by the connector)."

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "uptime_tests": {
        "description": "Uptime checks configured in your StatusCake account.",
        "docs_url": "https://developers.statuscake.com/api/#tag/uptime",
        "columns": {
            "id": "Unique identifier for the uptime check.",
            "name": "Display name of the uptime check.",
            "website_url": "URL or IP address the check monitors.",
            "test_type": "Type of check (HTTP, HEAD, TCP, DNS, SMTP, SSH, PING, PUSH).",
            "check_rate": "Number of seconds between checks.",
            "contact_groups": "List of contact group ids alerted by this check.",
            "paused": "Whether the check is paused.",
            "status": "Current status of the check (up or down).",
            "tags": "List of tags assigned to the check.",
            "uptime": "Uptime percentage of the check.",
        },
    },
    "uptime_history": {
        "description": "Raw uptime check results (one row per check execution) for every uptime test.",
        "docs_url": "https://developers.statuscake.com/api/#tag/uptime/operation/list-uptime-test-history",
        "columns": {
            "test_id": _TEST_ID_COLUMN,
            "created_at": "Timestamp the check result was recorded.",
            "status_code": "HTTP status code returned by the monitored endpoint.",
            "location": "Monitoring location the check ran from.",
            "performance": "Time taken to complete the check, in milliseconds.",
        },
    },
    "uptime_periods": {
        "description": "Continuous up/down periods for every uptime test — the basis for availability and SLA reporting.",
        "docs_url": "https://developers.statuscake.com/api/#tag/uptime/operation/list-uptime-test-periods",
        "columns": {
            "test_id": _TEST_ID_COLUMN,
            "status": "Status of the test during the period (up or down).",
            "created_at": "Timestamp the period started.",
        },
    },
    "uptime_alerts": {
        "description": "Alerts triggered by uptime tests changing state.",
        "docs_url": "https://developers.statuscake.com/api/#tag/uptime/operation/list-uptime-test-alerts",
        "columns": {
            "test_id": _TEST_ID_COLUMN,
            "id": "Unique identifier for the alert.",
            "status": "Status of the test when the alert triggered (up or down).",
            "status_code": "HTTP status code returned by the monitored endpoint at alert time.",
            "triggered_at": "Timestamp the alert was triggered.",
        },
    },
    "pagespeed_tests": {
        "description": "Pagespeed checks configured in your StatusCake account.",
        "docs_url": "https://developers.statuscake.com/api/#tag/pagespeed",
        "columns": {
            "id": "Unique identifier for the pagespeed check.",
            "name": "Display name of the pagespeed check.",
            "website_url": "URL the check measures.",
            "location": "Monitoring location the check runs from.",
            "check_rate": "Number of seconds between checks.",
            "contact_groups": "List of contact group ids alerted by this check.",
            "paused": "Whether the check is paused.",
            "latest_stats": "Latest performance statistics for the check.",
        },
    },
    "pagespeed_history": {
        "description": "Historical pagespeed measurements (load time, page size, request count) for every pagespeed test.",
        "docs_url": "https://developers.statuscake.com/api/#tag/pagespeed/operation/list-pagespeed-test-history",
        "columns": {
            "test_id": _TEST_ID_COLUMN,
            "created_at": "Timestamp the measurement was recorded.",
            "loadtime_ms": "Page load time in milliseconds.",
            "filesize_kb": "Total page size in kilobytes.",
            "requests": "Number of requests made to load the page.",
        },
    },
    "ssl_tests": {
        "description": "SSL certificate checks configured in your StatusCake account, including current certificate details.",
        "docs_url": "https://developers.statuscake.com/api/#tag/ssl",
        "columns": {
            "id": "Unique identifier for the SSL check.",
            "website_url": "URL whose certificate is checked.",
            "check_rate": "Number of seconds between checks.",
            "contact_groups": "List of contact group ids alerted by this check.",
            "issuer_common_name": "Common name of the certificate issuer.",
            "certificate_score": "Certificate quality score.",
            "certificate_status": "Current status of the certificate.",
            "valid_from": "Timestamp the certificate became valid.",
            "valid_until": "Timestamp the certificate expires.",
            "paused": "Whether the check is paused.",
        },
    },
    "heartbeat_tests": {
        "description": "Heartbeat (push) checks configured in your StatusCake account.",
        "docs_url": "https://developers.statuscake.com/api/#tag/heartbeat",
        "columns": {
            "id": "Unique identifier for the heartbeat check.",
            "name": "Display name of the heartbeat check.",
            "period": "Number of seconds since the last ping before the check is considered down.",
            "contact_groups": "List of contact group ids alerted by this check.",
            "status": "Current status of the check (up or down).",
            "paused": "Whether the check is paused.",
        },
    },
    "contact_groups": {
        "description": "Contact groups that receive alerts from StatusCake checks.",
        "docs_url": "https://developers.statuscake.com/api/#tag/contact-groups",
        "columns": {
            "id": "Unique identifier for the contact group.",
            "name": "Display name of the contact group.",
            "email_addresses": "Email addresses alerted through this group.",
            "mobile_numbers": "Mobile numbers alerted through this group.",
            "integrations": "Third-party integration ids attached to this group.",
            "ping_url": "URL called when an alert fires for this group.",
        },
    },
    "maintenance_windows": {
        "description": "Maintenance windows during which uptime test alerts are suppressed.",
        "docs_url": "https://developers.statuscake.com/api/#tag/maintenance-windows",
        "columns": {
            "id": "Unique identifier for the maintenance window.",
            "name": "Display name of the maintenance window.",
            "start_at": "Timestamp the window starts.",
            "end_at": "Timestamp the window ends.",
            "repeat_interval": "How often the window repeats (never, daily, weekly, monthly).",
            "state": "Current state of the window (pending, active, paused).",
            "tests": "List of uptime test ids covered by the window.",
            "timezone": "Timezone the window's start and end times are expressed in.",
        },
    },
    "uptime_locations": {
        "description": "Monitoring locations available for uptime checks — a dimension for the location field on uptime history.",
        "docs_url": "https://developers.statuscake.com/api/#tag/locations",
        "columns": {
            "description": "Human-readable name of the monitoring location.",
            "region": "Geographic region of the location.",
            "region_code": "Short code for the region.",
            "status": "Operational status of the location.",
            "ipv4": "IPv4 address the location's checks originate from.",
            "ipv6": "IPv6 address the location's checks originate from.",
        },
    },
}
