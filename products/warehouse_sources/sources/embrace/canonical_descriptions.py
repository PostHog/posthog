from products.warehouse_sources.sources.sdk import CanonicalDescriptions

DEVICE_LABELS = "Metric labels, including app ID, app version, OS version, and device model."
WEB_VITAL_LABELS = "Metric labels, including app ID, Web Vital name, and rating."
PERIOD_ADJECTIVES = {"hour": "hourly", "day": "daily"}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    name: {
        "description": description,
        "docs_url": "https://embrace.io/docs/metrics-forwarding/",
        "columns": {
            "series_id": "Stable hash of all metric labels, including the metric name.",
            "timestamp": f"UTC timestamp of the {PERIOD_ADJECTIVES[period]} metric sample.",
            "value": f"Metric value for this {period} and label combination. Non-finite values are null.",
            "labels": labels,
        },
    }
    for name, (description, period, labels) in {
        "sessions": (
            "Hourly counts of session parts. Embrace metric names use sessions to mean session parts.",
            "hour",
            DEVICE_LABELS,
        ),
        "crashes": ("Hourly crash counts for Android and iOS apps.", "hour", DEVICE_LABELS),
        "network_4xx": (
            "Hourly counts of network errors with HTTP status codes in the 400 range.",
            "hour",
            DEVICE_LABELS,
        ),
        "network_5xx": (
            "Hourly counts of network errors with HTTP status codes in the 500 range.",
            "hour",
            DEVICE_LABELS,
        ),
        "daily_users": (
            "Daily counts of unique users. Each value counts distinct devices within one UTC day, so summing days double-counts users.",
            "day",
            DEVICE_LABELS,
        ),
        "crash_free_users": (
            "Hourly counts of unique users without crashes for Android and iOS apps.",
            "hour",
            DEVICE_LABELS,
        ),
        "exceptions": ("Hourly exception counts for web apps.", "hour", "Metric labels, including app ID."),
        "web_vitals": ("Hourly counts of Web Vital measurements for web apps.", "hour", WEB_VITAL_LABELS),
        "web_vital_p75": (
            "Hourly 75th percentile values of each Web Vital for web apps. Units differ by Web Vital name.",
            "hour",
            WEB_VITAL_LABELS,
        ),
    }.items()
}
