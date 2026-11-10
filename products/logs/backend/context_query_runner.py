import re
import json
import base64
import datetime as dt
from typing import TYPE_CHECKING, Literal

from posthog.schema import HogQLQueryModifiers, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseQueryTimeOut

from products.logs.backend.agent_window import utc_iso, window_echo
from products.logs.backend.logs_query_runner import fail_fast_aggregate_settings

if TYPE_CHECKING:
    from posthog.models import Team

BODY_MAX_CHARS = 300
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
_DEFAULT_PADDING = {
    "trace": dt.timedelta(seconds=30),
    "log": dt.timedelta(minutes=5),
    "attribute": dt.timedelta(minutes=5),
}
_MAX_PADDING = dt.timedelta(hours=6)
_LOOKUP_SLACK = dt.timedelta(minutes=1)
_MAX_CORRELATION_KEYS = 10
_TRACE_SPAN_LIMIT = 2000
_SPAN_SQL = (
    "SELECT lower(hex(tryBase64Decode(span_id))), lower(hex(tryBase64Decode(parent_span_id))), name, service_name, "
    "status_code, timestamp, end_time, duration_nano, is_root_span FROM posthog.trace_spans WHERE {where} "
    "ORDER BY timestamp ASC LIMIT {limit}"
)
_MAX_ATTRS_PER_ROW = 8
_PADDING_RE = re.compile(r"^(\d+)([smh])$")
_ID_LIKE_RE = re.compile(r"(^|[._])(id|uuid)$|[a-z](Id|ID)$|^(run|request)")
_NOISE_KEYS = frozenset(
    "time ts timestamp @timestamp level severity msg message logtag logger caller service.name".split()
)
_NOISE_PREFIXES = ("log.file.", "log.iostream", "code.", "thread.", "process.", "trace_", "span_", "otel")
_ROW_SQL = (
    "SELECT uuid, timestamp, service_name, severity_text, substringUTF8(body, 1, 301), attributes, "
    "lower(hex(tryBase64Decode(trace_id))) FROM logs WHERE {where}"
)


class LogsContextError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@frozen
class LogsContextParams:
    kind: Literal["trace", "log", "attribute"]
    trace_id: str | None = None
    log_uuid: str | None = None
    attribute: tuple[str, str] | None = None
    time_hint: dt.datetime | None = None
    padding: dt.timedelta | None = None
    severity_levels: tuple[str, ...] = ()
    service_names: tuple[str, ...] = ()
    include_spans: bool = False
    read_spans: bool = True
    limit: int = DEFAULT_LIMIT
    after: str | None = None


def parse_padding(raw: str) -> dt.timedelta:
    match = _PADDING_RE.match(raw or "")
    if match is None:
        raise ValueError('padding must look like "30s", "5m" or "1h"')
    seconds = int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    if seconds > _MAX_PADDING.total_seconds():
        raise ValueError("padding can be at most 6h")
    return dt.timedelta(seconds=seconds)


def normalize_trace_id(raw: str) -> str:
    value = raw.strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", value):
        return value.lower()
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError:
        decoded = b""
    if len(decoded) != 16:
        raise ValueError("traceId must be 32 hex characters or the base64 form of 16 bytes")
    return decoded.hex()


def is_id_like_key(key: str) -> bool:
    return bool(_ID_LIKE_RE.search(key))


def differing_attrs(row: dict[str, str], anchor: dict[str, str]) -> str:
    pairs = [
        f"{key}={_cut(row[key], 120)}"
        for key in sorted(row)
        if key not in _NOISE_KEYS and not key.startswith(_NOISE_PREFIXES) and anchor.get(key) != row[key]
    ]
    return " ".join(pairs[:_MAX_ATTRS_PER_ROW])


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def _ms(delta: dt.timedelta) -> float:
    return round(delta.total_seconds() * 1000, 1)


def _trace_equals(hex_trace_id: str) -> ast.Expr:
    stored = base64.b64encode(bytes.fromhex(hex_trace_id)).decode()
    return parse_expr("trace_id = {trace_id}", placeholders={"trace_id": ast.Constant(value=stored)})


def _attribute_equals(key: str, value: str) -> ast.Expr:
    return parse_expr(
        "attributes_map_str[{key}] = {value}",
        placeholders={"key": ast.Constant(value=f"{key}__str"), "value": ast.Constant(value=value)},
    )


