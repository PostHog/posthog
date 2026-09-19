import json
from typing import Any

from structlog import get_logger

from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig, redacted_record

logger = get_logger(__name__)

LINEAR_IGNORED_STATE_TYPES = ("completed", "canceled")

LINEAR_SUMMARIZATION_PROMPT = """Summarize this Linear issue for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue
2. A concise summary capturing the problem or request, the product area affected, and key context like error messages or what the user was doing when the issue occurred

Strip raw logs, full stack traces, and large code blocks — but keep specific error messages and high-level reproduction context if they clarify the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<issue>
{description}
</issue>
"""

LINEAR_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a Linear issue, determine if it contains actionable product feedback.

An issue is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression
- A question about how to use the product
- A gap or error in documentation that caused confusion
- and similar cases

An issue is NOT_ACTIONABLE if it is:
- A meta/tracking issue with no feedback (release checklists, sprint trackers)
- A duplicate that only says "same as X" with no new information
- An internal housekeeping task (dependency bumps, CI config, infra maintenance)

The issue may end with a record_metadata block. `assignee_name` names the person the issue is assigned to in Linear, and the key is null or absent when the issue has no assignee. The assignee is context and not a verdict. An assigned issue still describes real feedback, so never classify an issue as NOT_ACTIONABLE only because it has an assignee.

When in doubt, classify as ACTIONABLE. Linear issues are filed intentionally, so err on the side of capturing the signal.

<issue>
{description}
</issue>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

REQUIRED_FIELDS = ("id", "title", "description")

EXTRA_FIELDS = (
    "url",
    "identifier",
    "number",
    "priority",
    "priority_label",
    "labels",
    "state",
    "team",
    "assignee",
    "created_at",
    "updated_at",
)

# `assignee` never belongs in a log line: the emitter keeps the name and drops the id and the email
# address, and the shared pipeline logs whole records when an emitter raises.
UNLOGGABLE_FIELDS = ("assignee",)


def _loggable(record: dict[str, Any]) -> dict[str, Any]:
    return redacted_record(record, UNLOGGABLE_FIELDS)


def linear_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        title = record["title"]
        description = record["description"]
    except KeyError as e:
        msg = f"Linear issue record missing required field {e}"
        logger.exception(msg, record=_loggable(record), team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not title:
        msg = f"Linear issue record has empty required field: id={issue_id!r}, title={title!r}"
        logger.exception(msg, record=_loggable(record), team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)
    if not description:
        return None
    return SignalEmitterOutput(
        source_product="linear",
        source_type="issue",
        source_id=str(issue_id),
        description=f"{title}\n{description}",
        weight=1.0,
        extra=_build_extra(record),
    )


def _parse_json_field(field_name: str, raw_value: Any, record: dict[str, Any]) -> Any:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        msg = f"Linear issue {field_name} field has unexpected type {type(raw_value).__name__}: {raw_value!r}"
        logger.exception(msg, record=_loggable(record), signals_type="data-import-signals")
        raise ValueError(msg)
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError) as e:
        msg = f"Linear issue {field_name} field is not valid JSON: {raw_value!r}"
        logger.exception(msg, record=_loggable(record), signals_type="data-import-signals")
        raise ValueError(msg) from e


def _assignee_name(raw_assignee: Any) -> str | None:
    """Lift `name` out of a Linear user object, which the warehouse stores as a JSON string.

    Unlike labels, an assignee we can't read degrades to an unowned issue rather than raising: the
    owner is context for triage, not something the signal is meaningless without.
    """
    if isinstance(raw_assignee, str):
        try:
            raw_assignee = json.loads(raw_assignee)
        except (json.JSONDecodeError, TypeError):
            # The blob itself names a person, so log only enough to spot a shape change upstream.
            logger.warning(
                "Ignoring unparseable Linear issue assignee field",
                signals_type="data-import-signals",
                raw_assignee_length=len(raw_assignee),
            )
            return None
    if not isinstance(raw_assignee, dict):
        return None
    name = raw_assignee.get("name")
    return name if isinstance(name, str) and name else None


def _build_extra(record: dict[str, Any]) -> dict[str, Any]:
    raw = {k: v for k, v in record.items() if k in EXTRA_FIELDS}
    extra: dict[str, Any] = {}
    for k in ("url", "identifier", "number", "priority", "priority_label", "created_at", "updated_at"):
        extra[k] = raw[k]
    parsed_labels = _parse_json_field("labels", raw.get("labels"), record)
    if parsed_labels is None:
        extra["labels"] = []
    elif isinstance(parsed_labels, dict):
        nodes = parsed_labels.get("nodes", [])
        extra["labels"] = [n["name"] for n in nodes if isinstance(n, dict) and "name" in n]
    else:
        msg = f"Linear issue labels field has unexpected shape: {raw.get('labels')!r}"
        logger.exception(msg, record=_loggable(record), signals_type="data-import-signals")
        raise ValueError(msg)
    parsed_state = _parse_json_field("state", raw.get("state"), record)
    if isinstance(parsed_state, dict):
        extra["state_name"] = parsed_state.get("name")
        extra["state_type"] = parsed_state.get("type")
    else:
        extra["state_name"] = None
        extra["state_type"] = None
    parsed_team = _parse_json_field("team", raw.get("team"), record)
    extra["team_name"] = parsed_team.get("name") if isinstance(parsed_team, dict) else None
    # Always present, so the contract shape doesn't shift when a sync withholds the assignee.
    extra["assignee_name"] = _assignee_name(raw.get("assignee"))
    return extra


LINEAR_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="linear",
    source_type="issue",
    emitter=linear_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=f"JSONExtractString(state, 'type') NOT IN ({', '.join(repr(s) for s in LINEAR_IGNORED_STATE_TYPES)})",
    max_records=1000,
    first_sync_lookback_days=1,  # 24 hours
    actionability_prompt=LINEAR_ACTIONABILITY_PROMPT,
    actionability_context_fields=("assignee_name",),
    unloggable_fields=UNLOGGABLE_FIELDS,
    summarization_prompt=LINEAR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
