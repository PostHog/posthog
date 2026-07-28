"""Sentry adapter: turns synced Sentry warehouse rows into PostHog `$exception` events.

The warehouse pipeline serializes nested Sentry structures (entries, user, tags, project) to JSON
strings and normalizes column names, so every accessor here tolerates both camelCase (raw Sentry
API) and snake_case (dlt-normalized) keys and parses JSON strings defensively.
"""

import re
import json
import uuid
from typing import Any

from posthog.hogql import ast

from products.error_tracking.backend.models import ErrorTrackingIssue
from products.error_tracking.backend.temporal.source_migration.base import TransformContext

# Fixed namespace so re-runs regenerate identical event UUIDs — ClickHouse's events table
# dedupes on uuid, which makes the whole import idempotent.
SENTRY_IMPORT_UUID_NAMESPACE = uuid.UUID("a9f42e6d-3c1b-4a7e-9d25-8f0c6b1e5a90")

# Sentry stacktraces can be very deep with full context; cymbal truncates values but frames
# flow through whole, so bound payload size here. Frames are oldest-first — keep the most
# recent (crash-site) frames.
MAX_FRAMES = 50

SENTRY_STATUS_TO_ISSUE_STATUS: dict[str, ErrorTrackingIssue.Status] = {
    "resolved": ErrorTrackingIssue.Status.RESOLVED,
    "ignored": ErrorTrackingIssue.Status.SUPPRESSED,
    "muted": ErrorTrackingIssue.Status.SUPPRESSED,
}

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


def build_fingerprint(org_slug: str, issue_id: str) -> str:
    return f"sentry:{org_slug}:{issue_id}"


def build_event_uuid(org_slug: str, event_id: str) -> str:
    return str(uuid.uuid5(SENTRY_IMPORT_UUID_NAMESPACE, f"{org_slug}:{event_id}"))


def build_anchor_event_uuid(org_slug: str, issue_id: str) -> str:
    return str(uuid.uuid5(SENTRY_IMPORT_UUID_NAMESPACE, f"{org_slug}:issue:{issue_id}:first"))


def map_sentry_status(sentry_status: str | None) -> ErrorTrackingIssue.Status | None:
    if not sentry_status:
        return None
    return SENTRY_STATUS_TO_ISSUE_STATUS.get(sentry_status.lower())


