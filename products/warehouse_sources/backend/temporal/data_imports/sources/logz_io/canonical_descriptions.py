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
    "security_events": {
        "description": "Cloud SIEM security events, one row per time a security rule's conditions were met. Muted events are included.",
        "docs_url": "https://api-docs.logz.io/docs/logz/search-security-rules-events",
        "columns": {
            "alertEventId": "Unique identifier of the security event.",
            "alertId": "Identifier of the security rule that triggered the event. Joins to security_rules.id.",
            "name": "Name of the security rule.",
            "description": "Explanation of the rule's logic and suggested next steps.",
            "alertSummary": "The rule's trigger condition.",
            "eventDate": "When the event triggered, as a Unix timestamp in seconds.",
            "alertWindowStartDate": "Unix timestamp in seconds of the earliest log that triggered the rule.",
            "alertWindowEndDate": "Unix timestamp in seconds of the latest log that triggered the rule.",
            "severity": "Severity of the event: INFO, LOW, MEDIUM, HIGH or SEVERE.",
            "groupBy": "Field-value pairs the rule used to aggregate the triggering logs.",
            "hits": "Number of logs that triggered the rule before aggregation.",
            "isMuted": "Whether the event is muted.",
            "mitreTags": "MITRE tags that classify the event.",
        },
    },
    "security_rules": {
        "description": "Cloud SIEM security rule definitions.",
        "docs_url": "https://api-docs.logz.io/docs/logz/search-account-security-rules",
        "columns": {
            "id": "Unique identifier of the security rule.",
            "title": "Rule title.",
            "description": "Description of the event the rule detects and suggested next steps.",
            "enabled": "Whether the rule is active.",
            "createdAt": "When the rule was created, in UTC.",
            "createdBy": "Email of the user who created the rule.",
            "updatedAt": "When the rule was last updated, in UTC.",
            "updatedBy": "Email of the user who last updated the rule.",
            "tags": "Tags used to organize the rule.",
        },
    },
    "audit_trail": {
        "description": "Account audit trail, one row per recorded change or action by a user or API token.",
        "docs_url": "https://api-docs.logz.io/docs/logz/list-account-audit-trails-filtered",
        "columns": {
            "audit_event_id": "Hash of the audit event's content. The API returns no event id, so PostHog derives one.",
            "auditEventUser": "The user or API token that performed the action.",
            "date": "When the event happened, as a Unix timestamp.",
            "auditEventTypeTitle": "Type of the audit event.",
            "ip": "IP address of the client that made the request.",
            "geoLocation": "Geographic location of the client that made the request.",
            "extraDataList": "Fields the event changed, with their old and new values.",
        },
    },
    "users": {
        "description": "Users of the Logz.io account that owns the API token.",
        "docs_url": "https://api-docs.logz.io/docs/logz/list-users",
        "columns": {
            "id": "Unique identifier of the user.",
            "username": "Email address the user signs in with.",
            "fullName": "First and last name of the user.",
            "accountID": "Logz.io account ID the user belongs to.",
            "role": "User role: USER_ROLE_READONLY, USER_ROLE_REGULAR or USER_ROLE_ACCOUNT_ADMIN.",
            "active": "Whether the user is active. False when the user is suspended.",
        },
    },
}
