"""Signal emitter for google_play_console `error_issues` (record kind: issue).

The table is a full refresh with one row per clustered crash or ANR issue, and it has no creation time.
The fetcher reads the issues with a recent report and the emission ledger keeps each issue name to one signal.
Aliases differ from the column names, because a grouped query cannot reuse a column name for an aggregate.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra
from products.signals.backend.emission._prompts import ERROR_ACTIONABILITY_PROMPT, ERROR_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

GOOGLE_PLAY_CONSOLE_ERROR_ISSUE_FIELDS = (
    "issue_name",
    "issue_type",
    "cause",
    "code_location",
    "report_count",
    "affected_users",
    "first_version",
    "last_version",
    "last_report_time",
    "issue_url",
)

_EXTRA_FIELDS = tuple(f for f in GOOGLE_PLAY_CONSOLE_ERROR_ISSUE_FIELDS if f not in ("issue_name", "cause"))

_SELECT_SQL = """
    name AS issue_name,
    any(type) AS issue_type,
    any(cause) AS cause,
    any(location) AS code_location,
    max(error_report_count) AS report_count,
    max(distinct_users) AS affected_users,
    any(first_app_version) AS first_version,
    any(last_app_version) AS last_version,
    max(last_error_report_time) AS last_report_time,
    any(issue_uri) AS issue_url
"""


def issue_source_id(record: dict[str, Any]) -> str:
    return clean_text(record.get("issue_name"))


google_play_console_error_issue_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="name",
    order_by_sql="report_count DESC",
    source_id_for=issue_source_id,
)


def google_play_console_error_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    source_id = issue_source_id(record)
    cause = clean_text(record.get("cause"))
    location = clean_text(record.get("code_location"))
    if not source_id or not (cause or location):
        logger.info(
            "Ignoring google_play_console error issue without a cause or location",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    issue_type = clean_text(record.get("issue_type")) or "Error"
    lines = [f"Google Play {issue_type}: {cause}" if cause else f"Google Play {issue_type}"]
    if location:
        lines.append(f"Location: {location}")
    stats = ", ".join(
        part
        for part in (
            f"Reports: {clean_text(record.get('report_count'))}" if clean_text(record.get("report_count")) else "",
            f"Users: {clean_text(record.get('affected_users'))}" if clean_text(record.get("affected_users")) else "",
        )
        if part
    )
    if stats:
        lines.append(stats)
    return SignalEmitterOutput(
        source_product="google_play_console",
        source_type="issue",
        source_id=source_id,
        description="\n".join(lines),
        weight=1.0,
        extra=build_extra(record, _EXTRA_FIELDS, ()),
    )


GOOGLE_PLAY_CONSOLE_ERROR_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="google_play_console",
    source_type="issue",
    emitter=google_play_console_error_issue_emitter,
    record_fetcher=google_play_console_error_issue_record_fetcher,
    record_processed_outputs=True,
    partition_field="toString(last_error_report_time)",
    partition_field_is_datetime_string=True,
    fields=GOOGLE_PLAY_CONSOLE_ERROR_ISSUE_FIELDS,
    max_records=200,
    actionability_prompt=ERROR_ACTIONABILITY_PROMPT,
    summarization_prompt=ERROR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
