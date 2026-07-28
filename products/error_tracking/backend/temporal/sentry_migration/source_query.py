"""HogQL query builders over the synced Sentry warehouse tables.

Table names come from DataWarehouseTable rows (validated identifiers), everything
user-controlled goes through HogQL placeholders.
"""

import re
from typing import Any

from posthog.hogql import ast

_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

# Ascending (date, issue, event) keyset — oldest-first emission is load-bearing:
# cymbal sets issue/fingerprint first_seen from the first event's timestamp.
_EVENTS_ORDER = "e.date_created ASC, toString(e.issue_id) ASC, toString(e.event_id) ASC"

_ISSUE_COLUMNS = (
    "i.title AS issue_title, i.culprit AS issue_culprit, i.level AS issue_level, "
    "i.status AS issue_status, i.permalink AS issue_permalink, i.short_id AS issue_short_id, "
    "i.count AS issue_count, i.user_count AS issue_user_count, i.first_seen AS issue_first_seen, "
    "i.project AS issue_project"
)


def _validate_table(name: str) -> str:
    if not _TABLE_NAME_RE.match(name):
        raise ValueError(f"Invalid warehouse table name: {name!r}")
    return name


def _config_filters(config: dict[str, Any]) -> tuple[list[str], dict[str, ast.Expr]]:
    conditions: list[str] = []
    placeholders: dict[str, ast.Expr] = {}
    if config.get("date_from"):
        conditions.append("e.date_created >= {date_from}")
        placeholders["date_from"] = ast.Constant(value=str(config["date_from"]))
    if config.get("date_to"):
        conditions.append("e.date_created < {date_to}")
        placeholders["date_to"] = ast.Constant(value=str(config["date_to"]))
    statuses = config.get("issue_statuses")
    if statuses:
        conditions.append("i.status IN {issue_statuses}")
        placeholders["issue_statuses"] = ast.Tuple(exprs=[ast.Constant(value=str(s)) for s in statuses])
    # sentry_project_slugs is filtered in Python (the slug lives inside the issue's
    # serialized project JSON, not a queryable column).
    return conditions, placeholders


def _cursor_filter(cursor: dict[str, Any] | None) -> tuple[list[str], dict[str, ast.Expr]]:
    if not cursor:
        return [], {}
    condition = (
        "(e.date_created, toString(e.issue_id), toString(e.event_id)) > "
        "({cursor_ts}, {cursor_issue_id}, {cursor_event_id})"
    )
    placeholders: dict[str, ast.Expr] = {
        "cursor_ts": ast.Constant(value=str(cursor["date_created"])),
        "cursor_issue_id": ast.Constant(value=str(cursor["issue_id"])),
        "cursor_event_id": ast.Constant(value=str(cursor["event_id"])),
    }
    return [condition], placeholders


def build_events_page_query(
    events_table: str,
    issues_table: str,
    config: dict[str, Any],
    cursor: dict[str, Any] | None,
    page_size: int,
) -> tuple[str, dict[str, ast.Expr]]:
    events = _validate_table(events_table)
    issues = _validate_table(issues_table)
    filter_conditions, placeholders = _config_filters(config)
    cursor_conditions, cursor_placeholders = _cursor_filter(cursor)
    placeholders.update(cursor_placeholders)
    conditions = filter_conditions + cursor_conditions
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = (
        f"SELECT e.*, {_ISSUE_COLUMNS} "
        f"FROM {events} AS e "
        f"INNER JOIN {issues} AS i ON toString(i.id) = toString(e.issue_id) "
        f"{where} "
        f"ORDER BY {_EVENTS_ORDER} "
        f"LIMIT {int(page_size)}"
    )
    return query, placeholders


def build_events_count_query(
    events_table: str, issues_table: str, config: dict[str, Any]
) -> tuple[str, dict[str, ast.Expr]]:
    events = _validate_table(events_table)
    issues = _validate_table(issues_table)
    conditions, placeholders = _config_filters(config)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = (
        f"SELECT count(), count(DISTINCT toString(e.issue_id)) "
        f"FROM {events} AS e "
        f"INNER JOIN {issues} AS i ON toString(i.id) = toString(e.issue_id) "
        f"{where}"
    )
    return query, placeholders


def build_issue_status_page_query(
    issues_table: str, cursor: str | None, page_size: int
) -> tuple[str, dict[str, ast.Expr]]:
    issues = _validate_table(issues_table)
    placeholders: dict[str, ast.Expr] = {}
    where = ""
    if cursor:
        where = "WHERE toString(i.id) > {cursor_issue_id}"
        placeholders["cursor_issue_id"] = ast.Constant(value=str(cursor))
    query = (
        f"SELECT toString(i.id), i.status FROM {issues} AS i {where} ORDER BY toString(i.id) ASC LIMIT {int(page_size)}"
    )
    return query, placeholders
