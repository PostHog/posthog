"""Find which candidates, such as exceptions, have a log linked to them by trace or session ID."""

import base64
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta

from pydantic.dataclasses import dataclass as pydantic_dataclass

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut
from posthog.models import Team

from products.logs.backend.models import resolved_session_id_attribute_keys

# A log links to a candidate when it falls this close to the candidate's timestamp. The error tracking
# Logs tab shows the same window (EXCEPTION_LOGS_WINDOW_MINUTES in products/logs/frontend/utils.tsx),
# so a candidate counts as linked exactly when that tab has a log to show for it.
LINK_WINDOW = timedelta(minutes=5)
# Each ID is inlined into the query text, and each log row checks every candidate.
MAX_CANDIDATES_PER_QUERY = 500
# trace_id has no skip index, so a query reads every log of the team inside its windows. This caps
# the log time one query reads, and therefore its cost, whatever the team's log volume.
MAX_WINDOW_TIME_PER_QUERY = timedelta(hours=6)
QUERY_SETTINGS = HogQLGlobalSettings(
    max_execution_time=20, max_bytes_to_read=20_000_000_000, read_overflow_mode="throw"
)
_LOOKUP_ERRORS = (
    CHQueryErrorTooManyBytes,
    ClickHouseQueryTimeOut,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseAtCapacity,
)


@pydantic_dataclass(frozen=True, kw_only=True)
class LogLinkCandidate:
    """Something that can link to logs, such as an exception, identified by `key`."""

    key: str
    timestamp: datetime
    # Hex, as SDKs send it. The logs table stores the same bytes as base64.
    trace_id: str | None = None
    session_id: str | None = None


class LinkedLogsLookupError(Exception):
    """The logs lookup failed or ran out of its query budget, so the result is unknown."""


@frozen
class _Window:
    start: datetime
    end: datetime


def _trace_id_as_stored(trace_id: str | None) -> str | None:
    """The base64 form the logs table stores, or None for an unusable or all-zeros "no trace" ID."""
    if not trace_id:
        return None
    try:
        raw = bytes.fromhex(trace_id)
    except ValueError:
        return None
    if not raw or not any(raw):
        return None
    return base64.b64encode(raw).decode()


def _merged_windows(timestamps: Sequence[datetime]) -> list[_Window]:
    windows: list[_Window] = []
    for timestamp in sorted(timestamps):
        start, end = timestamp - LINK_WINDOW, timestamp + LINK_WINDOW
        if windows and start <= windows[-1].end:
            windows[-1] = _Window(start=windows[-1].start, end=max(windows[-1].end, end))
        else:
            windows.append(_Window(start=start, end=end))
    return windows


def _chunks(candidates: Sequence[LogLinkCandidate]) -> Iterator[list[LogLinkCandidate]]:
    """Split time-ordered candidates so each query stays under both caps."""
    chunk: list[LogLinkCandidate] = []
    window_time = timedelta()
    covered_until: datetime | None = None
    for candidate in sorted(candidates, key=lambda candidate: candidate.timestamp):
        start, end = candidate.timestamp - LINK_WINDOW, candidate.timestamp + LINK_WINDOW
        added = end - max(start, covered_until) if covered_until is not None else end - start
        added = max(added, timedelta())
        if chunk and (len(chunk) >= MAX_CANDIDATES_PER_QUERY or window_time + added > MAX_WINDOW_TIME_PER_QUERY):
            yield chunk
            chunk, window_time, covered_until = [], timedelta(), None
            added = end - start
        chunk.append(candidate)
        window_time += added
        covered_until = end if covered_until is None else max(covered_until, end)
    if chunk:
        yield chunk


def _call(name: str, *args: ast.Expr) -> ast.Call:
    return ast.Call(name=name, args=list(args))


def _field(*chain: str | int) -> ast.Field:
    return ast.Field(chain=list(chain))


def _session_values_expr(team: Team) -> ast.Array:
    # Every key the logs viewer reads a session from, in both maps. A bare arrayElement read keeps
    # the bucketed map serialization, as in the impact query runner. A missing key reads as ''.
    reads: list[ast.Expr] = []
    for key in resolved_session_id_attribute_keys(team):
        reads.append(_call("arrayElement", _field("attributes_map_str"), ast.Constant(value=f"{key}__str")))
        reads.append(_call("arrayElement", _field("resource_attributes"), ast.Constant(value=key)))
    return ast.Array(exprs=reads)


