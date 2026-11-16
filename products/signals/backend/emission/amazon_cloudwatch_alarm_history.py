"""Signal emitter for amazon_cloudwatch `alarm_history` (record kind: incident).

The table holds one row per alarm history item: state transitions, configuration updates and action executions.
Only `StateUpdate` rows whose new state is `ALARM` are read.
The fetcher groups those rows of a trailing window by alarm, and the emitter produces one signal per alarm, at most once per ISO week, so a flapping alarm does not flood the inbox.
The emission ledger and the weekly fingerprint keep re-reading the same rows safe.
`history_data` is the JSON CloudWatch records for the change; the state reason of the newest transition is its text.
"""

import hashlib
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher, week_period
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

AMAZON_CLOUDWATCH_ALARM_FIELDS = (
    "alarm_name",
    "alarm_kind",
    "state_reason",
    "transitions",
    "first_seen",
    "last_seen",
)

_EXTRA_FIELDS = ("alarm_kind", "transitions", "first_seen", "last_seen")
_MAX_REASON_CHARS = 1000
_HISTORY_DATA = "toString(history_data)"

_SELECT_SQL = f"""
    alarm_name,
    any(alarm_type) AS alarm_kind,
    argMax(JSONExtractString({_HISTORY_DATA}, 'newState', 'stateReason'), timestamp) AS state_reason,
    count() AS transitions,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
"""


def alarm_source_id(record: dict[str, Any]) -> str:
    # The week lets an alarm that keeps firing, or fires again after a fix, emit again.
    fingerprint = "|".join((clean_text(record.get("alarm_name")), week_period(record.get("last_seen"))))
    return "alarm:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


amazon_cloudwatch_alarm_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="alarm_name",
    order_by_sql="transitions DESC",
    source_id_for=alarm_source_id,
)


def amazon_cloudwatch_alarm_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    alarm_name = clean_text(record.get("alarm_name"))
    if not alarm_name:
        logger.info(
            "Ignoring amazon_cloudwatch alarm group without an alarm name",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    transitions = clean_text(record.get("transitions"))
    first_seen = clean_text(record.get("first_seen"))
    last_seen = clean_text(record.get("last_seen"))
    reason = clean_text(record.get("state_reason"))[:_MAX_REASON_CHARS]
    summary = f"CloudWatch alarm {alarm_name} entered the ALARM state"
    if transitions:
        summary += f" {transitions} times"
    if first_seen and last_seen:
        summary += f" between {first_seen} and {last_seen}"
    lines = [summary]
    if reason:
        lines.append(reason)
    return SignalEmitterOutput(
        source_product="amazon_cloudwatch",
        source_type="incident",
        source_id=alarm_source_id(record),
        description="\n".join(lines),
        # Below the report threshold of 1.0, so one alarm alone cannot open a report.
        weight=0.5,
        extra={"alarm_name": alarm_name, **build_extra(record, _EXTRA_FIELDS, ())},
    )


AMAZON_CLOUDWATCH_ALARM_HISTORY_CONFIG = SignalSourceTableConfig(
    source_product="amazon_cloudwatch",
    source_type="incident",
    emitter=amazon_cloudwatch_alarm_emitter,
    record_fetcher=amazon_cloudwatch_alarm_record_fetcher,
    # Each group is emitted once through the ledger, because every sync window can contain it again.
    record_processed_outputs=True,
    partition_field="toString(timestamp)",
    partition_field_is_datetime_string=True,
    fields=AMAZON_CLOUDWATCH_ALARM_FIELDS,
    where_clause=(
        f"history_item_type = 'StateUpdate' AND JSONExtractString({_HISTORY_DATA}, 'newState', 'stateValue') = 'ALARM'"
    ),
    max_records=50,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
