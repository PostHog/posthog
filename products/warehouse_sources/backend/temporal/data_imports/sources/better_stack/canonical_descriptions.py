from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://betterstack.com/docs/uptime/api/getting-started-with-uptime-api/"

# Descriptions are sourced from Better Stack's public Uptime API reference. Partial coverage is
# fine — any endpoint, column, or table-level description not listed here falls back to LLM
# enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "incidents": {
        "description": "Downtime and alert incidents recorded by Better Stack, with their cause, acknowledgement, and resolution timeline.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the incident.",
            "name": "Name of the monitor or heartbeat the incident belongs to.",
            "url": "URL of the checked resource the incident relates to.",
            "cause": "What caused the incident (e.g. a status code, timeout, or missed heartbeat).",
            "started_at": "When the incident started.",
            "acknowledged_at": "When the incident was acknowledged.",
            "acknowledged_by": "Who acknowledged the incident.",
            "resolved_at": "When the incident was resolved.",
            "resolved_by": "Who or what resolved the incident.",
            "response_content": "Response content captured when the incident was detected.",
        },
    },
    "monitors": {
        "description": "Uptime monitors configured in Better Stack, with their check settings and current status.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the monitor.",
            "url": "URL or host the monitor checks.",
            "pronounceable_name": "Human-readable name of the monitor.",
            "monitor_type": "Type of check the monitor performs (e.g. status, keyword, ping, tcp).",
            "monitor_group_id": "Identifier of the monitor group this monitor belongs to.",
            "status": "Current status of the monitor (e.g. up, down, paused, validating).",
            "check_frequency": "How often the monitor runs, in seconds.",
            "last_checked_at": "When the monitor was last checked.",
            "paused_at": "When the monitor was paused, if it is paused.",
            "created_at": "When the monitor was created.",
            "updated_at": "When the monitor was last updated.",
        },
    },
    "monitor_groups": {
        "description": "Groups used to organize uptime monitors.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the monitor group.",
            "name": "Name of the monitor group.",
            "sort_index": "Position of the group when sorting groups.",
            "created_at": "When the group was created.",
            "updated_at": "When the group was last updated.",
        },
    },
    "heartbeats": {
        "description": "Heartbeat (cron/background job) checks configured in Better Stack.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the heartbeat.",
            "name": "Name of the heartbeat.",
            "url": "URL the monitored service pings to report the heartbeat.",
            "period": "Expected interval between heartbeats, in seconds.",
            "grace": "Additional grace period before an incident is raised, in seconds.",
            "heartbeat_group_id": "Identifier of the heartbeat group this heartbeat belongs to.",
            "status": "Current status of the heartbeat.",
            "paused_at": "When the heartbeat was paused, if it is paused.",
            "created_at": "When the heartbeat was created.",
            "updated_at": "When the heartbeat was last updated.",
        },
    },
    "heartbeat_groups": {
        "description": "Groups used to organize heartbeat checks.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the heartbeat group.",
            "name": "Name of the heartbeat group.",
            "sort_index": "Position of the group when sorting groups.",
            "created_at": "When the group was created.",
            "updated_at": "When the group was last updated.",
        },
    },
    "status_pages": {
        "description": "Public status pages hosted on Better Stack.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the status page.",
            "company_name": "Company name shown on the status page.",
            "company_url": "Company website linked from the status page.",
            "subdomain": "Better Stack subdomain the status page is served on.",
            "custom_domain": "Custom domain the status page is served on, if configured.",
            "timezone": "Timezone used to display times on the status page.",
            "history": "Number of days of incident history shown on the status page.",
            "created_at": "When the status page was created.",
            "updated_at": "When the status page was last updated.",
        },
    },
    "on_calls": {
        "description": "On-call calendars defining who is on call and when.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the on-call calendar.",
            "name": "Name of the on-call calendar.",
        },
    },
    "escalation_policies": {
        "description": "Escalation policies describing how incidents are escalated to team members.",
        "docs_url": _DOCS,
        "columns": {
            "id": "Unique identifier for the escalation policy.",
            "name": "Name of the escalation policy.",
            "repeat_count": "How many times the escalation steps are repeated.",
            "repeat_delay": "Delay between escalation repeats, in seconds.",
        },
    },
}
