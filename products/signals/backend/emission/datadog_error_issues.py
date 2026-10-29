"""Signal emitter for datadog `error_tracking_issues` (record kind: issue).

The table has one row per Datadog Error Tracking issue, which already groups errors across APM traces, logs and RUM.
`first_seen` is an ISO string and never changes, so the time cursor emits each issue once, as `sentry_issues.py` does with `firstSeen`.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

DATADOG_ERROR_ISSUE_FIELDS = (
    "id",
    "error_type",
    "error_message",
    "service",
    "state",
    "platform",
    "file_path",
    "function_name",
    "first_seen",
    "last_seen",
    "is_crash",
    "window_total_count",
    "window_impacted_users",
)

logger = get_logger(__name__)

_EXTRA_FIELDS = tuple(f for f in DATADOG_ERROR_ISSUE_FIELDS if f not in ("id", "error_message"))
_TRUE_VALUES = ("true", "1")
_MAX_MESSAGE_CHARS = 200


def _is_crash(value: Any) -> bool:
    return clean_text(value).lower() in _TRUE_VALUES


def _details(record: dict[str, Any]) -> str:
    parts: list[str] = []
    if service := clean_text(record.get("service")):
        parts.append(f"Service: {service}")
    file_path = clean_text(record.get("file_path"))
    function_name = clean_text(record.get("function_name"))
    location = ":".join(part for part in (file_path, function_name) if part)
    if location:
        parts.append(f"Location: {location}")
    if events := clean_text(record.get("window_total_count")):
        parts.append(f"Events: {events}")
    if users := clean_text(record.get("window_impacted_users")):
        parts.append(f"Users: {users}")
    if _is_crash(record.get("is_crash")):
        parts.append("Crash")
    return ", ".join(parts)


def datadog_error_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = clean_text(record["id"])
    except KeyError as e:
        msg = f"datadog error issue record missing required field {e}"
        logger.exception(msg, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    # An issue can have no error type, so the first message line stands in as its title.
    message_line = (clean_text(record.get("error_message")).splitlines() or [""])[0].strip()[:_MAX_MESSAGE_CHARS]
    title = clean_text(record.get("error_type")) or message_line
    if not issue_id or not title:
        logger.info(
            "Ignoring datadog error issue with empty id or title",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    lines = [title]
    # Datadog's grouped representative message, like Sentry's title; raw span and log messages are excluded as possible personal data.
    if message_line and message_line != title:
        lines.append(message_line)
    if details := _details(record):
        lines.append(details)
    return SignalEmitterOutput(
        source_product="datadog",
        source_type="issue",
        source_id=f"error_tracking_issue:{issue_id}",
        description="\n".join(lines),
        weight=1.0,
        extra={"kind": "error_tracking_issue", **build_extra(record, _EXTRA_FIELDS, ())},
    )


DATADOG_ERROR_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="datadog",
    source_type="issue",
    emitter=datadog_error_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="first_seen",
    partition_field_is_datetime_string=True,
    fields=DATADOG_ERROR_ISSUE_FIELDS,
    where_clause="ifNull(state, '') NOT IN ('RESOLVED', 'IGNORED', 'EXCLUDED')",
    # The busiest new issues come first, so a deploy that opens hundreds of issues keeps the ones that matter.
    order_by="window_total_count DESC",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