def _chunk_query(team: Team, chunk: Sequence[LogLinkCandidate]) -> ast.SelectQuery | None:
    traces = {candidate.key: _trace_id_as_stored(candidate.trace_id) for candidate in chunk}
    trace_ids = sorted({trace for trace in traces.values() if trace})
    session_ids = sorted({candidate.session_id for candidate in chunk if candidate.session_id})
    if not trace_ids and not session_ids:
        return None

    session_values = _session_values_expr(team)
    id_matches: list[ast.Expr] = []
    if trace_ids:
        id_matches.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=_field("trace_id"),
                right=ast.Tuple(exprs=[ast.Constant(value=trace) for trace in trace_ids]),
            )
        )
    if session_ids:
        id_matches.append(
            _call("hasAny", session_values, ast.Array(exprs=[ast.Constant(value=sid) for sid in session_ids]))
        )

    windows = _merged_windows([candidate.timestamp for candidate in chunk])
    window_matches: list[ast.Expr] = [
        ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq, left=_field("timestamp"), right=ast.Constant(value=window.start)
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq, left=_field("timestamp"), right=ast.Constant(value=window.end)
                ),
            ]
        )
        for window in windows
    ]

    # (key, stored trace ID or '', session ID or '', timestamp in ms). Each log row keeps the
    # candidates it matches by ID and falls within the link window of.
    candidate_tuples = ast.Array(
        exprs=[
            ast.Tuple(
                exprs=[
                    ast.Constant(value=candidate.key),
                    ast.Constant(value=traces[candidate.key] or ""),
                    ast.Constant(value=candidate.session_id or ""),
                    ast.Constant(value=int(candidate.timestamp.timestamp() * 1000)),
                ]
            )
            for candidate in chunk
        ]
    )
    window_ms = int(LINK_WINDOW.total_seconds() * 1000)
    candidate = _field("c")
    matches_candidate = ast.And(
        exprs=[
            ast.Or(
                exprs=[
                    ast.And(
                        exprs=[
                            _call("notEmpty", _call("tupleElement", candidate, ast.Constant(value=2))),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=_call("tupleElement", candidate, ast.Constant(value=2)),
                                right=_field("trace_id"),
                            ),
                        ]
                    ),
                    ast.And(
                        exprs=[
                            _call("notEmpty", _call("tupleElement", candidate, ast.Constant(value=3))),
                            _call("has", session_values, _call("tupleElement", candidate, ast.Constant(value=3))),
                        ]
                    ),
                ]
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=_call("toUnixTimestamp64Milli", _field("timestamp")),
                right=ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub,
                    left=_call("tupleElement", candidate, ast.Constant(value=4)),
                    right=ast.Constant(value=window_ms),
                ),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=_call("toUnixTimestamp64Milli", _field("timestamp")),
                right=ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Add,
                    left=_call("tupleElement", candidate, ast.Constant(value=4)),
                    right=ast.Constant(value=window_ms),
                ),
            ),
        ]
    )
    matched_keys = _call(
        "arrayMap",
        ast.Lambda(args=["c"], expr=_call("tupleElement", candidate, ast.Constant(value=1))),
        _call("arrayFilter", ast.Lambda(args=["c"], expr=matches_candidate), candidate_tuples),
    )

    return ast.SelectQuery(
        select=[ast.Alias(alias="key", expr=_call("arrayJoin", matched_keys))],
        select_from=ast.JoinExpr(table=_field("logs")),
        where=ast.And(
            exprs=[
                # time_bucket follows team_id in the sort key, so it prunes whole days before the minmax
                # index on timestamp. Both sides round in the same timezone, as in the logs query runner.
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=_call("toStartOfDay", _field("time_bucket")),
                    right=_call("toStartOfDay", ast.Constant(value=windows[0].start)),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=_call("toStartOfDay", _field("time_bucket")),
                    right=_call("toStartOfDay", ast.Constant(value=windows[-1].end)),
                ),
                ast.Or(exprs=window_matches) if len(window_matches) > 1 else window_matches[0],
                ast.Or(exprs=id_matches) if len(id_matches) > 1 else id_matches[0],
            ]
        ),
        group_by=[_field("key")],
        limit=ast.Constant(value=len(chunk)),
    )


def find_log_linked_keys(*, team: Team, candidates: Sequence[LogLinkCandidate]) -> frozenset[str]:
    """The keys of the candidates with a log that matches their trace or session ID within the link window."""
    linked: set[str] = set()
    for chunk in _chunks(candidates):
        query = _chunk_query(team, chunk)
        if query is None:
            continue
        try:
            response = execute_hogql_query(
                query=query,
                team=team,
                query_type="LinkedLogsLookup",
                workload=Workload.LOGS,
                settings=QUERY_SETTINGS,
            )
        except _LOOKUP_ERRORS as error:
            raise LinkedLogsLookupError() from error
        linked.update(str(row[0]) for row in response.results)
    return frozenset(linked)
