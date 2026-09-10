from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "search_logs": {
        "description": "Individual log documents returned by the Logz.io search API, one row per Elasticsearch document. Bounded by the account's log retention window.",
        "docs_url": "https://api-docs.logz.io/docs/logz/search",
        "columns": {
            "_id": "Elasticsearch document id, unique across the account's indices.",
            "_index": "Elasticsearch index the document was read from (typically time-based).",
            "@timestamp": "Timestamp of the log event, in UTC.",
            "message": "The log message body.",
            "type": "Log type assigned at shipping time.",
        },
    },
    "alerts": {
        "description": "Alert definitions configured in the account.",
        "docs_url": "https://api-docs.logz.io/docs/logz/get-all-alerts",
        "columns": {
            "id": "Unique identifier for the alert definition.",
            "title": "Human-readable alert title.",
            "enabled": "Whether the alert is currently active.",
            "createdAt": "When the alert was created.",
            "updatedAt": "When the alert was last modified.",
        },
    },
    "triggered_alerts": {
        "description": "History of alert firings — one row per triggered alert event.",
        "docs_url": "https://api-docs.logz.io/docs/logz/search-triggered-alerts",
        "columns": {
            "alertEventId": "Unique identifier for the triggered alert event.",
            "name": "Name of the alert that fired.",
            "severity": "Severity assigned to the firing.",
            "date": "When the alert fired.",
        },
    },
    "notification_endpoints": {
        "description": "Notification endpoints (Slack, PagerDuty, webhooks, etc.) available to route alerts to.",
        "docs_url": "https://api-docs.logz.io/docs/logz/get-all-endpoints",
        "columns": {
            "id": "Unique identifier for the notification endpoint.",
            "title": "Human-readable endpoint title.",
            "type": "Endpoint type (e.g. slack, pagerduty, custom).",
        },
    },
    "drop_filters": {
        "description": "Drop filters configured to discard matching logs before indexing.",
        "docs_url": "https://api-docs.logz.io/docs/logz/get-all-drop-filters",
        "columns": {
            "id": "Unique identifier for the drop filter.",
            "active": "Whether the drop filter is currently applied.",
        },
    },
}
