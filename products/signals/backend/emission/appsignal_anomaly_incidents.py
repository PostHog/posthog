"""Signal emitter for appsignal `anomaly_incidents` (record kind: issue).

Each row is an alert trigger on a metric that fired.
`created_at` never changes, so the time cursor emits each incident once. `state` is OPEN, WIP or CLOSED.
AppSignal uses the record kind `issue` for every table, so the existing AppSignal inbox toggle covers this table too.
The text comes from the nested `trigger` object and the metric `tags`.
The incident `description` is not read, because people write it.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._incident_text import parse_json_object
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

APPSIGNAL_ANOMALY_FIELDS = (
    "id",
    "trigger",
    "tags",
    "alert_state",
    "state",
    "severity",
    "count AS occurrence_count",
    "created_at",
    "last_occurred_at",
)

_MAX_TAGS = 10
_MAX_TRIGGER_DESCRIPTION_CHARS = 1000


def _trigger_value(trigger: dict[str, Any], *keys: str) -> str:
    # Nested keys keep the API's camelCase, but accept the snake_case form too.
    for key in keys:
        value = clean_text(trigger.get(key))
        if value:
            return value
    return ""


def metric_tags(raw: Any) -> list[str]:
    tags: list[str] = []
    for item in parse_json_list(raw):
        if not isinstance(item, dict):
            continue
        key = clean_text(item.get("key"))
        value = clean_text(item.get("value"))
        if key and value:
            tags.append(f"{key}={value}")
    return tags[:_MAX_TAGS]


def appsignal_anomaly_incident_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    incident_id = clean_text(record.get("id"))
    trigger = parse_json_object(record.get("trigger"))
    trigger_name = _trigger_value(trigger, "name")
    metric_name = _trigger_value(trigger, "metricName", "metric_name")
    if not incident_id or not (trigger_name or metric_name):
        logger.info(
            "Ignoring appsignal anomaly incident with empty id or trigger",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    field = _trigger_value(trigger, "field")
    lines = [f"AppSignal anomaly alert: {trigger_name or metric_name}"]
    if metric_name:
        lines.append(f"Metric: {metric_name}" + (f" ({field.lower()})" if field else ""))
    tags = metric_tags(record.get("tags"))
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")
    trigger_description = _trigger_value(trigger, "description")[:_MAX_TRIGGER_DESCRIPTION_CHARS]
    if trigger_description:
        lines.append(trigger_description)
    return SignalEmitterOutput(
        source_product="appsignal",
        source_type="issue",
        source_id=f"anomaly_incident:{incident_id}",
        description="\n".join(lines),
        weight=1.0,
        extra={
            "kind": "anomaly_incident",
            "state": clean_text(record.get("state")) or None,
            "severity": clean_text(record.get("severity")) or None,
            "namespace": None,
            "occurrence_count": clean_text(record.get("occurrence_count")) or None,
            "created_at": clean_text(record.get("created_at")) or None,
            "last_occurred_at": clean_text(record.get("last_occurred_at")) or None,
            "alert_state": clean_text(record.get("alert_state")) or None,
            "metric_name": metric_name or None,
        },
    )


APPSIGNAL_ANOMALY_CONFIG = SignalSourceTableConfig(
    source_product="appsignal",
    source_type="issue",
    emitter=appsignal_anomaly_incident_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="toString(created_at)",
    partition_field_is_datetime_string=True,
    fields=APPSIGNAL_ANOMALY_FIELDS,
    where_clause="state != 'CLOSED'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
