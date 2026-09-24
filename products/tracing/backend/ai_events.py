from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import Team, User

# A run rarely makes more than a few hundred model calls, and past this many rows the waterfall
# stops being readable, so the lookup does not page.
MAX_AI_EVENTS_PER_TRACE = 500

# The LLM analytics event kinds that carry a latency, so each one can be placed on the timeline.
AI_EVENT_KINDS = ["$ai_generation", "$ai_span", "$ai_embedding"]


# OTel ingestion stamps an event with the span's start, while the PostHog AI SDKs and the LLM
# gateway stamp it when the call finished. The source marker tells the two apart.
OTEL_INGESTION_SOURCE = "otel"


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


def fetch_trace_ai_events(
    *, team: "Team", user: "User | None", trace_id: str, date_from: datetime, date_to: datetime
) -> list[TraceAiEvent]:
    """LLM analytics events whose `$ai_trace_id` is the OpenTelemetry trace id, inside the window,
    earliest first. Matches the 32-hex form OTel ingestion writes and the hyphenated UUID form the
    LLM gateway writes for a `traceparent` header.

    Reads `ai_events`, whose sort key starts with `(team_id, trace_id)`, so a trace with no AI
    events costs a primary-key miss rather than a scan. That is why the lookup does not fall back
    to the shared events table: most APM traces have no AI events, and a fallback would scan the
    team's events on every one of them. Rows older than the ai_events retention are not found.

    The requesting user is passed through so property access rules mask restricted AI columns for
    that user rather than falling back to the team default.
    """
    query = parse_select(
        """
        SELECT
            uuid,
            any(event) AS event_name,
            any(timestamp) AS stamped_at,
            any(properties.$ai_ingestion_source) AS ingestion_source,
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
        WHERE trace_id IN {trace_ids}
          AND event IN {events}
          AND timestamp >= {date_from}
          AND timestamp <= {date_to}
        GROUP BY uuid
        ORDER BY stamped_at ASC
        LIMIT {limit}
        """,
        placeholders={
            "events": ast.Constant(value=AI_EVENT_KINDS),
            # Spans read their ids back as uppercase hex, while OTel ingestion writes them
            # lowercase. Both forms are constants, so the lookup stays on the sort key.
            "trace_ids": ast.Constant(value=_stored_trace_id_forms(trace_id)),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            # Explicit, because HogQL caps a select without a LIMIT at 100 rows.
            "limit": ast.Constant(value=MAX_AI_EVENTS_PER_TRACE),
        },
    )
    response = execute_hogql_query(query=query, team=team, user=user, query_type="TracingTraceAiEventsQuery")
    # The SELECT aliases differ from the column names they aggregate, because an alias equal to
    # a column name shadows it in WHERE and ClickHouse then rejects the aggregate there.
    columns = [{"event_name": "event"}.get(c, c) for c in response.columns or []]
    return [_to_trace_ai_event(dict(zip(columns, row))) for row in response.results or []]


def _stored_trace_id_forms(trace_id: str) -> list[str]:
    hex_form = trace_id.lower()
    try:
        return [hex_form, str(UUID(hex=hex_form))]
    except ValueError:
        return [hex_form]


def _to_trace_ai_event(row: dict) -> TraceAiEvent:
    stamped_at: datetime = row.pop("stamped_at")
    ingestion_source = row.pop("ingestion_source")
    latency = row.get("latency_seconds") or 0
    started_at = stamped_at if ingestion_source == OTEL_INGESTION_SOURCE else stamped_at - timedelta(seconds=latency)
    return TraceAiEvent(started_at=started_at, **row)
