"""Signal emitter for datadog `error_tracking_issues` (record kind: issue).

The table has one row per Datadog Error Tracking issue, which already groups errors across APM
traces, logs and RUM. `first_seen` is an ISO string and never changes, so the time cursor emits
each issue once, as `sentry_issues.py` does with `firstSeen`.
"""

from typing import Any

from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
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

_EXTRA_FIELDS = tuple(f for f in DATADOG_ERROR_ISSUE_FIELDS if f not in ("id", "error_message"))
_TRUE_VALUES = ("true", "1")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_crash(value: Any) -> bool:
    return _text(value).lower() in _TRUE_VALUES


def _details(record: dict[str, Any]) -> str:
    parts: list[str] = []
    if service := _text(record.get("service")):
        parts.append(f"Service: {service}")
    file_path = _text(record.get("file_path"))
    function_name = _text(record.get("function_name"))
    location = ":".join(part for part in (file_path, function_name) if part)
    if location:
        parts.append(f"Location: {location}")
    if events := _text(record.get("window_total_count")):
        parts.append(f"Events: {events}")
    if users := _text(record.get("window_impacted_users")):
        parts.append(f"Users: {users}")
    if _is_crash(record.get("is_crash")):
        parts.append("Crash")
    return ", ".join(parts)


def datadog_error_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = _text(record["id"])
    except KeyError as e:
        raise ValueError(f"datadog error issue record missing required field {e}") from e
    error_message = _text(record.get("error_message"))
    # An issue can have no error type, so the first message line stands in as its title.
    title = _text(record.get("error_type")) or (error_message.splitlines()[0] if error_message else "")
    if not issue_id or not title:
        return None
    lines = [title]
    if error_message and error_message != title:
        lines.append(error_message)
    if details := _details(record):
        lines.append(details)
    extra: dict[str, Any] = {"kind": "error_tracking_issue"}
    for field in _EXTRA_FIELDS:
        value = record.get(field)
        extra[field] = None if value is None else str(value)
    return SignalEmitterOutput(
        source_product="datadog",
        source_type="issue",
        source_id=f"error_issue:{issue_id}",
        description="\n".join(lines),
        weight=1.0,
        extra=extra,
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
