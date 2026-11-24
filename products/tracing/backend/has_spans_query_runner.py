import base64
import datetime as dt
from uuid import UUID

from django.core.cache import cache

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

HAS_SPANS_CACHE_TTL = int(dt.timedelta(days=7).total_seconds())


class HasSpansQueryRunner:
    def __init__(self, team: Team) -> None:
        self.team = team

    def run(self) -> bool:
        query = parse_select("SELECT 1 FROM posthog.trace_spans LIMIT 1")
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="HasSpansQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,
        )

        return len(response.results) > 0


def team_has_spans(team: Team) -> bool:
    cache_key = f"team:{team.id}:has_spans"
    if cache.get(cache_key) is True:
        return True

    has_spans = HasSpansQueryRunner(team).run()
    if has_spans:
        cache.set(cache_key, True, HAS_SPANS_CACHE_TTL)
    return has_spans


def otel_trace_id(trace_id: str) -> str | None:
    """The OpenTelemetry trace id a string stands for, as lowercase hex, or None when it stands for none.

    OTel ingestion writes the id as 32 hex characters, and the LLM gateway writes the same bytes as a hyphenated
    UUID. All zeros is OpenTelemetry's "no id" value.
    """
    try:
        value = UUID(trace_id)
    except ValueError:
        return None
    return value.hex if value.int else None


def find_stored_trace_id(team: Team, trace_id: str) -> str | None:
    """The hex id of the trace when the team stores a span of it, in any time range."""
    hex_id = otel_trace_id(trace_id)
    if hex_id is None:
        return None
    # The same shape as the subquery in `TraceSpansQueryRunner._unbounded_trace_filter`: it reads only what
    # `projection_index_team_trace_id` holds, so no date bound is needed.
    query = parse_select(
        "SELECT _part, _part_offset FROM posthog.trace_spans WHERE trace_id = {trace_id} LIMIT 1",
        placeholders={"trace_id": ast.Constant(value=base64.b64encode(bytes.fromhex(hex_id)).decode())},
    )
    response = execute_hogql_query(
        query_type="TracingStoredTraceIdQuery", query=query, team=team, workload=Workload.LOGS
    )
    return hex_id if response.results else None
