"""LLM analytics Conversations API.

Two endpoints:

* `GET /api/environments/{project_id}/llm_analytics/conversations/`
  Returns a list of conversations grouped by `$ai_session_id`. With
  `include_orphan_traces=true`, single-trace conversations without a session
  id are also returned (typed as `kind=trace`).

* `GET /api/environments/{project_id}/llm_analytics/conversations/{pk}/?kind=session|trace`
  Returns a flat chat transcript for one conversation: per-turn user and
  assistant messages, with the prior conversation history deduped so the
  reader sees what the end user actually saw.

Heavy raw-event payloads (full `$ai_input`, span tree, tool calls) are not
re-served here — the existing `TraceQuery` endpoint backs the
"Show reasoning" expand client-side.
"""

# `def list(...)` below shadows the builtin `list` inside the class namespace,
# so subsequent return annotations like `list[LLMTrace]` evaluate against the
# method object and raise `TypeError: 'function' object is not subscriptable`.
# PEP 563 string-form evaluation defers annotation lookup to runtime where
# `list` resolves to the builtin again.
from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import CachedTracesQueryResponse, DateRange, HogQLFilters, LLMTrace, TraceQuery, TracesQuery

from posthog.hogql.constants import LimitContext
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.ai.trace_query_runner import TraceQueryRunner
from posthog.hogql_queries.ai.traces_query_runner import TracesQueryRunner
from posthog.permissions import AccessControlPermission

logger = structlog.get_logger(__name__)

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
# Max concurrent TraceQueryRunner calls when materializing a session's full event payloads.
# Each call is one ClickHouse round-trip; capping protects ClickHouse from a long agent
# transcript fanning out into dozens of simultaneous queries.
TRACE_FETCH_CONCURRENCY = 6

# ---------------------------------------------------------------------------
# SQL templates
# ---------------------------------------------------------------------------
#
# Why we hand-roll JSON access instead of using HogQL's `properties.$ai_input`:
# HogQL wraps property access in `nullIf(...)` so the result is `Nullable(String)`.
# Calling `JSONExtractArrayRaw` on a Nullable(String) yields `Nullable(Array(String))`,
# which ClickHouse rejects (`CHQueryErrorIllegalTypeOfArgument`). Reading via
# `JSONExtractString(properties, '$ai_input')` returns plain `String`, which is
# safe to feed into `JSONExtractArrayRaw`.

_SESSIONS_SQL = """
SELECT
    'session' AS kind,
    session_id AS id,
    any(first_user_message) AS title,
    count() AS turns,
    any(any_distinct_id) AS distinct_id,
    round(sum(trace_cost), 4) AS total_cost,
    min(first_seen) AS first_seen,
    max(last_seen) AS last_seen
FROM (
    SELECT
        anyIf(
            properties.$ai_session_id,
            isNotNull(properties.$ai_session_id) AND properties.$ai_session_id != ''
        ) AS session_id,
        any(distinct_id) AS any_distinct_id,
        sumIf(
            toFloat(properties.$ai_total_cost_usd),
            event IN ('$ai_generation', '$ai_embedding')
        ) AS trace_cost,
        min(timestamp) AS first_seen,
        max(timestamp) AS last_seen,
        argMinIf(
            JSONExtractString(
                arrayFilter(
                    x -> JSONExtractString(x, 'role') = 'user',
                    JSONExtractArrayRaw(JSONExtractString(properties, '$ai_input'))
                )[1],
                'content'
            ),
            timestamp,
            event = '$ai_generation' AND JSONExtractString(properties, '$ai_input') != ''
        ) AS first_user_message
    FROM events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace')
        AND isNotNull(properties.$ai_trace_id)
        AND properties.$ai_trace_id != ''
        AND {filters}
    GROUP BY properties.$ai_trace_id
    HAVING session_id != '' AND isNotNull(session_id)
)
GROUP BY session_id
ORDER BY last_seen DESC
LIMIT {limit}
"""

