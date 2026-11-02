from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class ThousandeyesEndpoint:
    path: str
    selector: str
    primary_keys: tuple[str, ...]
    alert_state: str | None = None


ENDPOINTS = {
    "tests": ThousandeyesEndpoint(path="tests", selector="tests", primary_keys=("testId",)),
    "agents": ThousandeyesEndpoint(path="agents", selector="agents", primary_keys=("agentId",)),
    "alert_rules": ThousandeyesEndpoint(path="alerts/rules", selector="alertRules", primary_keys=("ruleId",)),
    "active_alerts": ThousandeyesEndpoint(
        path="alerts", selector="alerts", primary_keys=("id",), alert_state="trigger"
    ),
    "cleared_alerts": ThousandeyesEndpoint(path="alerts", selector="alerts", primary_keys=("id",), alert_state="clear"),
    "http_server_results": ThousandeyesEndpoint(
        path="test-results/{testId}/http-server", selector="results", primary_keys=("testId", "agentId", "roundId")
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "http_server_results": [
        IncrementalField(
            label="date",
            type=IncrementalFieldType.DateTime,
            field="date",
            field_type=IncrementalFieldType.DateTime,
        )
    ]
}
HISTORY_DAYS = 30
