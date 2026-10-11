from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Apps": {
        "description": "Apps and their environments configured in your Apitally team.",
        "docs_url": "https://docs.apitally.io/api-reference/apps/list-apps",
        "columns": {
            "id": "Unique identifier for the app.",
            "name": "Name of the app.",
            "framework": "Web framework the app's Apitally SDK is integrated with.",
            "client_id": "Client identifier used by the Apitally SDK to report data for this app.",
            "envs": "Environments configured for this app (e.g. production, staging), each with its own sync status.",
            "created_at": "Timestamp when the app was first created.",
        },
    },
    "Consumers": {
        "description": "API consumers (identified callers) that have made requests to an app.",
        "docs_url": "https://docs.apitally.io/api-reference/consumers/list-consumers",
        "columns": {
            "id": "Unique identifier for the consumer.",
            "identifier": "Consumer identifier as reported by the Apitally SDK.",
            "name": "Display name of the consumer.",
            "group": "Consumer group this consumer belongs to, if any.",
            "created_at": "Timestamp of the consumer's first recorded request.",
            "last_request_at": "Timestamp of the consumer's most recent recorded request.",
        },
    },
    "Endpoints": {
        "description": "API endpoints (method + path) detected for an app.",
        "docs_url": "https://docs.apitally.io/api-reference/endpoints/list-endpoints",
        "columns": {
            "id": "Unique identifier for the endpoint.",
            "method": "HTTP method of the endpoint (e.g. GET, POST).",
            "path": "Path pattern of the endpoint (e.g. /v1/users/{user_id}).",
        },
    },
    "Traffic": {
        "description": "Hourly API traffic metrics for an app: request counts and payload sizes over time.",
        "docs_url": "https://docs.apitally.io/api-reference/metrics/get-traffic",
        "columns": {
            "period_start": "Start of the aggregation period.",
            "period_end": "End of the aggregation period.",
            "requests": "Number of requests received during the period.",
            "bytes_received": "Total request payload bytes received during the period.",
            "bytes_sent": "Total response payload bytes sent during the period.",
        },
    },
    "RequestLogs": {
        "description": "Individual API request log entries for an app, including status code, timing, and consumer.",
        "docs_url": "https://docs.apitally.io/api-reference/request-logs/get-request-logs",
        "columns": {
            "timestamp": "Timestamp when the request was received.",
            "request_uuid": "Unique identifier for the request.",
            "env": "Environment the request was made against (e.g. production, staging).",
            "consumer": "Identifier of the consumer that made the request, if known.",
            "method": "HTTP method of the request.",
            "path": "Path pattern the request matched, if recognized.",
            "url": "Full URL of the request.",
            "status_code": "HTTP status code of the response.",
            "request_size_bytes": "Size of the request payload in bytes.",
            "response_size_bytes": "Size of the response payload in bytes.",
            "response_time_ms": "Time taken to respond, in milliseconds.",
            "client_ip": "IP address of the client that made the request.",
            "client_country_iso_code": "ISO country code derived from the client IP address.",
        },
    },
}
