"""Signal emitter for mux `errors` (record kind: issue).

Each row is one Mux Data playback error, aggregated over the synced window, with no creation time.
The sync rewrites the rows on every run, so the fetcher reads the errors seen in a trailing window of `last_seen`.
The emitter produces one signal per error, at most once per ISO week.
The emission ledger and the weekly fingerprint keep re-reading the same rows safe.
`notes` is not read, because people write it.
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

MUX_ERROR_FIELDS = (
    "id",
    "error_code",
    "error_message",
    "error_description",
    "view_count",
    "view_share",
    "last_seen_at",
)

_EXTRA_FIELDS = ("error_code", "view_count", "view_share", "last_seen_at")
_MAX_TEXT_CHARS = 1000

# Each alias differs from its column name, so the WHERE clause on `last_seen` reads the column and not the aggregate.
_SELECT_SQL = """
    id,
    any(code) AS error_code,
    any(message) AS error_message,
    any(description) AS error_description,
    max(count) AS view_count,
    max(percentage) AS view_share,
    max(last_seen) AS last_seen_at
"""


def mux_error_source_id(record: dict[str, Any]) -> str:
    # The week lets an error that keeps happening, or returns after a fix, emit again.
    fingerprint = "|".join((clean_text(record.get("id")), week_period(record.get("last_seen_at"))))
    return "mux_error:" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


mux_error_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="id",
    order_by_sql="view_count DESC",
    source_id_for=mux_error_source_id,
)


def mux_error_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    error_id = clean_text(record.get("id"))
    message = clean_text(record.get("error_message"))[:_MAX_TEXT_CHARS]
    description = clean_text(record.get("error_description"))[:_MAX_TEXT_CHARS]
    if not error_id or not (message or description):
        logger.info(
            "Ignoring mux error without an id or text",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    code = clean_text(record.get("error_code"))
    views = clean_text(record.get("view_count"))
    share = clean_text(record.get("view_share"))
    lines = [f"Video playback error {code}: {message or description}" if code else message or description]
    if message and description and description != message:
        lines.append(description)
    if views:
        impact = f"Affected {views} views"
        if share:
            impact += f" (share of views: {share})"
        lines.append(impact)
    return SignalEmitterOutput(
        source_product="mux",
        source_type="issue",
        source_id=mux_error_source_id(record),
        description="\n".join(lines),
        # Below the report threshold of 1.0, so one error alone cannot open a report.
        weight=0.5,
        extra={"error_id": error_id, **build_extra(record, _EXTRA_FIELDS, ())},
    )


MUX_ERRORS_CONFIG = SignalSourceTableConfig(
    source_product="mux",
    source_type="issue",
    emitter=mux_error_emitter,
    record_fetcher=mux_error_record_fetcher,
    # Each error is emitted once a week through the ledger, because every sync rewrites it.
    record_processed_outputs=True,
    partition_field="toString(last_seen)",
    partition_field_is_datetime_string=True,
    fields=MUX_ERROR_FIELDS,
    max_records=50,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
