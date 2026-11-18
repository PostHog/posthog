"""Signal emitter for lacework `alerts` (record kind: scanner_finding).

The alert text lives in the nested `alert_info` JSON (`subject`, `description`), so the query extracts
it into aliased columns. `status` is Open or Closed; `start_time` is an ISO string.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._prompts import SCANNER_ACTIONABILITY_PROMPT, SCANNER_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

LACEWORK_FIELDS = (
    "alert_id",
    "alert_name",
    "alert_type",
    "JSONExtractString(toString(alert_info), 'subject') AS alert_subject",
    "JSONExtractString(toString(alert_info), 'description') AS alert_description",
    "severity",
    "status",
    "start_time",
    "internet_exposure",
)

LACEWORK_EXTRA_FIELDS = ("alert_type", "severity", "status", "internet_exposure", "start_time")


def lacework_alert_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        alert_id = record["alert_id"]
    except KeyError as e:
        msg = f"lacework record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    title = record.get("alert_name") or record.get("alert_type")
    if not alert_id or not title:
        logger.info(
            "Ignoring lacework record with empty id or title", team_id=team_id, signals_type="data-import-signals"
        )
        return None
    parts = [str(title)]
    for key in ("alert_subject", "alert_description"):
        text = record.get(key)
        if text and str(text) not in parts:
            parts.append(str(text))
    return SignalEmitterOutput(
        source_product="lacework",
        source_type="scanner_finding",
        source_id=str(alert_id),
        description="\n".join(parts),
        weight=1.0,
        extra=build_extra(record, LACEWORK_EXTRA_FIELDS, ()),
    )


LACEWORK_CONFIG = SignalSourceTableConfig(
    source_product="lacework",
    source_type="scanner_finding",
    emitter=lacework_alert_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="start_time",
    partition_field_is_datetime_string=True,
    fields=LACEWORK_FIELDS,
    where_clause="lower(ifNull(status, '')) != 'closed'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=SCANNER_ACTIONABILITY_PROMPT,
    summarization_prompt=SCANNER_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
