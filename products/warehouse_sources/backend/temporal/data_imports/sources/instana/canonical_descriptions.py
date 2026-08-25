from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the official Instana OpenAPI specification
# (https://instana.github.io/openapi/). Keyed by endpoint name as returned by `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "events": {
        "description": "Incidents, issues, and changes detected by Instana across your monitored environment.",
        "docs_url": "https://instana.github.io/openapi/#operation/getEvents",
        "columns": {
            "eventId": "Unique identifier of the event.",
            "start": "Timestamp when the event started, in epoch milliseconds.",
            "end": "Timestamp when the event ended, in epoch milliseconds; unset while the event is still open.",
            "type": "Event type: INCIDENT, ISSUE, or CHANGE.",
            "state": "Current state of the event (e.g. OPEN or CLOSED).",
            "severity": "Numeric severity of the event (5 = warning, 10 = critical).",
            "problem": "Short description of the detected problem.",
            "detail": "Detailed description of the event.",
            "entityName": "Type of the entity the event was detected on (e.g. host, jvm).",
            "entityLabel": "Display label of the entity the event was detected on.",
            "entityType": "Category of the affected entity.",
            "snapshotId": "Identifier of the infrastructure snapshot the event relates to.",
            "eventSpecificationId": "Identifier of the event specification (rule) that triggered the event.",
            "fixSuggestion": "Suggested remediation for the detected problem.",
        },
    },
    "applications": {
        "description": "Application perspectives defined in Instana's application monitoring.",
        "docs_url": "https://instana.github.io/openapi/#operation/getApplications",
        "columns": {
            "id": "Unique identifier of the application perspective.",
            "label": "Display name of the application perspective.",
            "boundaryScope": "Which calls are part of the application: INBOUND or ALL.",
            "entityType": "Entity type of the record (application).",
        },
    },
    "services": {
        "description": "Services discovered by Instana's application monitoring.",
        "docs_url": "https://instana.github.io/openapi/#operation/getServices",
        "columns": {
            "id": "Unique identifier of the service.",
            "label": "Display name of the service.",
            "types": "Service types (e.g. HTTP, DATABASE, MESSAGING).",
            "technologies": "Technologies detected for the service.",
            "snapshotIds": "Infrastructure snapshot identifiers backing the service.",
            "entityType": "Entity type of the record (service).",
        },
    },
    "endpoints": {
        "description": "Service endpoints (HTTP paths, RPC methods, queues) discovered by Instana.",
        "docs_url": "https://instana.github.io/openapi/#operation/getApplicationEndpoints",
        "columns": {
            "id": "Unique identifier of the endpoint.",
            "label": "Display name of the endpoint.",
            "serviceId": "Identifier of the service the endpoint belongs to.",
            "type": "Endpoint type (e.g. HTTP, DATABASE, MESSAGING).",
            "technologies": "Technologies detected for the endpoint.",
            "synthetic": "Whether the endpoint only receives synthetic traffic.",
        },
    },
    "websites": {
        "description": "Websites configured for Instana end-user (website) monitoring.",
        "docs_url": "https://instana.github.io/openapi/#operation/getWebsites",
        "columns": {
            "id": "Unique identifier of the website configuration.",
            "name": "Name of the monitored website.",
            "appName": "Application name associated with the website.",
        },
    },
    "synthetic_tests": {
        "description": "Synthetic monitoring tests configured in Instana.",
        "docs_url": "https://instana.github.io/openapi/#operation/getSyntheticTests",
        "columns": {
            "id": "Unique identifier of the synthetic test.",
            "label": "Display name of the synthetic test.",
            "active": "Whether the test is currently active.",
            "testFrequency": "How often the test runs, in minutes.",
            "locations": "Identifiers of the locations the test runs from.",
            "createdAt": "Timestamp when the test was created, in epoch milliseconds.",
            "modifiedAt": "Timestamp when the test was last modified, in epoch milliseconds.",
        },
    },
    "alerting_channels": {
        "description": "Alert channels (integrations) configured in Instana's alerting settings.",
        "docs_url": "https://instana.github.io/openapi/#operation/getAlertingChannels",
        "columns": {
            "id": "Unique identifier of the alert channel.",
            "name": "Display name of the alert channel.",
            "kind": "Channel type (e.g. EMAIL, SLACK, WEB_HOOK, OPS_GENIE).",
        },
    },
    "alert_configs": {
        "description": "Alerting configurations that route triggered events to alert channels.",
        "docs_url": "https://instana.github.io/openapi/#operation/getAlerts",
        "columns": {
            "id": "Unique identifier of the alerting configuration.",
            "alertName": "Display name of the alerting configuration.",
            "integrationIds": "Identifiers of the alert channels this configuration notifies.",
            "eventFilteringConfiguration": "Rules selecting which events trigger this alert.",
            "muteUntil": "Timestamp the alert is muted until, in epoch milliseconds.",
            "lastUpdated": "Timestamp of the last modification, in epoch milliseconds.",
        },
    },
    "infrastructure_snapshots": {
        "description": "Snapshot summaries of infrastructure entities currently monitored by Instana agents.",
        "docs_url": "https://instana.github.io/openapi/#operation/getSnapshots",
        "columns": {
            "snapshotId": "Unique identifier of the infrastructure snapshot.",
            "plugin": "Entity type (plugin) that produced the snapshot (e.g. host, jvmRuntimePlatform).",
            "label": "Display label of the monitored entity.",
            "host": "Identifier of the host the entity runs on.",
            "tags": "Tags attached to the monitored entity.",
        },
    },
}
