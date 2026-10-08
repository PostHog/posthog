from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    name: {
        "description": description,
        "docs_url": "https://embrace.io/docs/metrics-forwarding/",
        "columns": {
            "series_id": "Stable hash of all metric labels, including the metric name.",
            "timestamp": "UTC timestamp of the hourly metric sample.",
            "value": "Metric value for this hour and label combination. Non-finite values are null.",
            "labels": "Metric labels, including app ID, app version, OS version, and device model.",
        },
    }
    for name, description in {
        "sessions": "Hourly counts of session parts. Embrace metric names use sessions to mean session parts.",
        "crashes": "Hourly crash counts for Android and iOS apps.",
        "network_4xx": "Hourly counts of network errors with HTTP status codes in the 400 range.",
        "network_5xx": "Hourly counts of network errors with HTTP status codes in the 500 range.",
    }.items()
}
