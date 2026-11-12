"""Signal emitters for newrelic `javascript_errors` and `transaction_errors` (record kind: issue).

Both tables hold one NRQL event row per error occurrence, with no issue id.
The fetcher groups the rows of a trailing window by app, error class and error message, and the emitter produces one signal per group, at most once per ISO week.
The emission ledger and the weekly fingerprint keep re-reading the same rows safe.
The import snake_cases the NRQL attribute names, so `error.class` and `errorClass` both become `error_class`.
"""

import hashlib
from collections.abc import Callable
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher, week_period
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

_MAX_MESSAGE_CHARS = 500
_GROUP_BY_SQL = "app_name, error_class, error_message"

NEWRELIC_JAVASCRIPT_ERROR_FIELDS = (
    "app_name",
    "error_class",
    "error_message",
    "occurrences",
    "first_seen",
    "last_seen",
)
NEWRELIC_TRANSACTION_ERROR_FIELDS = (*NEWRELIC_JAVASCRIPT_ERROR_FIELDS, "sample_transaction")

_GROUP_AGGREGATES_SQL = """
    count() AS occurrences,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
"""
# The stack trace and page URL are not selected: one sample adds little to the group, and a URL can carry ids.
_JAVASCRIPT_SELECT_SQL = f"{_GROUP_BY_SQL},{_GROUP_AGGREGATES_SQL}"
_TRANSACTION_SELECT_SQL = f"{_GROUP_BY_SQL}, any(transaction_name) AS sample_transaction,{_GROUP_AGGREGATES_SQL}"


def _source_id_for(prefix: str) -> Callable[[dict[str, Any]], str]:
    def source_id(record: dict[str, Any]) -> str:
        fingerprint = "|".join(
            (
                clean_text(record.get("app_name")),
                clean_text(record.get("error_class")),
                clean_text(record.get("error_message")),
                week_period(record.get("last_seen")),
            )
        )
        return f"{prefix}:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()

    return source_id


javascript_error_source_id = _source_id_for("javascript_error")
transaction_error_source_id = _source_id_for("transaction_error")


def _make_emitter(
    *, kind: str, label: str, source_id_for: Callable[[dict[str, Any]], str], extra_fields: tuple[str, ...]
) -> Callable[[int, dict[str, Any]], SignalEmitterOutput | None]:
    def emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
        error_class = clean_text(record.get("error_class"))
        message = clean_text(record.get("error_message"))[:_MAX_MESSAGE_CHARS]
        if not error_class and not message:
            logger.info(
                f"Ignoring newrelic {kind} group without an error class or message",
                team_id=team_id,
                signals_type="data-import-signals",
            )
            return None
        app_name = clean_text(record.get("app_name"))
        occurrences = clean_text(record.get("occurrences"))
        first_seen = clean_text(record.get("first_seen"))
        last_seen = clean_text(record.get("last_seen"))
        headline = f"{error_class}: {message}" if error_class and message else error_class or message
        summary = f"{label} in {app_name}" if app_name else label
        if occurrences:
            summary += f": {occurrences} occurrences"
        if first_seen and last_seen:
            summary += f" between {first_seen} and {last_seen}"
        lines = [headline, summary]
        transaction = clean_text(record.get("sample_transaction"))
        if transaction:
            lines.append(f"Transaction: {transaction}")
        return SignalEmitterOutput(
            source_product="newrelic",
            source_type="issue",
            source_id=source_id_for(record),
            description="\n".join(lines),
            # Below the report threshold of 1.0, so one noisy group alone cannot open a report.
            weight=0.5,
            extra={"kind": kind, **build_extra(record, extra_fields, ())},
        )

    return emitter


newrelic_javascript_error_emitter = _make_emitter(
    kind="javascript_error",
    label="JavaScript errors",
    source_id_for=javascript_error_source_id,
    extra_fields=tuple(f for f in NEWRELIC_JAVASCRIPT_ERROR_FIELDS if f != "error_message"),
)
newrelic_transaction_error_emitter = _make_emitter(
    kind="transaction_error",
    label="Transaction errors",
    source_id_for=transaction_error_source_id,
    extra_fields=tuple(f for f in NEWRELIC_TRANSACTION_ERROR_FIELDS if f != "error_message"),
)


NEWRELIC_JAVASCRIPT_ERRORS_CONFIG = SignalSourceTableConfig(
    source_product="newrelic",
    source_type="issue",
    emitter=newrelic_javascript_error_emitter,
    record_fetcher=grouped_warehouse_record_fetcher(
        select_sql=_JAVASCRIPT_SELECT_SQL,
        group_by_sql=_GROUP_BY_SQL,
        order_by_sql="occurrences DESC",
        source_id_for=javascript_error_source_id,
    ),
    # Each group is emitted once through the ledger, because every sync window can contain it again.
    record_processed_outputs=True,
    partition_field="toString(timestamp)",
    partition_field_is_datetime_string=True,
    fields=NEWRELIC_JAVASCRIPT_ERROR_FIELDS,
    max_records=50,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)

NEWRELIC_TRANSACTION_ERRORS_CONFIG = SignalSourceTableConfig(
    source_product="newrelic",
    source_type="issue",
    emitter=newrelic_transaction_error_emitter,
    record_fetcher=grouped_warehouse_record_fetcher(
        select_sql=_TRANSACTION_SELECT_SQL,
        group_by_sql=_GROUP_BY_SQL,
        order_by_sql="occurrences DESC",
        source_id_for=transaction_error_source_id,
    ),
    record_processed_outputs=True,
    partition_field="toString(timestamp)",
    partition_field_is_datetime_string=True,
    fields=NEWRELIC_TRANSACTION_ERROR_FIELDS,
    max_records=50,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
