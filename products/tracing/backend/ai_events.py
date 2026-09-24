from datetime import datetime
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import Team

# A run rarely makes more than a few hundred model calls, and past this many rows the waterfall
# stops being readable, so the lookup does not page.
MAX_AI_EVENTS_PER_TRACE = 500

# The LLM analytics event kinds that carry a latency, so each one can be placed on the timeline.
AI_EVENT_KINDS = ["$ai_generation", "$ai_span", "$ai_embedding"]


@frozen
class TraceAiEvent:
    uuid: str
    event: str
    timestamp: datetime
    ai_trace_id: str
    ai_span_id: str | None
    ai_parent_id: str | None
    span_name: str | None
    latency_seconds: float | None
    model: str | None
    provider: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_cost_usd: float | None
    is_error: bool


def fetch_trace_ai_events(*, team: "Team", trace_id: str, date_from: datetime, date_to: datetime) -> list[TraceAiEvent]:
    """LLM analytics events whose `$ai_trace_id` is the OpenTelemetry trace id, inside the window,
    earliest first.

    Reads `ai_events`, whose sort key starts with `(team_id, trace_id)`, so a trace with no AI
    events costs a primary-key miss rather than a scan. That is why the lookup does not fall back
    to the shared events table: most APM traces have no AI events, and a fallback would scan the
    team's events on every one of them. Rows older than the ai_events retention are not found.
    """
    query = parse_select(
        """
        SELECT
            uuid,
            any(event) AS event_name,
            any(timestamp) AS ended_at,
            any(trace_id) AS ai_trace_id,
            any(span_id) AS ai_span_id,
            any(parent_id) AS ai_parent_id,
            any(span_name) AS span_name,
            any(latency) AS latency_seconds,
            any(model) AS model,
            any(provider) AS provider,
            any(input_tokens) AS input_tokens,
            any(output_tokens) AS output_tokens,
            any(total_cost_usd) AS total_cost_usd,
            any(is_error) AS is_error
        FROM posthog.ai_events
        WHERE trace_id = {trace_id}
          AND event IN {events}
          AND timestamp >= {date_from}
          AND timestamp <= {date_to}
        GROUP BY uuid
        ORDER BY ended_at ASC
        LIMIT {limit}
        """,
        placeholders={
            "events": ast.Constant(value=AI_EVENT_KINDS),
            # Spans read their ids back as uppercase hex, while OTel ingestion writes them
            # lowercase. Lowercasing the input, not the column, keeps the sort key usable.
            "trace_id": ast.Constant(value=trace_id.lower()),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            # Explicit, because HogQL caps a select without a LIMIT at 100 rows.
            "limit": ast.Constant(value=MAX_AI_EVENTS_PER_TRACE),
        },
    )
    response = execute_hogql_query(query=query, team=team, query_type="TracingTraceAiEventsQuery")
    # The SELECT aliases differ from the column names they aggregate, because an alias equal to
    # a column name shadows it in WHERE and ClickHouse then rejects the aggregate there.
    columns = [{"event_name": "event", "ended_at": "timestamp"}.get(c, c) for c in response.columns or []]
    return [TraceAiEvent(**dict(zip(columns, row))) for row in response.results or []]
