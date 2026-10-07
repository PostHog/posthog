"""Signal emitter for datadog `error_logs` (record kind: issue).

The table holds one row per error log line, so the fetcher groups the new rows by (service,
normalized message) and the emitter produces one signal per group, at most once per week. The sync already filters to
`status:error` at the source.
"""

import hashlib
from typing import Any

from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher, week_period
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

DATADOG_ERROR_LOG_FIELDS = ("service", "message_pattern", "occurrences", "first_seen", "last_seen")

# Structured logs often leave `message` empty and put the text in Datadog's standard `error.message`
# or `error.kind` attributes. Without this fallback they all fall into one empty group that never emits.
_MESSAGE_TEXT_SQL = (
    "coalesce(nullIf(message, ''), "
    "nullIf(JSONExtractString(toString(attributes), 'error', 'message'), ''), "
    "nullIf(JSONExtractString(toString(attributes), 'error', 'kind'), ''), '')"
)
# Replacing UUIDs, hex strings and digit runs puts lines that differ only by an id into one group.
# The pattern is also the only message text that reaches the signal. Raw messages can hold personal
# data, so the signal never carries a sample line.
_UUID_REGEX = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_HEX_OR_NUMBER_REGEX = "[0-9a-fA-F]{8,}|[0-9]+"
MESSAGE_PATTERN_SQL = (
    f"substring(replaceRegexpAll(replaceRegexpAll({_MESSAGE_TEXT_SQL}, '{_UUID_REGEX}', '#'), "
    f"'{_HEX_OR_NUMBER_REGEX}', '#'), 1, 200)"
)
_SELECT_SQL = f"""
    service,
    {MESSAGE_PATTERN_SQL} AS message_pattern,
    count() AS occurrences,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
"""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def log_source_id(record: dict[str, Any]) -> str:
    # The week lets a fixed error that returns, or one that stays noisy, emit again.
    fingerprint = "|".join(
        (
            _text(record.get("service")),
            _text(record.get("message_pattern")),
            week_period(record.get("last_seen")),
        )
    )
    return "log:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


datadog_error_log_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="service, message_pattern",
    order_by_sql="occurrences DESC",
    source_id_for=log_source_id,
)


def datadog_error_log_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    service = _text(record.get("service"))
    message_pattern = _text(record.get("message_pattern"))
    if not message_pattern:
        return None
    occurrences = _text(record.get("occurrences"))
    first_seen = _text(record.get("first_seen"))
    last_seen = _text(record.get("last_seen"))
    summary = f"Error logs in {service}" if service else "Error logs"
    if occurrences:
        summary += f": {occurrences} occurrences"
    if first_seen and last_seen:
        summary += f" between {first_seen} and {last_seen}"
    extra: dict[str, Any] = {"kind": "error_log"}
    for field in ("service", "occurrences", "first_seen", "last_seen"):
        value = record.get(field)
        extra[field] = None if value is None else str(value)
    return SignalEmitterOutput(
        source_product="datadog",
        source_type="issue",
        source_id=log_source_id(record),
        description=f"{summary}\n{message_pattern}",
        weight=0.3,
        extra=extra,
    )


DATADOG_ERROR_LOGS_CONFIG = SignalSourceTableConfig(
    source_product="datadog",
    source_type="issue",
    emitter=datadog_error_log_emitter,
    record_fetcher=datadog_error_log_record_fetcher,
    record_processed_outputs=True,
    partition_field="timestamp",
    partition_field_is_datetime_string=True,
    fields=DATADOG_ERROR_LOG_FIELDS,
    max_records=50,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
