"""Signal emitter for datadog `error_spans` (record kind: issue).

The table holds one row per failed span, so the fetcher groups the new rows by (service, resource,
error type) and the emitter produces one signal per group, at most once per week. The sync already filters to `status:error` at the
source, which keeps the table to errors only.
"""

import hashlib
from typing import Any

from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher, week_period
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

DATADOG_ERROR_SPAN_FIELDS = (
    "service",
    "resource_name",
    "occurrences",
    "first_seen",
    "last_seen",
    "error_type",
)

# Spans keep the error under `error`. A column shape that differs from this makes the extraction
# return an empty string, so the group still emits without an error type. Error messages can hold
# personal data, so only the error type reaches the signal, as with error logs.
_SELECT_SQL = """
    service,
    resource_name,
    ifNull(JSONExtractString(toString(error), 'type'), '') AS error_type,
    count() AS occurrences,
    min(start_timestamp) AS first_seen,
    max(start_timestamp) AS last_seen
"""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def span_source_id(record: dict[str, Any]) -> str:
    # The error type separates two different failures of one resource, and the week lets a fixed error
    # that returns, or one that stays noisy, emit again.
    fingerprint = "|".join(
        (
            _text(record.get("service")),
            _text(record.get("resource_name")),
            _text(record.get("error_type")),
            week_period(record.get("last_seen")),
        )
    )
    return "span:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


datadog_error_span_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="service, resource_name, error_type",
    order_by_sql="occurrences DESC",
    source_id_for=span_source_id,
)


def datadog_error_span_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    service = _text(record.get("service"))
    resource_name = _text(record.get("resource_name"))
    if not service and not resource_name:
        return None
    occurrences = _text(record.get("occurrences"))
    first_seen = _text(record.get("first_seen"))
    last_seen = _text(record.get("last_seen"))
    error_type = _text(record.get("error_type"))
    where = " on ".join(
        part for part in (f"Error spans in {service}" if service else "Error spans", resource_name) if part
    )
    summary = f"{where}: {occurrences} occurrences" if occurrences else where
    if first_seen and last_seen:
        summary += f" between {first_seen} and {last_seen}"
    lines = [summary]
    if error_type:
        lines.append(error_type)
    extra: dict[str, Any] = {"kind": "error_span"}
    for field in ("service", "resource_name", "occurrences", "first_seen", "last_seen", "error_type"):
        value = record.get(field)
        extra[field] = None if value is None else str(value)
    return SignalEmitterOutput(
        source_product="datadog",
        source_type="issue",
        source_id=span_source_id(record),
        description="\n".join(lines),
        # Below the report threshold of 1.0, so one noisy group alone cannot open a report.
        weight=0.5,
        extra=extra,
    )


DATADOG_ERROR_SPANS_CONFIG = SignalSourceTableConfig(
    source_product="datadog",
    source_type="issue",
    emitter=datadog_error_span_emitter,
    record_fetcher=datadog_error_span_record_fetcher,
    # Each group is emitted once through the ledger, because every sync window can contain it again.
    record_processed_outputs=True,
    partition_field="start_timestamp",
    partition_field_is_datetime_string=True,
    fields=DATADOG_ERROR_SPAN_FIELDS,
    max_records=50,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
