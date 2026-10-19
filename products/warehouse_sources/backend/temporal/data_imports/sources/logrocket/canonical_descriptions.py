from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.logrocket.settings import (
    AUDIT_DOCS_URL,
    ENDPOINTS,
    EXPORT_DOCS_URL,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "audit_logs": {
        "description": ENDPOINTS["audit_logs"].description,
        "docs_url": AUDIT_DOCS_URL,
        "columns": {
            "created_date": "UTC timestamp when the audit action occurred.",
            "time": "Display time for the audit action.",
            "user": "Email address or system identifier of the user who performed the action.",
            "action": "Name of the action performed.",
            "description": "Action details or the identifier of a viewed session.",
        },
    },
    "session_events": {
        "description": ENDPOINTS["session_events"].description,
        "docs_url": EXPORT_DOCS_URL,
        "columns": {
            "type": "LogRocket event type, including metadata, identification, navigation, and network events.",
            "seqID": "Event sequence number from the session export.",
            "tabID": "Identifier of the browser tab that recorded the event.",
            "time": "Event timestamp in Unix milliseconds.",
            "data": "Event details, including user traits or custom properties when present.",
            "event_time": "UTC event timestamp converted from time for table partitioning.",
            "export_file_id": "Stable hash of the export file host and path, excluding temporary URL credentials.",
            "export_line": "One-based line number within the export file.",
        },
    },
}
