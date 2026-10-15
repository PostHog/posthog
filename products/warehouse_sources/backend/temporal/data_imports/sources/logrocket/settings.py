from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.logrocket.com/v1/"
AUDIT_DOCS_URL = "https://docs.logrocket.com/docs/audit-log-api"
EXPORT_DOCS_URL = "https://docs.logrocket.com/docs/data-export"


@frozen
class LogrocketEndpoint:
    path: str
    data_selector: str
    page_size: int
    primary_keys: tuple[str, ...] | None
    partition_key: str
    description: str
    should_sync_default: bool = True
    incremental_fields: tuple[IncrementalField, ...] = ()


# Timestamp filters stay disabled until their behavior is verified with a live LogRocket account.
ENDPOINTS: dict[str, LogrocketEndpoint] = {
    "audit_logs": LogrocketEndpoint(
        path="audit/logs/",
        data_selector="logs",
        page_size=10,
        # The documented audit rows have no unique identifier, so full refresh preserves duplicate actions.
        primary_keys=None,
        partition_key="created_date",
        description="Administrative actions and session access recorded in the LogRocket audit log.",
    ),
    "session_events": LogrocketEndpoint(
        path="data-export/",
        data_selector="sessions",
        page_size=100,
        primary_keys=("export_file_id", "export_line"),
        partition_key="event_time",
        description="Session metadata, user traits, navigation, clicks, errors, network events, and custom events from legacy exports.",
        should_sync_default=False,
    ),
}
