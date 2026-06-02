from __future__ import annotations

import json
from typing import cast

from posthog.hogql.escape_sql import escape_hogql_string

MAX_NORMALIZED_TEXT_CHARS = 1000

ISSUE_FIELDS = [
    "id",
    "name",
    "description",
    "status",
    "first_seen",
    "last_seen",
    "library",
    "source",
    "function",
    "assignee",
]

LIST_ISSUE_FIELDS = [
    "id",
    "name",
    "description",
    "status",
    "first_seen",
    "last_seen",
    "library",
    "source",
    "assignee",
    "aggregations",
]

CONTEXT_EVENT_SELECTS = ["properties.$exception_list", "properties.$exception_releases"]
EVENT_PROPERTY_SELECTS = [
    "properties.$exception_types",
    "properties.$exception_values",
    "properties.$exception_list",
    "properties.$exception_fingerprint",
    "properties.$exception_issue_id",
    "properties.$session_id",
    "properties.$lib",
    "properties.$browser",
    "properties.$browser_version",
    "properties.$os",
    "properties.$os_version",
    "properties.$current_url",
]
EVENT_SELECTS = ["uuid", "timestamp", "distinct_id", *EVENT_PROPERTY_SELECTS]
EVENT_SEARCH_PROPERTIES = ["properties.$exception_types", "properties.$exception_values", "properties.$current_url"]
PROPERTY_COLUMN_NAMES = {
    select.removeprefix("properties.") for select in [*CONTEXT_EVENT_SELECTS, *EVENT_PROPERTY_SELECTS]
}


def compact_dict(record: dict[str, object]) -> dict[str, object]:
    """Remove empty response fields while intentionally preserving 0 and false values."""
    return {
        key: value for key, value in record.items() if value is not None and value != [] and value != {} and value != ""
    }


def escape_hogql_like_pattern(value: str) -> str:
    pattern = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escape_hogql_string(f"%{pattern}%")


def as_list(value: str | list[str]) -> list[str]:
    return value if isinstance(value, list) else [value]


def build_date_range(raw_date_range: object) -> dict[str, object]:
    date_range: dict[str, object] = {"date_from": "-7d"}
    if isinstance(raw_date_range, dict):
        date_range.update({str(key): value for key, value in raw_date_range.items()})
    return date_range


def add_event_filter(filters: list[dict[str, object]], key: str, operator: str, value: str | list[str]) -> None:
    filters.append(
        {"type": "event", "key": key, "operator": operator, "value": as_list(value) if operator == "exact" else value}
    )


def add_release_filter(filters: list[dict[str, object]], release: str) -> None:
    escaped_release = escape_hogql_string(release)
    releases_json = "ifNull(nullIf(JSONExtractRaw(properties, '$exception_releases'), ''), '{}')"
    filters.append(
        {
            "type": "hogql",
            "key": f"position(toString(properties.$exception_releases), {escaped_release}) > 0",
        }
    )
    filters.append(
        {
            "type": "hogql",
            "key": (
                f"arrayExists(r -> (r.1 = {escaped_release} "
                f"OR JSONExtractString(r.2, 'version') = {escaped_release} "
                f"OR JSONExtractString(JSONExtractRaw(r.2, 'metadata'), 'git', 'commit_id') = {escaped_release}), "
                f"JSONExtractKeysAndValuesRaw({releases_json}))"
            ),
        }
    )


def build_issue_filters(params: dict[str, object]) -> list[dict[str, object]]:
    filters = [dict(item) for item in cast(list[dict[str, object]], params.get("filterGroup", []))]
    library = params.get("library")
    if isinstance(library, str | list):
        add_event_filter(filters, "$lib", "exact", cast(str | list[str], library))
    release = params.get("release")
    if isinstance(release, str):
        add_release_filter(filters, release)
    fingerprint = params.get("fingerprint")
    if isinstance(fingerprint, str | list):
        add_event_filter(filters, "$exception_fingerprint", "exact", cast(str | list[str], fingerprint))
    url = params.get("url")
    if isinstance(url, str):
        add_event_filter(filters, "$current_url", "icontains", url)
    return filters


