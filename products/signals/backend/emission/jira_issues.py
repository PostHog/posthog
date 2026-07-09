import re
import json
from typing import Any

from structlog import get_logger

from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

# Jira workflow status names that mean "no longer actionable". Status names are workflow-configurable,
# so this is a best-effort default matching the common Jira Cloud terminal statuses.
JIRA_DONE_STATUS_NAMES = ("Done", "Closed", "Resolved")

JIRA_SUMMARIZATION_PROMPT = """Summarize this Jira issue for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue
2. A concise summary capturing the problem or request, the product area affected, and key context like error messages or what the user was doing when the issue occurred

Strip raw logs, full stack traces, and large code blocks — but keep specific error messages and high-level reproduction context if they clarify the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<issue>
{description}
</issue>
"""

JIRA_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a Jira issue, determine if it contains actionable product feedback.

An issue is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression
- A question about how to use the product
- A gap or error in documentation that caused confusion
- and similar cases

An issue is NOT_ACTIONABLE if it is:
- A meta/tracking issue with no substantive feedback (release checklists, sprint trackers, epics that only link children)
- An internal housekeeping task (dependency bumps, CI config, infra maintenance)
- A duplicate that only says "same as X" with no new information

When in doubt, classify as ACTIONABLE. Jira issues are filed intentionally, so err on the side of capturing the signal.

<issue>
{description}
</issue>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# The `issues` warehouse table stores raw Jira API columns (`id`, `key`, `self`, `fields`, `expand`)
# plus `created`/`updated` promoted to top-level columns by the source. Everything else (summary,
# status, priority, assignee, labels, description) lives inside the `fields` JSON blob, so we
# JSON-extract it in the SELECT and read the aliased columns in the emitter.
FIELDS = (
    "id",
    "key",
    "self AS self_url",
    "created",
    "updated",
    "JSONExtractString(fields, 'summary') AS summary",
    "JSONExtractString(JSONExtractRaw(fields, 'status'), 'name') AS status",
    "JSONExtractString(JSONExtractRaw(fields, 'priority'), 'name') AS priority",
    "JSONExtractString(JSONExtractRaw(fields, 'assignee'), 'displayName') AS assignee",
    "JSONExtractRaw(fields, 'labels') AS labels",
    "JSONExtractRaw(fields, 'description') AS description",
)

EXTRA_FIELDS = ("key", "url", "status", "priority", "assignee", "labels", "created", "updated")


def jira_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        key = record["key"]
        summary = record["summary"]
    except KeyError as e:
        msg = f"Jira issue record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not summary:
        msg = f"Jira issue record has empty required field: id={issue_id!r}, summary={summary!r}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)
    # Jira descriptions are Atlassian Document Format (rich JSON), not plain text; many issues have
    # only a summary. Use the summary as the title and append any extractable body text.
    body = _adf_to_text(record.get("description"))
    description = f"{summary}\n{body}" if body else summary
    return SignalEmitterOutput(
        source_product="jira",
        source_type="issue",
        source_id=str(issue_id),
        description=description,
        weight=1.0,
        extra=_build_extra(record, key),
    )


def _adf_to_text(raw: Any) -> str:
    """Best-effort plain-text extraction from an Atlassian Document Format description blob."""
    if not raw:
        return ""
    try:
        doc = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return ""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                parts.append(node["text"])
            for child in node.get("content", []) or []:
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return " ".join(parts).strip()


def _browse_url(self_url: Any, key: str) -> str | None:
    """Turn the issue's REST `self` URL into a human browse URL (…/browse/PROJ-123)."""
    if not isinstance(self_url, str) or not self_url:
        return None
    match = re.match(r"(https?://[^/]+)", self_url)
    return f"{match.group(1)}/browse/{key}" if match else self_url


def _parse_labels(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(label) for label in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return [str(label) for label in parsed] if isinstance(parsed, list) else []
    return []


def _build_extra(record: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "key": str(key),
        "url": _browse_url(record.get("self_url"), key),
        "status": record.get("status") or None,
        "priority": record.get("priority") or None,
        "assignee": record.get("assignee") or None,
        "labels": _parse_labels(record.get("labels")),
        "created": str(record["created"]) if record.get("created") is not None else None,
        "updated": str(record["updated"]) if record.get("updated") is not None else None,
    }


JIRA_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="jira",
    source_type="issue",
    emitter=jira_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    # `created` is promoted to a top-level column by the source. Its stored type (String vs DateTime)
    # depends on the warehouse sync, so wrap in toString(...) + parseDateTimeBestEffort to be robust
    # to either — verify against a real sync when first enabling this source.
    partition_field="toString(created)",
    partition_field_is_datetime_string=True,
    fields=FIELDS,
    where_clause=(
        "JSONExtractString(JSONExtractRaw(fields, 'status'), 'name') "
        f"NOT IN ({', '.join(repr(s) for s in JIRA_DONE_STATUS_NAMES)})"
    ),
    max_records=1000,
    first_sync_lookback_days=1,  # 24 hours
    actionability_prompt=JIRA_ACTIONABILITY_PROMPT,
    summarization_prompt=JIRA_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