def _window_exprs(window: tuple[dt.datetime, dt.datetime]) -> list[ast.Expr]:
    bounds: dict[str, ast.Expr] = {"date_from": ast.Constant(value=window[0]), "date_to": ast.Constant(value=window[1])}
    return [
        parse_expr(
            "toStartOfDay(time_bucket, 'UTC') >= toStartOfDay({date_from}, 'UTC') "
            "AND toStartOfDay(time_bucket, 'UTC') <= toStartOfDay({date_to}, 'UTC')",
            placeholders=bounds,
        ),
        parse_expr("timestamp >= {date_from} AND timestamp < {date_to}", placeholders=bounds),
    ]


def self_time_nano(
    start: dt.datetime, end: dt.datetime, duration_nano: int, children: list[tuple[dt.datetime, dt.datetime]]
) -> int:
    covered = dt.timedelta(0)
    cursor = start
    for child_start, child_end in sorted((max(a, start), min(b, end)) for a, b in children if a < end and b > start):
        child_start = max(child_start, cursor)
        if child_end > child_start:
            covered += child_end - child_start
            cursor = child_end
    return max(duration_nano - covered // dt.timedelta(microseconds=1) * 1000, 0)


@frozen
class _Span:
    span_id: str
    parent_span_id: str
    name: str
    service_name: str
    status_code: int
    start: dt.datetime
    end: dt.datetime
    duration_nano: int
    self_time_nano: int
    is_root_span: bool


@frozen
class _Trace:
    start: dt.datetime
    end: dt.datetime
    services: tuple[str, ...]
    spans: tuple[_Span, ...]
    truncated: bool


class LogsContextRunner:
    def __init__(self, team: "Team", params: LogsContextParams) -> None:
        self.team = team
        self.params = params
        self.notes: list[str] = []

    def run(self) -> dict:
        params = self.params
        padding = _DEFAULT_PADDING[params.kind] if params.padding is None else params.padding
        services = list(params.service_names)
        anchor_row: dict | None = None
        trace = self._read_trace(params.trace_id) if params.trace_id and params.read_spans else None
        if trace is not None:
            window = (_utc(trace.start) - padding, _utc(trace.end) + padding)
            if not services:
                services = list(trace.services)
                self.notes.append(f"Logs are limited to the {len(services)} services with spans in the trace.")
            if trace.truncated:
                self.notes.append("The trace has more spans than were read, so its end time can be early.")
        elif params.time_hint is None:
            raise LogsContextError(
                "anchor.around is required: the trace has no spans to take a time range from. "
                "Pass an ISO 8601 time near the trace so the logs can be read without a full scan."
            )
        else:
            center = _utc(params.time_hint)
            if params.kind == "log":
                anchor_row = self._lookup_log(center)
                center = anchor_row["timestamp"]
                services = services or [anchor_row["service"]]
            elif params.kind == "trace":
                self.notes.append("The trace has no spans, so the window comes from anchor.around.")
            window = (center - padding, center + padding)

        rows, truncated = self._timeline(window, services)
        anchor_row = anchor_row or (rows[0] if rows else None)
        reference = _utc(trace.start) if trace else anchor_row["timestamp"] if anchor_row else window[0] + padding
        matched = [anchor_row] if params.kind == "log" and anchor_row else rows
        start, end = (
            (trace.start, trace.end)
            if trace
            else (matched[0]["timestamp"], matched[-1]["timestamp"])
            if matched
            else (None, None)
        )
        correlation_keys = self._correlation_keys(anchor_row, window)
        return {
            "window": window_echo(window),
            "anchor": {
                "type": params.kind,
                "trace_id": params.trace_id or (anchor_row or {}).get("trace_id") or None,
                "timestamp": utc_iso(reference),
                "start": utc_iso(start) if start else None,
                "end": utc_iso(end) if end else None,
                "duration_ms": _ms(end - start) if start and end else None,
                "services": list(trace.services) if trace else sorted({row["service"] for row in matched}),
            },
            "correlation_keys": correlation_keys,
            "timeline": [
                {
                    "t_offset_ms": _ms(row["timestamp"] - reference),
                    "timestamp": utc_iso(row["timestamp"]),
                    "service": row["service"],
                    "severity": row["severity"],
                    "body": _cut(row["body"], BODY_MAX_CHARS),
                    "attrs": differing_attrs(row["attributes"], (anchor_row or {}).get("attributes", {})),
                    "uuid": row["uuid"],
                }
                for row in rows
            ],
            "spans_summary": _spans_summary(trace) if params.include_spans and trace else None,
            "truncated": truncated,
            "next_cursor": _cursor(rows[-1]) if truncated else None,
            "next": self._next_calls(anchor_row, correlation_keys, trace),
            "notes": self.notes,
        }

    def _read_trace(self, trace_id: str) -> "_Trace | None":
        limit = ast.Constant(value=_TRACE_SPAN_LIMIT + 1)
        stored = ast.Constant(value=base64.b64encode(bytes.fromhex(trace_id)).decode())
        where = parse_expr(
            "trace_id = {id} AND (_part, _part_offset) IN "
            "(SELECT _part, _part_offset FROM posthog.trace_spans WHERE trace_id = {id})",
            placeholders={"id": stored},
        )
        rows = self._execute(_SPAN_SQL, {"where": where, "limit": limit})
        if not rows:
            return None
        children: dict[str, list[tuple[dt.datetime, dt.datetime]]] = {}
        for row in rows[:_TRACE_SPAN_LIMIT]:
            children.setdefault(row[1], []).append((row[5], row[6]))
        spans = tuple(
            _Span(
                span_id=row[0],
                parent_span_id=row[1],
                name=row[2],
                service_name=row[3],
                status_code=int(row[4]),
                start=row[5],
                end=row[6],
                duration_nano=int(row[7]),
                self_time_nano=self_time_nano(row[5], row[6], int(row[7]), children.get(row[0], [])),
                is_root_span=bool(row[8]),
            )
            for row in rows[:_TRACE_SPAN_LIMIT]
        )
        return _Trace(
            start=min(span.start for span in spans),
            end=max(span.end for span in spans),
            services=tuple(sorted({span.service_name for span in spans if span.service_name})),
            spans=spans,
            truncated=len(rows) > _TRACE_SPAN_LIMIT,
        )

    def _execute(self, sql: str, placeholders: dict[str, ast.Expr]) -> list:
        return execute_hogql_query(
            query_type="LogsContextQuery",
            query=parse_select(sql, placeholders=placeholders),
            team=self.team,
            workload=Workload.LOGS,
            modifiers=HogQLQueryModifiers(
                convertToProjectTimezone=False, propertyGroupsMode=PropertyGroupsMode.OPTIMIZED
            ),
            settings=fail_fast_aggregate_settings(),
        ).results

    def _rows(self, where: list[ast.Expr], suffix: str = "", limit: int = 1) -> list[dict]:
        results = self._execute(
            f"{_ROW_SQL} {suffix} LIMIT {{limit}}", {"where": ast.And(exprs=where), "limit": ast.Constant(value=limit)}
        )
        keys = ("uuid", "timestamp", "service", "severity", "body", "attributes", "trace_id")
        return [{**dict(zip(keys, row)), "timestamp": _utc(row[1]), "attributes": dict(row[5])} for row in results]

    def _lookup_log(self, timestamp: dt.datetime) -> dict:
        uuid = parse_expr("uuid = {uuid}", placeholders={"uuid": ast.Constant(value=self.params.log_uuid)})
        rows = self._rows([*_window_exprs((timestamp - _LOOKUP_SLACK, timestamp + _LOOKUP_SLACK)), uuid])
        if not rows:
            raise LogsContextError(
                f"No log with uuid {self.params.log_uuid} within 1 minute of {utc_iso(timestamp)}. "
                "anchor.timestamp must be the log's own timestamp.",
                status=404,
            )
        return rows[0]

    def _timeline(self, window: tuple[dt.datetime, dt.datetime], services: list[str]) -> tuple[list[dict], bool]:
        params = self.params
        where = _window_exprs(window)
        if params.trace_id:
            where.append(_trace_equals(params.trace_id))
        if params.attribute:
            where.append(_attribute_equals(*params.attribute))
        if services:
            where.append(parse_expr("service_name IN {values}", placeholders={"values": ast.Constant(value=services)}))
        if params.severity_levels:
            levels = ast.Constant(value=list(params.severity_levels))
            where.append(parse_expr("severity_text IN {values}", placeholders={"values": levels}))
        if params.after:
            try:
                cursor = json.loads(base64.b64decode(params.after))
                after: dict[str, ast.Expr] = {
                    "ts": ast.Constant(value=_utc(dt.datetime.fromisoformat(cursor["timestamp"]))),
                    "id": ast.Constant(value=str(cursor["uuid"])),
                }
            except (KeyError, TypeError, ValueError) as error:
                raise LogsContextError("after: invalid cursor. Pass next_cursor from a previous call.") from error
            where.append(parse_expr("timestamp >= {ts} AND (timestamp, uuid) > ({ts}, {id})", placeholders=after))
        rows = self._rows(where, "ORDER BY timestamp ASC, uuid ASC", params.limit + 1)
        return rows[: params.limit], len(rows) > params.limit

    def _correlation_keys(self, anchor_row: dict | None, window: tuple[dt.datetime, dt.datetime]) -> list[dict]:
        if anchor_row is None:
            return []
        pairs = [("trace_id", anchor_row["trace_id"])] if anchor_row["trace_id"] else []
        pairs += [
            (key, value)
            for key, value in sorted(anchor_row["attributes"].items())
            if value and is_id_like_key(key) and not key.startswith(("trace_", "span_"))
        ]
        pairs = pairs[:_MAX_CORRELATION_KEYS]
        if not pairs:
            return []
        matches = [_trace_equals(value) if key == "trace_id" else _attribute_equals(key, value) for key, value in pairs]
        placeholders: dict[str, ast.Expr] = {f"match_{i}": expr for i, expr in enumerate(matches)}
        placeholders["where"] = ast.And(exprs=[*_window_exprs(window), ast.Or(exprs=matches)])
        counts = ", ".join(f"countIf({{match_{i}}})" for i in range(len(matches)))
        try:
            row = self._execute(f"SELECT {counts} FROM logs WHERE {{where}}", placeholders)[0]
        except (CHQueryErrorTooManyBytes, ClickHouseQueryTimeOut):
            self.notes.append("Counting logs per correlation key hit the read budget, so correlation_keys is empty.")
            return []
        return [{"key": key, "value": value, "log_count": int(count)} for (key, value), count in zip(pairs, row)]

    def _next_calls(self, anchor_row: dict | None, correlation_keys: list[dict], trace: _Trace | None) -> list[dict]:
        calls: list[tuple[str, dict]] = []
        if trace is not None and not self.params.include_spans:
            calls.append(("the trace's root, error and slowest spans", {"traceId": self.params.trace_id}))
        if anchor_row and anchor_row["trace_id"] and not self.params.trace_id:
            around = utc_iso(anchor_row["timestamp"])
            calls.append(("every log of the anchor's trace", {"traceId": anchor_row["trace_id"], "around": around}))
        skip = {"trace_id", self.params.attribute[0] if self.params.attribute else None}
        for key in correlation_keys:
            if anchor_row and key["key"] not in skip and key["log_count"] > 1:
                attribute = {"key": key["key"], "value": key["value"]}
                anchor = {"attribute": attribute, "around": utc_iso(anchor_row["timestamp"])}
                calls.append((f"all {key['log_count']} logs with {key['key']}={_cut(key['value'], 40)}", anchor))
        return [
            {
                "tool": "logs-context",
                "why": why,
                "query": {"anchor": anchor, **({"include": ["spans"]} if "traceId" in anchor else {})},
            }
            for why, anchor in calls[:3]
        ]


def _cursor(row: dict) -> str:
    return base64.b64encode(
        json.dumps({"timestamp": row["timestamp"].isoformat(), "uuid": row["uuid"]}).encode()
    ).decode()


def _spans_summary(trace: _Trace) -> dict:
    def summary(span: _Span) -> dict:
        return {
            "span_id": span.span_id,
            "name": span.name,
            "service": span.service_name,
            "start_offset_ms": _ms(_utc(span.start) - _utc(trace.start)),
            "duration_ms": round(span.duration_nano / 1e6, 1),
            "self_time_ms": round(span.self_time_nano / 1e6, 1),
            "status": "error" if span.status_code == 2 else "ok",
        }

    root = next((span for span in trace.spans if span.is_root_span), None)
    return {
        "span_count": len(trace.spans),
        "truncated": trace.truncated,
        "services": list(trace.services),
        "root": summary(root) if root else None,
        "error_spans": [summary(span) for span in trace.spans if span.status_code == 2][:10],
        "slowest": [summary(span) for span in sorted(trace.spans, key=lambda span: -span.duration_nano)[:5]],
    }