def build_property_group(filters: list[dict[str, object]]) -> dict[str, object] | None:
    if not filters:
        return None
    return {"type": "AND", "values": [{"type": "AND", "values": filters}]}


def build_search_query(params: dict[str, object]) -> str | None:
    terms = [
        value.strip()
        for value in [params.get("searchQuery"), params.get("user"), params.get("filePath")]
        if isinstance(value, str) and value.strip()
    ]
    return " ".join(terms) if terms else None


def get_page_info(data: dict[str, object], limit: int, offset: int) -> tuple[bool, int | None]:
    results = data.get("results")
    row_count = len(results) if isinstance(results, list) else 0
    has_more = bool(data.get("hasMore")) or row_count > limit
    return has_more, offset + limit if has_more else None


def pick_fields(record: dict[str, object], fields: list[str]) -> dict[str, object]:
    return {field: record[field] for field in fields if field in record}


def to_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def parse_jsonish(value: object) -> object:
    parsed = value
    for _ in range(2):
        if not isinstance(parsed, str):
            return parsed
        trimmed = parsed.strip()
        if not trimmed or trimmed[0] not in {"[", "{", '"'}:
            return parsed
        try:
            parsed = json.loads(trimmed)
        except json.JSONDecodeError:
            return parsed
    return parsed


def truncate_text(value: object, verbosity: str) -> object:
    if verbosity == "raw" or not isinstance(value, str) or len(value) <= MAX_NORMALIZED_TEXT_CHARS:
        return value
    suffix = f"… [truncated from {len(value)} chars]"
    return f"{value[: MAX_NORMALIZED_TEXT_CHARS - len(suffix)]}{suffix}"


