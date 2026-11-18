from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import Team, User

# A run rarely makes more than a few hundred model calls, and past this many rows the waterfall
# stops being readable, so the lookup does not page. A trace past the cap reports `has_more`, and
# the caller links to AI observability, which lists every event.
MAX_AI_EVENTS_PER_TRACE = 500

# The LLM analytics event kinds that carry a latency, so each one can be placed on the timeline.
AI_EVENT_KINDS = ["$ai_generation", "$ai_span", "$ai_embedding"]


# OTel ingestion stamps an event with the span's start, while the PostHog AI SDKs and the LLM
# gateway stamp it when the call finished. The source marker tells the two apart.
OTEL_INGESTION_SOURCE = "otel"

# `$ai_latency` is sender-controlled. Past this a value is junk rather than a slow call.
MAX_LATENCY_SECONDS = 7 * 24 * 60 * 60


@frozen
class TraceAiEvent:
    uuid: str
    event: str
    started_at: datetime
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


@frozen
class TraceAiEvents:
    events: list[TraceAiEvent]
    has_more: bool


def fetch_trace_ai_events(*, team: "Team", user: "User | None", trace_id: str) -> TraceAiEvents:
    """LLM analytics events whose `$ai_trace_id` is the OpenTelemetry trace id, earliest start
    first, capped at `MAX_AI_EVENTS_PER_TRACE`. Matches the 32-hex form OTel ingestion writes and the hyphenated UUID form the LLM
    gateway writes for a `traceparent` header.

    Reads `ai_events`, whose sort key starts with `(team_id, trace_id)`, so a trace with no AI
    events costs a primary-key miss rather than a scan. That is why the lookup does not fall back
    to the shared events table: most APM traces have no AI events, and a fallback would scan the
    team's events on every one of them. There is no time window: the trace id already bounds the
    read, and the table partitions by retention date rather than event time, so a window prunes
    nothing. Rows older than the ai_events retention are not found.

    The requesting user is passed through so property access rules mask restricted AI columns for
    that user rather than falling back to the team default.
    """
    # `$ai_latency` is sender-controlled, so the same guard that keeps a junk value out of the
    # response keeps it out of the start-time arithmetic. The start is computed in the query
    # because the order and the row cap have to follow it, not the stamped time.
    query = parse_select(
        """
        SELECT
            uuid,
            any(event) AS event_name,
            any(trace_id) AS ai_trace_id,
            any(span_id) AS ai_span_id,
            any(parent_id) AS ai_parent_id,
            any(span_name) AS span_name,
            any(if(isFinite(latency) AND latency >= 0 AND latency <= {max_latency}, latency, NULL)) AS latency_seconds,
            any(model) AS model,
            any(provider) AS provider,
            any(input_tokens) AS input_tokens,
            any(output_tokens) AS output_tokens,
            any(total_cost_usd) AS total_cost_usd,
            any(is_error) AS is_error,
            any(if(
                properties.$ai_ingestion_source = {otel_source} OR isNull(latency) OR NOT isFinite(latency) OR latency < 0 OR latency > {max_latency},
                timestamp,
                fromUnixTimestamp64Milli(toUnixTimestamp64Milli(timestamp) - toInt(latency * 1000))
            )) AS started_at
        FROM posthog.ai_events
        WHERE trace_id IN {trace_ids}
          AND event IN {events}
        GROUP BY uuid
        ORDER BY started_at ASC
        LIMIT {limit}
        """,
        placeholders={
            "events": ast.Constant(value=AI_EVENT_KINDS),
            # Spans read their ids back as uppercase hex, while OTel ingestion writes them
            # lowercase. Both forms are constants, so the lookup stays on the sort key.
            "trace_ids": ast.Constant(value=_stored_trace_id_forms(trace_id)),
            "otel_source": ast.Constant(value=OTEL_INGESTION_SOURCE),
            "max_latency": ast.Constant(value=MAX_LATENCY_SECONDS),
            # Explicit, because HogQL caps a select without a LIMIT at 100 rows. One row past the
            # cap tells a full trace from a truncated one.
            "limit": ast.Constant(value=MAX_AI_EVENTS_PER_TRACE + 1),
        },
    )
    response = execute_hogql_query(query=query, team=team, user=user, query_type="TracingTraceAiEventsQuery")
    # The event alias differs from the column it aggregates, because an alias equal to a column
    # name shadows it in WHERE and ClickHouse then rejects the aggregate there.
    columns = [{"event_name": "event"}.get(c, c) for c in response.columns or []]
    rows = response.results or []
    return TraceAiEvents(
        events=[TraceAiEvent(**dict(zip(columns, row))) for row in rows[:MAX_AI_EVENTS_PER_TRACE]],
        has_more=len(rows) > MAX_AI_EVENTS_PER_TRACE,
    )


def _stored_trace_id_forms(trace_id: str) -> list[str]:
    hex_form = trace_id.lower()
    try:
        return [hex_form, str(UUID(hex=hex_form))]
    except ValueError:
        return [hex_form]
