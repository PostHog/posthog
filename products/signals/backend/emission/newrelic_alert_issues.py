"""Signal emitter for newrelic `alert_issues` (record kind: issue).

The table holds one NrAiIssue event row per lifecycle change of an alert issue (create, activate, acknowledge, close).
Only the `activate` row is read: New Relic notifies on activation, and an issue closed before activation never paged anyone.
Every row of one issue shares `issue_id`, so the source id is the issue id and the ledger refuses a second signal for it.
`title` is a string or a JSON list of strings, depending on how many incidents the issue correlates.
New Relic uses the record kind `issue` for every table, so one inbox toggle covers New Relic errors and alerts.
"""

import json
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.datadog_common import clean_text
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

NEWRELIC_ALERT_ISSUE_FIELDS = ("issue_id", "title", "priority", "timestamp")

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


def newrelic_alert_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = clean_text(record["issue_id"])
        title = issue_title(record["title"])
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
    priority = clean_text(record.get("priority"))
    description = f"New Relic alert: {title}"
    if priority:
        description += f"\nPriority: {priority.lower()}"
    return SignalEmitterOutput(
        source_product="newrelic",
        source_type="issue",
        source_id=f"alert_issue:{issue_id}",
        description=description,
        weight=1.0,
        extra={
            "kind": "alert_issue",
            "issue_id": issue_id,
            "priority": priority or None,
            "activated_at": clean_text(record.get("timestamp")) or None,
        },
    )


NEWRELIC_ALERT_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="newrelic",
    source_type="issue",
    emitter=newrelic_alert_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    # A sync can hold more than one activate row for an issue, so the issue id is the idempotency key.
    record_processed_outputs=True,
    partition_field="toString(timestamp)",
    partition_field_is_datetime_string=True,
    fields=NEWRELIC_ALERT_ISSUE_FIELDS,
    where_clause="lower(toString(event)) = 'activate'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