def as_record(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def strip_non_raw_fields(record: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in record.items() if key not in {"junk_drawer", "raw_id"}}


def normalize_frame(frame: object, verbosity: str, only_app_frames: bool) -> dict[str, object] | None:
    frame_record = as_record(parse_jsonish(frame))
    if frame_record is None:
        return None
    if only_app_frames and frame_record.get("in_app") is not True:
        return None
    base_frame = frame_record if verbosity == "raw" else strip_non_raw_fields(frame_record)
    normalized = {
        **base_frame,
        "mangled_name": frame_record.get("mangled_name") or frame_record.get("function") or frame_record.get("name"),
        "source": frame_record.get("source") or frame_record.get("filename") or frame_record.get("abs_path"),
        "line": frame_record.get("line") or frame_record.get("lineno"),
        "column": frame_record.get("column") or frame_record.get("colno"),
    }
    return compact_dict(normalized)


def normalize_stacktrace(stacktrace: object, verbosity: str, only_app_frames: bool) -> dict[str, object] | None:
    stacktrace_record = as_record(parse_jsonish(stacktrace))
    if stacktrace_record is None:
        return None
    raw_frames = stacktrace_record.get("frames")
    frames = (
        [
            normalized
            for frame in cast(list[object], raw_frames)
            if (normalized := normalize_frame(frame, verbosity, only_app_frames)) is not None
        ]
        if isinstance(raw_frames, list)
        else None
    )
    base_stacktrace = stacktrace_record if verbosity == "raw" else strip_non_raw_fields(stacktrace_record)
    return compact_dict({**base_stacktrace, "frames": frames})


def normalize_exception(exception: object, verbosity: str, only_app_frames: bool) -> dict[str, object] | None:
    exception_record = as_record(parse_jsonish(exception))
    if exception_record is None:
        return None
    summary = compact_dict(
        {
            "type": exception_record.get("type") or exception_record.get("exception_type"),
            "value": truncate_text(
                exception_record.get("value")
                or exception_record.get("message")
                or exception_record.get("exception_message"),
                verbosity,
            ),
            "module": exception_record.get("module"),
            "mechanism": exception_record.get("mechanism"),
        }
    )
    if verbosity == "summary":
        return summary
    stacktrace = normalize_stacktrace(exception_record.get("stacktrace"), verbosity, only_app_frames)
    if verbosity == "raw":
        return compact_dict({**exception_record, "stacktrace": stacktrace})
    return compact_dict({**summary, "stacktrace": stacktrace})


def normalize_exception_list(value: object, verbosity: str, only_app_frames: bool) -> object:
    parsed = parse_jsonish(value)
    record = as_record(parsed)
    exceptions = parsed if isinstance(parsed, list) else record.get("values") if record else None
    if not isinstance(exceptions, list):
        return parsed
    return [
        normalized
        for exception in exceptions
        if (normalized := normalize_exception(exception, verbosity, only_app_frames)) is not None
    ]


def normalize_string_array(value: object, verbosity: str = "summary", truncate_items: bool = False) -> object:
    parsed = parse_jsonish(value)
    if not isinstance(parsed, list):
        return parsed
    return [truncate_text(item, verbosity) for item in parsed] if truncate_items else parsed


def normalize_error_property(name: str, value: object, verbosity: str, only_app_frames: bool) -> object:
    if name == "$exception_list":
        return normalize_exception_list(value, verbosity, only_app_frames)
    if name == "$exception_releases":
        return parse_jsonish(value)
    if name == "$exception_types":
        return normalize_string_array(value)
    if name == "$exception_values":
        return normalize_string_array(value, verbosity, True)
    return value


def property_name(select: str) -> str | None:
    if select.startswith("properties."):
        return select.removeprefix("properties.")
    return select if select in PROPERTY_COLUMN_NAMES else None


def map_event_row(row: object, columns: list[str], verbosity: str, only_app_frames: bool) -> dict[str, object]:
    if isinstance(row, list):
        values = row
    else:
        record = as_record(row)
        values = [record.get(column) if record else None for column in columns]
    event: dict[str, object] = {"properties": {}}
    properties = cast(dict[str, object], event["properties"])
    for index, column in enumerate(columns):
        value = values[index] if isinstance(values, list) and index < len(values) else None
        if value is None:
            continue
        prop = property_name(column)
        if prop:
            properties[prop] = normalize_error_property(prop, value, verbosity, only_app_frames)
        else:
            event[column] = value
    return event


def map_context_event_properties(data: dict[str, object]) -> dict[str, object]:
    rows = data.get("results")
    row = rows[0] if isinstance(rows, list) and rows else None
    if row is None:
        return {}
    raw_columns = data.get("columns")
    columns = [str(column) for column in raw_columns] if isinstance(raw_columns, list) else CONTEXT_EVENT_SELECTS
    return cast(dict[str, object], map_event_row(row, columns, "stack", True)["properties"])


def get_frames(exception_list: object) -> list[dict[str, object]]:
    if not isinstance(exception_list, list):
        return []
    frames: list[dict[str, object]] = []
    for exception in exception_list:
        exception_record = as_record(exception)
        if exception_record is None:
            continue
        stacktrace = as_record(exception_record.get("stacktrace"))
        exception_frames = stacktrace.get("frames") if stacktrace else None
        if isinstance(exception_frames, list):
            frames.extend(frame for frame in exception_frames if isinstance(frame, dict))
    return frames


def get_frame_value(frame: dict[str, object], keys: list[str]) -> object:
    for key in keys:
        value = frame.get(key)
        if value is not None and value != "":
            return value
    return None


def build_top_in_app_frame(issue: dict[str, object], event_properties: dict[str, object]) -> dict[str, object]:
    top_frame = next(
        (
            frame
            for frame in reversed(get_frames(event_properties.get("$exception_list")))
            if frame.get("in_app") is True
        ),
        None,
    )
    if top_frame is None:
        return {}
    frame_function = get_frame_value(top_frame, ["function", "mangled_name", "name"])
    fallback_function = issue.get("function") if isinstance(issue.get("function"), str) else None
    function = frame_function if isinstance(frame_function, str) and frame_function != "?" else fallback_function
    frame_source = get_frame_value(top_frame, ["source", "filename", "abs_path", "module"])
    fallback_source = issue.get("source") if isinstance(issue.get("source"), str) else None
    return compact_dict(
        {
            "function": function,
            "source": frame_source or fallback_source,
            "line": get_frame_value(top_frame, ["line", "lineno"]),
            "column": get_frame_value(top_frame, ["column", "colno"]),
            "in_app": True,
        }
    )


def extract_latest_release(event_properties: dict[str, object]) -> dict[str, object]:
    releases = event_properties.get("$exception_releases")
    release_values = (
        releases if isinstance(releases, list) else list(releases.values()) if isinstance(releases, dict) else []
    )
    records = [record for value in release_values if (record := as_record(value)) is not None]
    records.sort(key=lambda record: str(record.get("timestamp") or record.get("created_at") or ""), reverse=True)
    release = records[0] if records else None
    if release is None:
        return {}
    metadata = as_record(release.get("metadata"))
    git = as_record(metadata.get("git") if metadata else None)
    return compact_dict(
        {
            "version": release.get("version"),
            "project": release.get("project"),
            "timestamp": release.get("timestamp") or release.get("created_at"),
            "commit_id": git.get("commit_id") if git else None,
            "branch": git.get("branch") if git else None,
            "repo_name": git.get("repo_name") if git else None,
        }
    )


def build_impact(issue: dict[str, object]) -> dict[str, object]:
    aggregations = as_record(issue.get("aggregations")) or {}
    return compact_dict(
        {
            "occurrences": to_number(aggregations.get("occurrences")),
            "users": to_number(aggregations.get("users")),
            "sessions": to_number(aggregations.get("sessions")),
        }
    )


def build_sparkline(issue: dict[str, object]) -> list[float] | None:
    aggregations = as_record(issue.get("aggregations")) or {}
    volume_range = aggregations.get("volumeRange")
    if isinstance(volume_range, list):
        numeric_values: list[float] = []
        for value in volume_range:
            numeric_value = to_number(value)
            if numeric_value is None:
                return None
            numeric_values.append(numeric_value)
        return numeric_values
    volume_buckets = aggregations.get("volume_buckets")
    if isinstance(volume_buckets, list):
        numeric_values = []
        for bucket in volume_buckets:
            record = as_record(bucket)
            if record is None:
                continue
            value = to_number(record.get("value"))
            if value is not None:
                numeric_values.append(value)
        return numeric_values or None
    return None


def build_issue_where(issue_id: str) -> list[str]:
    escaped_issue_id = escape_hogql_string(issue_id)
    return [f"(issue_id = {escaped_issue_id} OR properties.$exception_issue_id = {escaped_issue_id})"]


def build_fingerprint_where(fingerprints: list[str]) -> list[str]:
    if not fingerprints:
        return ["1 = 0"]
    escaped_fingerprints = ", ".join(escape_hogql_string(fingerprint) for fingerprint in fingerprints)
    return [f"properties.$exception_fingerprint IN ({escaped_fingerprints})"]


def build_event_where(issue_id: str, search_query: str | None) -> list[str]:
    where = build_issue_where(issue_id)
    return add_event_search_where(where, search_query)


def build_fingerprint_event_where(fingerprints: list[str], search_query: str | None) -> list[str]:
    where = build_fingerprint_where(fingerprints)
    return add_event_search_where(where, search_query)


def add_event_search_where(where: list[str], search_query: str | None) -> list[str]:
    if search_query:
        search = escape_hogql_like_pattern(search_query)
        chunks = [f"ilike(toString({prop}), {search})" for prop in EVENT_SEARCH_PROPERTIES]
        where.append(f"({' OR '.join(chunks)})")
    return where
