"""Signal emitter for cronitor `issues` (record kind: incident).

`state` is unresolved, investigating, identified, monitoring or resolved; `started` is an ISO string.
Maintenance issues are not failures, so the filter drops them.
`updates` is nested JSON; the newest update message is the useful text.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._incident_text import latest_text, str_or_none
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

CRONITOR_FIELDS = (
    "key",
    "name",
    "severity",
    "state",
    "updates",
    "created",
    "started",
)


def cronitor_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        key = record["key"]
        name = record["name"]
    except KeyError as e:
        msg = f"cronitor record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not key or not name:
        logger.info(
            "Ignoring cronitor record with empty key or name", team_id=team_id, signals_type="data-import-signals"
        )
        return None
    update = latest_text(
        parse_json_list(record.get("updates")),
        text_keys=("message", "body", "text", "content", "description"),
        time_keys=("created", "created_at", "stamp", "timestamp", "started"),
    )
    return SignalEmitterOutput(
        source_product="cronitor",
        source_type="incident",
        source_id=str(key),
        description=f"{name}\n{update}" if update else str(name),
        weight=1.0,
        extra={
            "severity": str_or_none(record.get("severity")),
            "state": str_or_none(record.get("state")),
            "created": str_or_none(record.get("created")),
            "started": str_or_none(record.get("started")),
        },
    )


CRONITOR_CONFIG = SignalSourceTableConfig(
    source_product="cronitor",
    source_type="incident",
    emitter=cronitor_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="started",
    partition_field_is_datetime_string=True,
    fields=CRONITOR_FIELDS,
    where_clause="state != 'resolved' AND coalesce(severity, '') != 'maintenance'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