def _get(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _parse_json(value: Any) -> Any:
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return None


def _split_context(frame: dict[str, Any]) -> tuple[list[str], str | None, list[str]]:
    # Sentry's `context` is a list of [lineno, text] pairs surrounding the frame's line.
    context = _parse_json(_get(frame, "context")) or []
    lineno = _get(frame, "lineNo", "line_no", "lineno")
    pre: list[str] = []
    context_line: str | None = _get(frame, "contextLine", "context_line")
    post: list[str] = []
    for entry in context:
        if not isinstance(entry, list | tuple) or len(entry) != 2:
            continue
        entry_lineno, text = entry
        if not isinstance(text, str):
            continue
        if lineno is not None and entry_lineno == lineno:
            context_line = text
        elif lineno is not None and entry_lineno < lineno:
            pre.append(text)
        else:
            post.append(text)
    return pre, context_line, post


def sentry_frame_to_custom_frame(frame: dict[str, Any], lang: str) -> dict[str, Any]:
    pre_context, context_line, post_context = _split_context(frame)
    return {
        # "custom" frames skip cymbal's symbolication entirely: Sentry API frames are
        # already symbolicated, and resolved=true renders them as-is with context.
        "platform": "custom",
        "lang": lang,
        "function": _get(frame, "function") or "<anonymous>",
        "filename": _get(frame, "filename") or _get(frame, "absPath", "abs_path"),
        "lineno": _get(frame, "lineNo", "line_no", "lineno"),
        "colno": _get(frame, "colNo", "col_no", "colno"),
        "module": _get(frame, "module"),
        "context_line": context_line,
        "pre_context": pre_context,
        "post_context": post_context,
        "in_app": _get(frame, "inApp", "in_app") is not False,
        "resolved": True,
    }


def _exception_entry_values(entries: Any) -> list[dict[str, Any]]:
    for entry in _parse_json(entries) or []:
        if isinstance(entry, dict) and entry.get("type") == "exception":
            values = (entry.get("data") or {}).get("values") or []
            return [v for v in values if isinstance(v, dict)]
    return []


def build_exception_list(
    entries: Any, platform: str, fallback_type: str | None, fallback_value: str | None
) -> list[dict[str, Any]]:
    values = _exception_entry_values(entries)
    if not values:
        # Message-only Sentry events still become issues; cymbal only requires `type`.
        return [{"type": fallback_type or "Message", "value": fallback_value or ""}]

    exception_list: list[dict[str, Any]] = []
    # Sentry orders the exception chain oldest-cause-first; PostHog displays [0] as the
    # primary exception, so reverse to put the outermost exception first.
    for value in reversed(values):
        exception: dict[str, Any] = {
            "type": value.get("type") or fallback_type or "Error",
            "value": value.get("value") or "",
        }
        if value.get("module"):
            exception["module"] = value["module"]
        mechanism = value.get("mechanism")
        if isinstance(mechanism, dict):
            exception["mechanism"] = {
                key: mechanism[key] for key in ("handled", "type", "synthetic") if key in mechanism
            }
        stacktrace = value.get("stacktrace")
        frames = (stacktrace or {}).get("frames") if isinstance(stacktrace, dict) else None
        if frames:
            exception["stacktrace"] = {
                "type": "raw",
                "frames": [
                    sentry_frame_to_custom_frame(frame, platform)
                    for frame in frames[-MAX_FRAMES:]
                    if isinstance(frame, dict)
                ],
            }
        exception_list.append(exception)
    return exception_list


def extract_distinct_id(user: Any, org_slug: str) -> str:
    parsed = _parse_json(user)
    if isinstance(parsed, dict):
        for key in ("email", "id", "username"):
            value = parsed.get(key)
            if value:
                return str(value)
    return f"sentry:{org_slug}:anonymous"


def extract_project_slug(row: dict[str, Any]) -> str | None:
    project = _parse_json(_get(row, "issue_project"))
    if isinstance(project, dict):
        slug = project.get("slug")
        return str(slug) if slug else None
    return None


def _sentry_tags(row: dict[str, Any]) -> dict[str, str]:
    tags = _parse_json(_get(row, "tags")) or []
    result: dict[str, str] = {}
    for tag in tags:
        if isinstance(tag, dict) and tag.get("key") is not None and tag.get("value") is not None:
            result[str(tag["key"])] = str(tag["value"])
    return result


def _base_properties(row: dict[str, Any], org_slug: str, import_job_id: str) -> dict[str, Any]:
    issue_id = str(_get(row, "issue_id"))
    platform = _get(row, "platform") or "unknown"
    properties: dict[str, Any] = {
        "$exception_list": build_exception_list(
            _get(row, "entries"),
            platform,
            _get(row, "issue_title", "title"),
            _get(row, "message"),
        ),
        "$exception_fingerprint": build_fingerprint(org_slug, issue_id),
        "$issue_name": _get(row, "issue_title"),
        "$issue_description": _get(row, "issue_culprit"),
        "$exception_level": _get(row, "issue_level", "level"),
        "$sentry_event_id": _get(row, "event_id", "eventID", "id"),
        "$sentry_issue_id": issue_id,
        "$sentry_short_id": _get(row, "issue_short_id"),
        "$sentry_url": _get(row, "issue_permalink"),
        "$sentry_event_count": _get(row, "issue_count"),
        "$sentry_user_count": _get(row, "issue_user_count"),
        "$lib": "posthog-sentry-import",
        "$import_source": "sentry",
        "$import_job_id": import_job_id,
    }
    project_slug = extract_project_slug(row)
    if project_slug:
        properties["$sentry_project"] = project_slug
    tags = _sentry_tags(row)
    if tags:
        properties["$sentry_tags"] = tags
    return {key: value for key, value in properties.items() if value is not None}


def sentry_event_to_capture_event(row: dict[str, Any], org_slug: str, import_job_id: str) -> dict[str, Any]:
    event_id = str(_get(row, "event_id", "eventID", "id"))
    return {
        "event": "$exception",
        "distinct_id": extract_distinct_id(_get(row, "user"), org_slug),
        "timestamp": _get(row, "date_created", "dateCreated"),
        "event_uuid": build_event_uuid(org_slug, event_id),
        "properties": _base_properties(row, org_slug, import_job_id),
        "options": {"disable_skew_correction": True},
    }


def build_first_seen_anchor_event(row: dict[str, Any], org_slug: str, import_job_id: str) -> dict[str, Any] | None:
    """One synthetic event at the issue's Sentry firstSeen so PostHog first_seen matches even
    when the real first event predates Sentry's retention window. Deterministic uuid makes
    re-emission across retries a no-op."""
    first_seen = _get(row, "issue_first_seen")
    event_timestamp = _get(row, "date_created", "dateCreated")
    if not first_seen or not event_timestamp or str(first_seen) >= str(event_timestamp):
        return None
    issue_id = str(_get(row, "issue_id"))
    event = sentry_event_to_capture_event(row, org_slug, import_job_id)
    event["timestamp"] = first_seen
    event["event_uuid"] = build_anchor_event_uuid(org_slug, issue_id)
    event["distinct_id"] = f"sentry:{org_slug}:anonymous"
    return event


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


class SentryMigrationAdapter:
    source_type = "sentry"
    external_source_type = "Sentry"
    schema_roles = {"issues": "issues", "events": "issue_events"}

    def validate_config(self, config: dict[str, Any]) -> str | None:
        if not config.get("org_slug"):
            return "A Sentry migration requires the organization slug in its config."
        return None

    def fingerprint_prefix(self, config: dict[str, Any]) -> str:
        return build_fingerprint(config["org_slug"], "")

    def issue_fingerprint(self, config: dict[str, Any], issue_key: str) -> str:
        return build_fingerprint(config["org_slug"], issue_key)

    def build_events_page_query(
        self, tables: dict[str, str], config: dict[str, Any], cursor: dict[str, Any] | None, page_size: int
    ) -> tuple[str, dict[str, ast.Expr]]:
        events = _validate_table(tables["events"])
        issues = _validate_table(tables["issues"])
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
        self, tables: dict[str, str], config: dict[str, Any]
    ) -> tuple[str, dict[str, ast.Expr]]:
        events = _validate_table(tables["events"])
        issues = _validate_table(tables["issues"])
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
        self, tables: dict[str, str], cursor: str | None, page_size: int
    ) -> tuple[str, dict[str, ast.Expr]]:
        issues = _validate_table(tables["issues"])
        placeholders: dict[str, ast.Expr] = {}
        where = ""
        if cursor:
            where = "WHERE toString(i.id) > {cursor_issue_id}"
            placeholders["cursor_issue_id"] = ast.Constant(value=str(cursor))
        query = (
            f"SELECT toString(i.id), i.status "
            f"FROM {issues} AS i "
            f"{where} "
            f"ORDER BY toString(i.id) ASC "
            f"LIMIT {int(page_size)}"
        )
        return query, placeholders

    def events_for_row(self, row: dict[str, Any], ctx: TransformContext) -> list[dict[str, Any]]:
        project_slugs = set(ctx.config.get("sentry_project_slugs") or [])
        if project_slugs:
            slug = extract_project_slug(row)
            if slug is not None and slug not in project_slugs:
                return []
        org_slug = ctx.config["org_slug"]
        events: list[dict[str, Any]] = []
        issue_id = str(_get(row, "issue_id"))
        if issue_id not in ctx.anchored_issue_ids:
            ctx.anchored_issue_ids.add(issue_id)
            anchor = build_first_seen_anchor_event(row, org_slug, ctx.import_job_id)
            if anchor is not None:
                events.append(anchor)
        events.append(sentry_event_to_capture_event(row, org_slug, ctx.import_job_id))
        return events

    def event_cursor(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "date_created": str(row.get("date_created")),
            "issue_id": str(row.get("issue_id")),
            "event_id": str(row.get("event_id")),
        }

    def map_status(self, raw_status: str | None) -> ErrorTrackingIssue.Status | None:
        return map_sentry_status(raw_status)
