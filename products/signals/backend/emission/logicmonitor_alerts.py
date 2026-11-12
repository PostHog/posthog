"""Signal emitter for logicmonitor `alerts` (record kind: incident).

Each row is one alert on a monitored resource, so the alert id is the source id.
The sync rewrites the table each time, and the time cursor on `start_epoch` (Unix seconds) emits each alert once.
Cleared alerts are skipped.
The text names the datasource, the monitored object, the instance and the datapoint, because LogicMonitor alerts carry no title.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

LOGICMONITOR_ALERT_FIELDS = (
    "id",
    "severity",
    "acked",
    "monitor_object_name",
    "resource_template_name",
    "instance_name",
    "data_point_name",
    "start_epoch",
)

SEVERITY_LABELS = {"2": "warning", "3": "error", "4": "critical"}


def severity_label(raw: Any) -> str:
    severity = clean_text(raw)
    return SEVERITY_LABELS.get(severity, severity)


def logicmonitor_alert_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        alert_id = clean_text(record["id"])
        datasource = clean_text(record["resource_template_name"])
        monitored_object = clean_text(record["monitor_object_name"])
    except KeyError as e:
        msg = f"logicmonitor alert record missing required field {e}"
        logger.exception(msg, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not alert_id or not (datasource or monitored_object):
        logger.info(
            "Ignoring logicmonitor alert with empty id, datasource and monitored object",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    instance = clean_text(record.get("instance_name"))
    datapoint = clean_text(record.get("data_point_name"))
    severity = severity_label(record.get("severity"))
    headline = " alert on ".join(part for part in (datasource, monitored_object) if part)
    if datasource and not monitored_object:
        headline += " alert"
    details = [
        f"{label}: {value}"
        for label, value in (("Instance", instance), ("Datapoint", datapoint), ("Severity", severity))
        if value
    ]
    description = f"LogicMonitor alert: {headline}"
    if details:
        description += "\n" + ", ".join(details)
    return SignalEmitterOutput(
        source_product="logicmonitor",
        source_type="incident",
        source_id=alert_id,
        description=description,
        weight=1.0,
        extra={
            "severity": severity or None,
            "acked": None if record.get("acked") is None else str(record["acked"]),
            "monitor_object_name": monitored_object or None,
            "datasource": datasource or None,
            "instance_name": instance or None,
            "data_point_name": datapoint or None,
            "start_epoch": clean_text(record.get("start_epoch")) or None,
        },
    )


LOGICMONITOR_ALERTS_CONFIG = SignalSourceTableConfig(
    source_product="logicmonitor",
    source_type="incident",
    emitter=logicmonitor_alert_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(toInt(start_epoch))",
    fields=LOGICMONITOR_ALERT_FIELDS,
    where_clause="NOT ifNull(cleared, false)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
