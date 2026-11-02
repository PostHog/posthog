from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

DOCS_URL = "https://learn.microsoft.com/en-us/azure/azure-monitor/app/data-model-complete"
COMMON_COLUMNS = {
    "timestamp": "Time when the telemetry item was recorded.",
    "itemId": "Unique identifier for the telemetry item.",
    "itemCount": "Number of occurrences represented by the telemetry item.",
    "operation_Id": "Identifier for the root operation that groups related telemetry.",
    "cloud_RoleName": "Name of the application role that produced the telemetry.",
}
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "requests": {
        "description": "Incoming application requests, with their duration and result.",
        "docs_url": DOCS_URL,
        "columns": {
            **COMMON_COLUMNS,
            "name": "Name of the request.",
            "duration": "Request duration in milliseconds.",
            "success": "Whether the request succeeded.",
            "resultCode": "Response code returned by the application.",
        },
    },
    "dependencies": {
        "description": "Calls to external services or storage, with their duration and result.",
        "docs_url": DOCS_URL,
        "columns": {
            **COMMON_COLUMNS,
            "target": "Target of the dependency call.",
            "duration": "Dependency call duration in milliseconds.",
            "success": "Whether the dependency call succeeded.",
        },
    },
    "exceptions": {
        "description": "Application exceptions and their diagnostic details.",
        "docs_url": DOCS_URL,
        "columns": {
            **COMMON_COLUMNS,
            "problemId": "Identifier that groups exceptions from the same problem.",
            "type": "Type of exception.",
            "outerMessage": "Message from the outer exception.",
        },
    },
    "availabilityResults": {
        "description": "Availability test results that measure application responsiveness and uptime.",
        "docs_url": DOCS_URL,
        "columns": {
            **COMMON_COLUMNS,
            "name": "Name of the availability test.",
            "location": "Location where the test ran.",
            "success": "Whether the availability test succeeded.",
            "duration": "Availability test duration in milliseconds.",
        },
    },
}
