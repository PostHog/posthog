"""Signal emitter for newrelic `alert_issues` (record kind: issue).

The table holds one NrAiIssue event row per lifecycle change of an alert issue (create, activate, acknowledge, close).
Only the `activate` row is read: New Relic notifies on activation, and an issue closed before activation never paged anyone.
The New Relic sync stops a few minutes before its start time, so a cursor on the previous sync start would skip the rows it imports late.
The grouped fetcher rereads a trailing window instead, with one group per issue.
The source id is the issue id, so the emission ledger drops an issue that already produced a signal.
`title` is a string or a JSON list of strings, depending on how many incidents the issue correlates.
New Relic uses the record kind `issue` for every table, so one inbox toggle covers New Relic errors and alerts.
"""

import json
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.grouped_warehouse import grouped_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

NEWRELIC_ALERT_ISSUE_FIELDS = ("issue_id", "issue_title", "issue_priority", "activated_at")

# Each alias differs from its column name, so the WHERE clause on `timestamp` reads the column and not the aggregate.
_SELECT_SQL = """
    issue_id,
    argMax(title, timestamp) AS issue_title,
    argMax(priority, timestamp) AS issue_priority,
    max(timestamp) AS activated_at
"""

_MAX_TITLES = 5


def issue_title(raw: Any) -> str:
    """The issue title as one line, joining the titles of a JSON list."""
    text = clean_text(raw)
    if not text.startswith("["):
        return text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(parsed, list):
        return text
    titles: list[str] = []
    for item in parsed:
        title = clean_text(item) if isinstance(item, str) else ""
        if title and title not in titles:
            titles.append(title)
    return "; ".join(titles[:_MAX_TITLES])


def alert_issue_source_id(record: dict[str, Any]) -> str:
    return f"alert_issue:{clean_text(record.get('issue_id'))}"


newrelic_alert_issue_record_fetcher = grouped_warehouse_record_fetcher(
    select_sql=_SELECT_SQL,
    group_by_sql="issue_id",
    order_by_sql="activated_at DESC",
    source_id_for=alert_issue_source_id,
)


def newrelic_alert_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = clean_text(record["issue_id"])
        title = issue_title(record["issue_title"])
    except KeyError as e:
        msg = f"newrelic alert issue record missing required field {e}"
        logger.exception(msg, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not title:
        logger.info(
            "Ignoring newrelic alert issue with empty id or title",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    priority = clean_text(record.get("issue_priority"))
    description = f"New Relic alert: {title}"
    if priority:
        description += f"\nPriority: {priority.lower()}"
    return SignalEmitterOutput(
        source_product="newrelic",
        source_type="issue",
        source_id=alert_issue_source_id(record),
        description=description,
        weight=1.0,
        extra={
            "kind": "alert_issue",
            "issue_id": issue_id,
            "priority": priority or None,
            "activated_at": clean_text(record.get("activated_at")) or None,
        },
    )


NEWRELIC_ALERT_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="newrelic",
    source_type="issue",
    emitter=newrelic_alert_issue_emitter,
    record_fetcher=newrelic_alert_issue_record_fetcher,
    # Every sync window can contain the issue again, so the ledger keeps it to one signal.
    record_processed_outputs=True,
    partition_field="toString(timestamp)",
    partition_field_is_datetime_string=True,
    fields=NEWRELIC_ALERT_ISSUE_FIELDS,
    where_clause="lower(toString(event)) = 'activate'",
    max_records=200,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
