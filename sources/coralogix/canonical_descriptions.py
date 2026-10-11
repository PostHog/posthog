from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "logs": {
        "description": "Raw log records returned by the DataPrime query API (`source logs`), one row per log entry.",
        "docs_url": "https://coralogix.com/docs/dataprime/API/direct-archive-query-http/",
        "columns": {
            "logid": "Unique identifier Coralogix assigns to the log entry.",
            "timestamp": "Event time of the log entry, in UTC.",
            "severity": "Log severity level (e.g. Debug, Info, Warning, Error, Critical).",
            "priorityclass": "Priority class assigned to the log by Coralogix's TCO pipeline (high, medium, low).",
            "applicationname": "Application the log was ingested under.",
            "subsystemname": "Subsystem the log was ingested under.",
            "user_data": "The raw log body as a JSON-encoded string.",
        },
    },
    "spans": {
        "description": "Raw trace spans returned by the DataPrime query API (`source spans`), one row per span.",
        "docs_url": "https://coralogix.com/docs/dataprime/API/direct-archive-query-http/",
        "columns": {
            "timestamp": "Start time of the span, in UTC.",
            "applicationname": "Application the span was ingested under.",
            "subsystemname": "Subsystem the span was ingested under.",
            "user_data": "The raw span (attributes, IDs, duration) as a JSON-encoded string.",
        },
    },
}
