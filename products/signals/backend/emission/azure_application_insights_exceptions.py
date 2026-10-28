"""Signal emitter for azure_application_insights `exceptions` (record kind: issue).

The table holds one row per exception occurrence.
The fetcher groups the rows of a trailing window by `problem_id`, and the emitter produces one signal per problem, at most once per ISO week.
The emission ledger and the weekly fingerprint keep re-reading the same rows safe.
"""

import hashlib
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher, week_period
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

AZURE_EXCEPTION_FIELDS = (
    "problem_id",
    "exception_type",
    "sample_message",
    "role_name",
    "occurrences",
    "first_seen",
    "last_seen",
)

_EXTRA_FIELDS = tuple(f for f in AZURE_EXCEPTION_FIELDS if f not in ("sample_message",))
_MAX_MESSAGE_CHARS = 300

_SELECT_SQL = """
    problem_id,
    any(type) AS exception_type,
    any(outer_message) AS sample_message,
    any(cloud_role_name) AS role_name,
    count() AS occurrences,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
"""


def exception_source_id(record: dict[str, Any]) -> str:
    # The week lets a fixed problem that returns, or one that stays noisy, emit again.
    fingerprint = "|".join((clean_text(record.get("problem_id")), week_period(record.get("last_seen"))))
    return "exception:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


azure_exception_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="problem_id",
    order_by_sql="occurrences DESC",
    source_id_for=exception_source_id,
)


def azure_exception_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    problem_id = clean_text(record.get("problem_id"))
    exception_type = clean_text(record.get("exception_type"))
    message = clean_text(record.get("sample_message"))[:_MAX_MESSAGE_CHARS]
    if not problem_id or not (exception_type or message):
        logger.info(
            "Ignoring azure_application_insights exception group without a type or message",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    role_name = clean_text(record.get("role_name"))
    occurrences = clean_text(record.get("occurrences"))
    first_seen = clean_text(record.get("first_seen"))
    last_seen = clean_text(record.get("last_seen"))
    summary = f"Exceptions in {role_name}" if role_name else "Exceptions"
    if occurrences:
        summary += f": {occurrences} occurrences"
    if first_seen and last_seen:
        summary += f" between {first_seen} and {last_seen}"
    lines = [summary]
    if exception_type:
        lines.append(exception_type)
    if message:
        lines.append(message)
    return SignalEmitterOutput(
        source_product="azure_application_insights",
        source_type="issue",
        source_id=exception_source_id(record),
        description="\n".join(lines),
        # Below the report threshold of 1.0, so one noisy problem alone cannot open a report.
        weight=0.5,
        extra=build_extra(record, _EXTRA_FIELDS, ()),
    )


AZURE_EXCEPTIONS_CONFIG = SignalSourceTableConfig(
    source_product="azure_application_insights",
    source_type="issue",
    emitter=azure_exception_emitter,
    record_fetcher=azure_exception_record_fetcher,
    record_processed_outputs=True,
    partition_field="toString(timestamp)",
    partition_field_is_datetime_string=True,
    fields=AZURE_EXCEPTION_FIELDS,
    where_clause="problem_id != ''",
    max_records=100,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
