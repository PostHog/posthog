import re
import json
from typing import Any

from structlog import get_logger

from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

LINEAR_IGNORED_STATE_TYPES = ("completed", "canceled")

# Config key on the team's SignalSourceConfig.config holding the Linear team IDs the user opted into.
# Absent or empty means "all teams" (unchanged behavior); a non-empty list scopes emitted issues to
# just those teams. See _linear_team_scope_where.
LINEAR_TEAM_IDS_CONFIG_KEY = "linear_team_ids"
# Linear team IDs are UUIDs. Restricting to this charset both validates the config and keeps the IDs
# safe to inline as string literals in the scoping clause (no quotes/backslashes can appear).
_LINEAR_TEAM_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")

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
    "created_at",
    "updated_at",
)


def linear_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
        title = record["title"]
        description = record["description"]
    except KeyError as e:
        msg = f"Linear issue record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id or not title:
        msg = f"Linear issue record has empty required field: id={issue_id!r}, title={title!r}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
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
        logger.exception(msg, record=record, signals_type="data-import-signals")
        raise ValueError(msg)
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError) as e:
        msg = f"Linear issue {field_name} field is not valid JSON: {raw_value!r}"
        logger.exception(msg, record=record, signals_type="data-import-signals")
        raise ValueError(msg) from e


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
        logger.exception(msg, record=record, signals_type="data-import-signals")
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
    return extra


def _linear_team_scope_where(source_config: dict[str, Any]) -> str | None:
    """Scope emitted Linear issues to the teams the user opted into.

    A workspace-wide Linear OAuth token imports every issue from every team in the workspace, so
    without this the pipeline would surface issues from teams the user has nothing to do with. When
    `linear_team_ids` is configured, only issues whose `team.id` is in the allowlist emit. Absent or
    empty config leaves behavior unchanged (all teams). If the allowlist is set but no entry is a
    valid Linear team ID we fail closed (match nothing) rather than leak every team.
    """
    raw = source_config.get(LINEAR_TEAM_IDS_CONFIG_KEY)
    if not raw:
        return None
    if not isinstance(raw, list):
        logger.warning(
            "Linear team scope config is not a list; ignoring and syncing all teams",
            linear_team_ids=raw,
            signals_type="data-import-signals",
        )
        return None
    valid = [t for t in raw if isinstance(t, str) and _LINEAR_TEAM_ID_RE.match(t)]
    if len(valid) != len(raw):
        logger.warning(
            "Dropped invalid Linear team IDs from scope config",
            linear_team_ids=raw,
            valid=valid,
            signals_type="data-import-signals",
        )
    # Fail closed: an allowlist was set, so never widen back to all teams — an all-invalid list
    # matches no team ('' is never a real Linear team id).
    ids = ", ".join(f"'{t}'" for t in valid) if valid else "''"
    return f"JSONExtractString(team, 'id') IN ({ids})"


LINEAR_ISSUES_CONFIG = SignalSourceTableConfig(
    source_product="linear",
    source_type="issue",
    emitter=linear_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=REQUIRED_FIELDS + EXTRA_FIELDS,
    where_clause=f"JSONExtractString(state, 'type') NOT IN ({', '.join(repr(s) for s in LINEAR_IGNORED_STATE_TYPES)})",
    source_config_where_builder=_linear_team_scope_where,
    max_records=1000,
    first_sync_lookback_days=1,  # 24 hours
    actionability_prompt=LINEAR_ACTIONABILITY_PROMPT,
    summarization_prompt=LINEAR_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