_ORPHANS_SQL = """
SELECT
    'trace' AS kind,
    trace_id AS id,
    title,
    1 AS turns,
    distinct_id,
    round(trace_cost, 4) AS total_cost,
    first_seen,
    last_seen
FROM (
    SELECT
        properties.$ai_trace_id AS trace_id,
        any(distinct_id) AS distinct_id,
        sumIf(
            toFloat(properties.$ai_total_cost_usd),
            event IN ('$ai_generation', '$ai_embedding')
        ) AS trace_cost,
        min(timestamp) AS first_seen,
        max(timestamp) AS last_seen,
        anyIf(
            properties.$ai_session_id,
            isNotNull(properties.$ai_session_id) AND properties.$ai_session_id != ''
        ) AS session_id,
        argMinIf(
            JSONExtractString(
                arrayFilter(
                    x -> JSONExtractString(x, 'role') = 'user',
                    JSONExtractArrayRaw(JSONExtractString(properties, '$ai_input'))
                )[1],
                'content'
            ),
            timestamp,
            event = '$ai_generation' AND JSONExtractString(properties, '$ai_input') != ''
        ) AS title
    FROM events
    WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace')
        AND isNotNull(properties.$ai_trace_id)
        AND properties.$ai_trace_id != ''
        AND {filters}
    GROUP BY properties.$ai_trace_id
    HAVING session_id = '' OR isNull(session_id)
)
ORDER BY last_seen DESC
LIMIT {limit}
"""


def _build_list_sql(include_orphan_traces: bool, limit: int) -> str:
    sessions_part = _SESSIONS_SQL.replace("{limit}", str(limit))
    if not include_orphan_traces:
        return sessions_part
    orphans_part = _ORPHANS_SQL.replace("{limit}", str(limit))
    # Two limited subqueries unioned together: the user sees up to `limit` rows
    # of each kind, then the outer query re-sorts and re-limits to the global cap.
    return f"""
SELECT * FROM (
{sessions_part}
)
UNION ALL
SELECT * FROM (
{orphans_part}
)
ORDER BY last_seen DESC
LIMIT {limit * 2}
"""


# ---------------------------------------------------------------------------
# Turn extraction
# ---------------------------------------------------------------------------


def _message_signature(message: dict[str, Any]) -> str:
    """Stable signature for dedup. Role + first 200 chars of content (raw or JSON)."""
    role = str(message.get("role", ""))
    content = message.get("content")
    if content is None:
        return f"{role}::"
    if isinstance(content, str):
        return f"{role}::{content.strip()[:200]}"
    try:
        return f"{role}::{json.dumps(content, sort_keys=True)[:200]}"
    except (TypeError, ValueError):
        return f"{role}::{hashlib.sha1(repr(content).encode()).hexdigest()}"


def _last_generation(trace: LLMTrace) -> dict[str, Any] | None:
    if not trace.events:
        return None
    generations = sorted(
        [e for e in trace.events if e.event == "$ai_generation"],
        key=lambda e: e.createdAt,
    )
    if not generations:
        return None
    return generations[-1].properties


def _replay_session_id(trace: LLMTrace) -> str | None:
    for event in trace.events or []:
        sid = event.properties.get("$session_id")
        if isinstance(sid, str) and sid:
            return sid
    return None


def _coerce_messages(raw: Any) -> list[dict[str, Any]]:
    """Flatten common message-array shapes into a list of dicts. Conservative on purpose;
    the frontend's `normalizeMessages` does the heavy multimodal flattening at render time.

    Handles three observed shapes for `$ai_output_choices`:
      1. `[{"role": "assistant", "content": "..."}, ...]` — already a message list
      2. `[{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}, ...]` — OpenAI chat completions
      3. `{"choices": [...]}` — wrapped LiteLLM-style response
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        messages: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            # OpenAI choices format: unwrap the inner `message` field
            if "message" in item and isinstance(item["message"], dict):
                messages.append(item["message"])
            else:
                messages.append(item)
        return messages
    if isinstance(raw, dict):
        if "choices" in raw and isinstance(raw["choices"], list):
            return _coerce_messages(raw["choices"])
        return [raw]
    if isinstance(raw, str):
        # Legacy: a bare string is treated as one assistant message.
        return [{"role": "assistant", "content": raw}]
    return []


def extract_turns(traces: list[LLMTrace]) -> list[dict[str, Any]]:
    """Build a flat chat transcript from a session's traces (chronological).

    For each trace, pick the last `$ai_generation` event. Its `$ai_input` array
    holds the conversation history sent to the model; we surface only the
    messages we have not already shown in earlier turns. The model's
    `$ai_output_choices` (or `$ai_output`) becomes the assistant turn.
    """
    seen: set[str] = set()
    turns: list[dict[str, Any]] = []
    for trace in traces:
        gen_props = _last_generation(trace)
        if gen_props is None:
            continue
        raw_input = gen_props.get("$ai_input") or gen_props.get("$ai_input_state")
        raw_output = gen_props.get("$ai_output_choices") or gen_props.get("$ai_output")

        all_input = _coerce_messages(raw_input)
        new_user_messages: list[dict[str, Any]] = []
        for msg in all_input:
            sig = _message_signature(msg)
            if sig in seen:
                continue
            seen.add(sig)
            role = msg.get("role")
            if role in ("user", "tool", "tools"):
                new_user_messages.append(msg)

        assistant_messages = _coerce_messages(raw_output)
        for msg in assistant_messages:
            seen.add(_message_signature(msg))

        turns.append(
            {
                "trace_id": trace.id,
                "trace_name": trace.traceName,
                "created_at": trace.createdAt,
                "session_id": _replay_session_id(trace),
                "user_messages": new_user_messages,
                "assistant_messages": assistant_messages,
                "total_cost": trace.totalCost,
                "total_latency": trace.totalLatency,
                "error_count": trace.errorCount or 0,
            }
        )
    return turns


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class ConversationListItemSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["session", "trace"],
        help_text="`session` if grouped by `$ai_session_id`, `trace` for orphan traces without a session id.",
    )
    id = serializers.CharField(
        help_text="Session id (when kind=session) or trace id (when kind=trace).",
    )
    title = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="Preview of the first user message in the conversation.",
    )
    turns = serializers.IntegerField(help_text="Number of traces (≈ chat turns) in the conversation.")
    distinct_id = serializers.CharField(allow_null=True, help_text="Distinct id of the user.")
    total_cost = serializers.FloatField(
        allow_null=True,
        help_text="Sum of `$ai_total_cost_usd` across all generation/embedding events.",
    )
    first_seen = serializers.DateTimeField(help_text="Timestamp of the earliest event in the conversation.")
    last_seen = serializers.DateTimeField(help_text="Timestamp of the latest event in the conversation.")


class ConversationListResponseSerializer(serializers.Serializer):
    results = serializers.ListField(
        child=ConversationListItemSerializer(),
        help_text="Conversations matching the filters, sorted by `last_seen` descending.",
    )


class ConversationTurnSerializer(serializers.Serializer):
    trace_id = serializers.CharField(help_text="Trace id corresponding to this turn.")
    trace_name = serializers.CharField(allow_null=True, help_text="Trace name, if set on the `$ai_trace` event.")
    created_at = serializers.DateTimeField(help_text="Timestamp of the trace's first event.")
    session_id = serializers.CharField(
        allow_null=True,
        help_text="Replay session id (`$session_id`) if present on any event; powers the 'Watch replay' link.",
    )
    user_messages = serializers.ListField(
        child=serializers.JSONField(),
        help_text="New user / tool messages introduced in this turn (deduplicated against earlier turns).",
    )
    assistant_messages = serializers.ListField(
        child=serializers.JSONField(),
        help_text="Assistant output messages from the trace's last `$ai_generation` event.",
    )
    total_cost = serializers.FloatField(allow_null=True, help_text="Total cost of this turn's events.")
    total_latency = serializers.FloatField(allow_null=True, help_text="Total latency of this turn's events.")
    error_count = serializers.IntegerField(help_text="Number of `$ai_is_error=true` events in the trace.")


class ConversationDetailResponseSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=["session", "trace"],
        help_text="`session` for a multi-turn conversation, `trace` for a single-trace conversation.",
    )
    id = serializers.CharField(help_text="Session id (kind=session) or trace id (kind=trace).")
    title = serializers.CharField(
        allow_null=True,
        allow_blank=True,
        help_text="Preview of the first user message in the conversation.",
    )
    distinct_id = serializers.CharField(allow_null=True, help_text="Distinct id of the user.")
    total_cost = serializers.FloatField(allow_null=True, help_text="Sum of cost across all turns.")
    total_latency = serializers.FloatField(allow_null=True, help_text="Sum of latency across all turns.")
    turns = serializers.ListField(
        child=ConversationTurnSerializer(),
        help_text="Turns in chronological order.",
    )


# ---------------------------------------------------------------------------
# ViewSet
# ---------------------------------------------------------------------------


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes")


def _truncate_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= 280 else cleaned[:280] + "…"


class _UnwrappedListSchemaPaginator:
    """drf-spectacular's `def list` heuristic always wraps the response schema in an
    array unless `pagination_class` is set to something with `get_paginated_response_schema`.
    We're not actually paginated — the response is a fixed `{results: [...]}` envelope —
    so this no-op paginator returns the schema unwrapped, which makes the generated OpenAPI
    (and therefore the Orval-generated TypeScript client) match the runtime shape.

    Only `get_paginated_response_schema` is called by drf-spectacular; `paginate_queryset`
    et al. are never reached because `def list` doesn't go through DRF's pagination path.
    """

    def get_paginated_response_schema(self, schema: dict) -> dict:
        # drf-spectacular pre-wraps the serializer's schema in `{type: array, items: ...}`
        # before calling us. To get the unwrapped envelope shape we declared on
        # `@extend_schema(responses=...)`, peel the array off and return just the items ref.
        if isinstance(schema, dict) and schema.get("type") == "array" and "items" in schema:
            return schema["items"]
        return schema

    def get_schema_operation_parameters(self, view: Any) -> list:
        # drf-spectacular calls this for list-action `parameters` (typically `?limit`/`?offset`).
        # Our pagination params are declared on the @extend_schema decorator instead.
        return []


class LLMAnalyticsConversationsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "llm_analytics"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions: list[str] = []
    permission_classes = [AccessControlPermission]
    # See _UnwrappedListSchemaPaginator above. Schema-time only; runtime never touches it.
    pagination_class = _UnwrappedListSchemaPaginator

    @extend_schema(
        parameters=[
            OpenApiParameter("date_from", OpenApiTypes.STR, description="Start of date range, e.g. -1h or -7d."),
            OpenApiParameter("date_to", OpenApiTypes.STR, description="End of date range; null for now."),
            OpenApiParameter(
                "filter_test_accounts",
                OpenApiTypes.BOOL,
                description="Apply the team's test-account filters.",
            ),
            OpenApiParameter(
                "include_orphan_traces",
                OpenApiTypes.BOOL,
                description="Include traces without `$ai_session_id` as single-turn conversations.",
            ),
            OpenApiParameter(
                "properties",
                OpenApiTypes.STR,
                description="JSON-encoded list of HogQL `AnyPropertyFilter` objects (event/person/cohort/HogQL).",
            ),
            OpenApiParameter("limit", OpenApiTypes.INT, description="Max rows per kind (capped at 200)."),
        ],
        # `OpenApiResponse(...)` opts out of drf-spectacular's automatic
        # list-action array wrapping. Without this, the generated OpenAPI schema
        # ends up with `{type: "array", items: ConversationListResponse}` even
        # though the actual response is a single `{results: [...]}` object —
        # which then propagates into the Orval-generated TypeScript types.
        responses={200: OpenApiResponse(response=ConversationListResponseSerializer)},
        tags=["LLM Analytics"],
    )
    def list(self, request: Request, **kwargs) -> Response:
        date_from = request.query_params.get("date_from") or "-1h"
        date_to = request.query_params.get("date_to") or None
        filter_test_accounts = _parse_bool(request.query_params.get("filter_test_accounts"))
        include_orphan_traces = _parse_bool(request.query_params.get("include_orphan_traces"))
        try:
            limit = min(int(request.query_params.get("limit") or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT)
        except (TypeError, ValueError):
            return Response({"limit": "Must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
        if limit <= 0:
            return Response({"limit": "Must be > 0."}, status=status.HTTP_400_BAD_REQUEST)

        properties_param = request.query_params.get("properties")
        properties: list[Any] | None = None
        if properties_param:
            try:
                parsed = json.loads(properties_param)
            except (TypeError, ValueError):
                return Response(
                    {"properties": "Must be a JSON-encoded array of HogQL property filters."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not isinstance(parsed, list):
                return Response(
                    {"properties": "Must be a JSON-encoded array of HogQL property filters."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            properties = parsed

        sql = _build_list_sql(include_orphan_traces=include_orphan_traces, limit=limit)
        filters = HogQLFilters(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            filterTestAccounts=filter_test_accounts,
            properties=properties,
        )
        query = parse_select(sql)
        query_with_filters = replace_filters(query, filters, self.team)

        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.LLM_ANALYTICS, team_id=self.team_id):
            try:
                result = execute_hogql_query(
                    query=query_with_filters,
                    team=self.team,
                    query_type="LLMConversationsList",
                    limit_context=LimitContext.QUERY,
                )
            except Exception:
                logger.exception("Failed to fetch conversations list", team_id=self.team_id)
                return Response(
                    {"error": "Failed to fetch conversations"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        results: list[dict[str, Any]] = []
        for row in result.results or []:
            kind, id_, title, turns, distinct_id, total_cost, first_seen, last_seen = row
            results.append(
                {
                    "kind": kind,
                    "id": id_,
                    "title": _truncate_title(title),
                    "turns": int(turns) if turns is not None else 0,
                    "distinct_id": distinct_id,
                    "total_cost": float(total_cost) if total_cost is not None else None,
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                }
            )

        # Serialize through the response serializer rather than returning the raw
        # dict — this ensures the runtime response shape matches the OpenAPI schema
        # (which the frontend types are generated from). Drift between the two
        # silently produces wrong frontend types; running every response through
        # the serializer makes any mismatch break tests immediately.
        response_serializer = ConversationListResponseSerializer({"results": results})
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "kind",
                OpenApiTypes.STR,
                description="Either `session` (default) or `trace`. Determines whether `pk` is a session id or a trace id.",
            ),
            OpenApiParameter("date_from", OpenApiTypes.STR, description="Start of date range; defaults to -30d."),
            OpenApiParameter("date_to", OpenApiTypes.STR, description="End of date range; null for now."),
        ],
        responses={
            200: ConversationDetailResponseSerializer,
            404: OpenApiTypes.OBJECT,
        },
        # Explicit `llm_analytics` tag works around a known issue in
        # `posthog/api/documentation.py::custom_postprocessing_hook`: the auto-tag injection
        # keys `_endpoint_product_mapping` by the pre-spec path (with `{pk}`) but looks it up
        # by the post-spec path (drf-spectacular rewrites `{pk}` → `{id}` for retrieve actions).
        # Without this, the tag is missing and Orval skips generating the client method.
        tags=["LLM Analytics", "llm_analytics"],
    )
    def retrieve(self, request: Request, pk: str | None = None, **kwargs) -> Response:
        if not pk:
            raise exceptions.NotFound()
        kind = (request.query_params.get("kind") or "session").lower()
        if kind not in ("session", "trace"):
            return Response(
                {"kind": "Must be 'session' or 'trace'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        date_from = request.query_params.get("date_from") or "-30d"
        date_to = request.query_params.get("date_to")

        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.LLM_ANALYTICS, team_id=self.team_id):
            try:
                if kind == "session":
                    traces = self._fetch_session_traces(pk, date_from, date_to)
                else:
                    traces = self._fetch_orphan_trace(pk, date_from, date_to)
            except Exception:
                logger.exception(
                    "Failed to fetch conversation",
                    team_id=self.team_id,
                    conversation_kind=kind,
                    conversation_id=pk,
                )
                return Response(
                    {"error": "Failed to fetch conversation"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        if not traces:
            raise exceptions.NotFound("Conversation not found in the given date range.")

        turns = extract_turns(traces)
        title = next(
            (
                msg.get("content")
                for turn in turns
                for msg in turn.get("user_messages", [])
                if msg.get("role") == "user" and isinstance(msg.get("content"), str) and msg.get("content")
            ),
            None,
        )

        total_cost = sum(t.totalCost or 0 for t in traces) or None
        total_latency = sum(t.totalLatency or 0 for t in traces) or None
        first_distinct_id = next((t.distinctId for t in traces if t.distinctId), None)

        response_serializer = ConversationDetailResponseSerializer(
            {
                "kind": kind,
                "id": pk,
                "title": _truncate_title(title) if title else None,
                "distinct_id": first_distinct_id,
                "total_cost": total_cost,
                "total_latency": total_latency,
                "turns": turns,
            }
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def _fetch_session_traces(self, session_id: str, date_from: str, date_to: str | None) -> list[LLMTrace]:
        traces_query = TracesQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=[
                {
                    "type": "event",
                    "key": "$ai_session_id",
                    "operator": "exact",
                    "value": session_id,
                }
            ],
        )
        traces_response = TracesQueryRunner(team=self.team, query=traces_query).calculate()
        traces_response = cast(CachedTracesQueryResponse, traces_response)
        # Newest-first → chronological
        shallow_traces: list[LLMTrace] = list(reversed(traces_response.results or []))
        if not shallow_traces:
            return []
        # Re-fetch each trace with full event payload (the list query only includes
        # direct-child events). Run in parallel — each fetch is its own ClickHouse
        # round-trip, so wall-clock becomes max(individual) instead of sum.
        #
        # Why we re-apply `tags_context` inside each worker: the parent thread sets
        # query tags as `ContextVar`s in `retrieve()`, and `ContextVar`s do NOT
        # propagate into `ThreadPoolExecutor` workers — each worker thread gets a
        # fresh empty context. Without re-tagging, the per-worker ClickHouse queries
        # would land in observability dashboards untagged (no product / feature /
        # team_id), silently regressing query attribution. We can't reuse a single
        # `copy_context()` snapshot across workers either: `Context.run()` can't be
        # invoked concurrently on the same Context. Re-applying the (constant) tags
        # explicitly is both safest and most readable.
        team_id = self.team_id

        def fetch(trace: LLMTrace) -> LLMTrace | None:
            with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.LLM_ANALYTICS, team_id=team_id):
                return self._fetch_trace(trace.id, date_from, date_to)

        worker_count = min(TRACE_FETCH_CONCURRENCY, len(shallow_traces))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(fetch, shallow_traces))
        return [trace for trace in results if trace is not None]

    def _fetch_orphan_trace(self, trace_id: str, date_from: str, date_to: str | None) -> list[LLMTrace]:
        trace = self._fetch_trace(trace_id, date_from, date_to)
        return [trace] if trace is not None else []

    def _fetch_trace(self, trace_id: str, date_from: str, date_to: str | None) -> LLMTrace | None:
        runner = TraceQueryRunner(
            team=self.team,
            query=TraceQuery(
                traceId=trace_id,
                dateRange=DateRange(date_from=date_from, date_to=date_to),
            ),
        )
        result = runner.calculate()
        if not result.results:
            return None
        return result.results[0]
