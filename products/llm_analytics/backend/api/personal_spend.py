"""
Personal LLM spend analysis endpoint.

Surfaces the requesting user's own LLM spend across PostHog products (last N
days) by running a fixed set of HogQL queries against PostHog's internal cloud
analytics team. Optionally filter to a single `ai_product` (e.g. `posthog_code`,
`background_agents`) — when omitted, results aggregate across every product
captured by LLM analytics for that user.

Endpoint:
- GET /api/llm_analytics/@me/spend/?days=30&product=<key>&limit=50&refresh=false
"""

from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponseRedirect

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
from posthog.models import Team, User
from posthog.rate_limit import PersonalSpendBurstThrottle, PersonalSpendDailyThrottle, PersonalSpendSustainedThrottle

logger = structlog.get_logger(__name__)

MAX_PRODUCT_KEY_LENGTH = 64

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 30

MIN_LIMIT = 1
MAX_LIMIT = 200
DEFAULT_LIMIT = 50

CACHE_TIMEOUT_SECONDS = 300


def _internal_team_id() -> int:
    return settings.LLM_ANALYTICS_INTERNAL_TEAM_ID


def _cache_key(distinct_id: str, days: int, product: str | None, limit: int) -> str:
    product_slot = product or "_all"
    return f"personal_spend:{distinct_id}:{days}:{product_slot}:{limit}"


class _SpendQueryParamsSerializer(serializers.Serializer):
    days = serializers.IntegerField(
        required=False,
        min_value=MIN_DAYS,
        max_value=MAX_DAYS,
        default=DEFAULT_DAYS,
        help_text=f"Lookback window in days for the spend analysis ({MIN_DAYS}-{MAX_DAYS}). Defaults to {DEFAULT_DAYS}.",
    )
    product = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        max_length=MAX_PRODUCT_KEY_LENGTH,
        default=None,
        help_text=(
            "Optional `ai_product` key to scope the tool / model / trace breakdowns to a single product "
            "(e.g. `posthog_code`, `background_agents`). When omitted, those breakdowns aggregate across "
            "every product captured for the user."
        ),
    )
    limit = serializers.IntegerField(
        required=False,
        min_value=MIN_LIMIT,
        max_value=MAX_LIMIT,
        default=DEFAULT_LIMIT,
        help_text=(
            f"Maximum number of rows to return per breakdown ({MIN_LIMIT}-{MAX_LIMIT}, defaults to {DEFAULT_LIMIT}). "
            "Each breakdown returns up to this many rows ordered by cost descending. "
            "Per-breakdown `truncated: true` indicates more rows exist beyond the limit."
        ),
    )
    refresh = serializers.BooleanField(
        required=False,
        default=False,
        help_text="If true, bypass the result cache and re-run the underlying queries against ClickHouse.",
    )


class _ProductBreakdownRowSerializer(serializers.Serializer):
    product = serializers.CharField(
        allow_null=True,
        help_text="Value of the `ai_product` property on the event (e.g. `posthog_code`, `background_agents`). Null when unset.",
    )
    event_count = serializers.IntegerField(
        help_text="Number of $ai_generation + $ai_embedding events for this product."
    )
    cost_usd = serializers.FloatField(help_text="Total cost in USD for this product over the lookback window.")


class _ToolBreakdownRowSerializer(serializers.Serializer):
    tool = serializers.CharField(
        allow_null=True,
        help_text=(
            "Individual tool name from `$ai_tools_called` (split on `,` since multi-tool generations "
            "store a comma-separated list). Null = pure text response with no tool call."
        ),
    )
    generation_count = serializers.IntegerField(
        help_text="Number of $ai_generation events whose tool list includes this tool."
    )
    cost_usd = serializers.FloatField(
        help_text=(
            "Sum of `$ai_total_cost_usd` for generations whose tool list includes this tool. Multi-tool "
            "generations contribute their full cost to every tool they invoked, so this sum can exceed "
            "`summary.scoped_cost_usd`. Prefer `share_of_scoped` for headline percentages — it's computed "
            "per row and doesn't require the totals to reconcile."
        ),
    )
    share_of_scoped = serializers.FloatField(
        help_text=(
            "This tool's share of `summary.scoped_cost_usd`, expressed as a float in `[0, 1]`. Independent "
            "per row, so co-occurring tools can each show a substantial share — the headline number to "
            "present (e.g. `'Bash drove 47% of your spend'`)."
        ),
    )
    avg_input_tokens = serializers.FloatField(
        help_text="Average `$ai_input_tokens` across these generations — high values signal context bloat per call.",
    )


class _ModelBreakdownRowSerializer(serializers.Serializer):
    model = serializers.CharField(allow_null=True, help_text="Value of the `$ai_model` property.")
    generation_count = serializers.IntegerField(help_text="Number of $ai_generation + $ai_embedding events.")
    cost_usd = serializers.FloatField(help_text="Total cost in USD for this model.")
    input_tokens = serializers.IntegerField(help_text="Sum of `$ai_input_tokens` for this model.")
    output_tokens = serializers.IntegerField(help_text="Sum of `$ai_output_tokens` for this model.")


class _TopTraceRowSerializer(serializers.Serializer):
    trace_id = serializers.CharField(
        allow_null=True,
        help_text="`$ai_trace_id` of the session — opaque string scoped to the originating product.",
    )
    generation_count = serializers.IntegerField(help_text="Number of $ai_generation events in this trace.")
    cost_usd = serializers.FloatField(help_text="Total cost in USD for this trace.")
    started_at = serializers.DateTimeField(allow_null=True, help_text="Timestamp of the earliest event in this trace.")


class _SummarySerializer(serializers.Serializer):
    period_days = serializers.IntegerField(help_text="Lookback window in days used for the analysis.")
    product = serializers.CharField(
        allow_null=True,
        help_text="The `ai_product` filter applied to tool / model / trace breakdowns. Null when unfiltered.",
    )
    total_cost_usd = serializers.FloatField(
        help_text="Total LLM cost in USD across every `ai_product` for the user — independent of the `product` filter."
    )
    event_count = serializers.IntegerField(
        help_text="Total $ai_generation + $ai_embedding events captured across every product."
    )
    scoped_cost_usd = serializers.FloatField(
        help_text=(
            "Total cost in USD for the product filter (or all products when unfiltered). Matches the cost summed "
            "across `by_tool` / `by_model` for the scoped slice."
        ),
    )
    scoped_event_count = serializers.IntegerField(
        help_text="Total $ai_generation + $ai_embedding events for the scoped slice."
    )


class _ProductBreakdownSerializer(serializers.Serializer):
    items = _ProductBreakdownRowSerializer(many=True, help_text="Rows of spend by product, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class _ToolBreakdownSerializer(serializers.Serializer):
    items = _ToolBreakdownRowSerializer(many=True, help_text="Rows of spend by tool, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class _ModelBreakdownSerializer(serializers.Serializer):
    items = _ModelBreakdownRowSerializer(many=True, help_text="Rows of spend by model, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class _TopTracesSerializer(serializers.Serializer):
    items = _TopTraceRowSerializer(many=True, help_text="Rows of top traces by cost, ordered by cost descending.")
    truncated = serializers.BooleanField(
        help_text="True when more rows exist beyond the requested `limit`. Re-request with a larger `limit` to retrieve them."
    )


class PersonalSpendAnalysisResponseSerializer(serializers.Serializer):
    """Structured personal LLM spend analysis for the requesting user."""

    summary = _SummarySerializer(help_text="High-level totals for the lookback window.")
    by_product = _ProductBreakdownSerializer(
        help_text="Spend grouped by the `ai_product` property — always across all products, never filtered."
    )
    by_tool = _ToolBreakdownSerializer(help_text="Spend grouped by tool. Scoped to `product` when set.")
    by_model = _ModelBreakdownSerializer(help_text="Spend grouped by `$ai_model`. Scoped to `product` when set.")
    top_traces = _TopTracesSerializer(
        help_text="Most expensive trace IDs (sessions) in the window. Scoped to `product` when set."
    )


def _distinct_id_filter(distinct_id: str) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["distinct_id"]),
        right=ast.Constant(value=distinct_id),
    )


def _timestamp_filter(days: int) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.GtEq,
        left=ast.Field(chain=["timestamp"]),
        right=ast.Call(
            name="minus",
            args=[
                ast.Call(name="now", args=[]),
                ast.Call(name="toIntervalDay", args=[ast.Constant(value=days)]),
            ],
        ),
    )


def _event_in(events: list[str]) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=e) for e in events]),
    )


def _ai_product_eq(value: str) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["properties", "ai_product"]),
        right=ast.Constant(value=value),
    )


def _true() -> ast.Expr:
    """Identity filter used when no product scoping is requested."""
    return ast.Constant(value=True)


def _product_filter(product: str | None) -> ast.Expr:
    return _ai_product_eq(product) if product else _true()


def _truncate(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Trim a `limit + 1` row fetch back down to `limit` rows and set the `truncated` flag."""
    return {"items": rows[:limit], "truncated": len(rows) > limit}


def _fetch_summary(team: Team, distinct_id: str, days: int, product: str | None) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            countIf({product_filter}) AS scoped_event_count,
            round(sumIf(toFloat(properties.$ai_total_cost_usd), {product_filter}), 6) AS scoped_cost_usd,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS total_cost_usd
        FROM ai_events
        WHERE {event_in} AND {distinct_id_filter} AND {timestamp_filter}
        """
    )
    result = execute_with_ai_events_fallback(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "distinct_id_filter": _distinct_id_filter(distinct_id),
            "timestamp_filter": _timestamp_filter(days),
        },
        team=team,
        query_type="PersonalSpendSummary",
    )
    row = (result.results or [(0, 0.0, 0, 0.0)])[0]
    return {
        "period_days": days,
        "product": product,
        "scoped_event_count": int(row[0] or 0),
        "scoped_cost_usd": float(row[1] or 0.0),
        "event_count": int(row[2] or 0),
        "total_cost_usd": float(row[3] or 0.0),
    }


def _fetch_by_product(team: Team, distinct_id: str, days: int, limit: int) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            properties.ai_product AS product,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd
        FROM ai_events
        WHERE {event_in} AND {distinct_id_filter} AND {timestamp_filter}
        GROUP BY product
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_with_ai_events_fallback(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "distinct_id_filter": _distinct_id_filter(distinct_id),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=limit + 1),
        },
        team=team,
        query_type="PersonalSpendByProduct",
    )
    rows = [
        {
            "product": row[0] if row[0] is not None else None,
            "event_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, limit)


def _fetch_by_tool(team: Team, distinct_id: str, days: int, product: str | None, limit: int) -> dict[str, Any]:
    # `$ai_tools_called` stores a comma-separated list of all tools called within a
    # generation (e.g. "Bash,Read"). Split it so multi-tool generations contribute to
    # each individual tool row. nullIf restores the no-tool case (where the property
    # is NULL and coalesce produces an empty string) to a NULL bucket.
    query = parse_select(
        """
        SELECT
            nullIf(arrayJoin(splitByChar(',', coalesce(properties.$ai_tools_called, ''))), '') AS tool,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            round(avg(toFloat(properties.$ai_input_tokens)), 0) AS avg_input_tokens
        FROM ai_events
        WHERE equals(event, '$ai_generation')
            AND {product_filter}
            AND {distinct_id_filter}
            AND {timestamp_filter}
        GROUP BY tool
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_with_ai_events_fallback(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "distinct_id_filter": _distinct_id_filter(distinct_id),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=limit + 1),
        },
        team=team,
        query_type="PersonalSpendByTool",
    )
    rows = [
        {
            "tool": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "avg_input_tokens": float(row[3] or 0.0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, limit)


def _fetch_by_model(team: Team, distinct_id: str, days: int, product: str | None, limit: int) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            properties.$ai_model AS model,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
            sum(toFloat(properties.$ai_output_tokens)) AS output_tokens
        FROM ai_events
        WHERE {event_in}
            AND {product_filter}
            AND {distinct_id_filter}
            AND {timestamp_filter}
        GROUP BY model
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_with_ai_events_fallback(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "product_filter": _product_filter(product),
            "distinct_id_filter": _distinct_id_filter(distinct_id),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=limit + 1),
        },
        team=team,
        query_type="PersonalSpendByModel",
    )
    rows = [
        {
            "model": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "input_tokens": int(row[3] or 0),
            "output_tokens": int(row[4] or 0),
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, limit)


def _fetch_top_traces(team: Team, distinct_id: str, days: int, product: str | None, limit: int) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            properties.$ai_trace_id AS trace_id,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            min(timestamp) AS started_at
        FROM ai_events
        WHERE equals(event, '$ai_generation')
            AND {product_filter}
            AND {distinct_id_filter}
            AND {timestamp_filter}
        GROUP BY trace_id
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_with_ai_events_fallback(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "distinct_id_filter": _distinct_id_filter(distinct_id),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=limit + 1),
        },
        team=team,
        query_type="PersonalSpendTopTraces",
    )
    rows = [
        {
            "trace_id": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "started_at": row[3],
        }
        for row in (result.results or [])
    ]
    return _truncate(rows, limit)


class PersonalSpendViewSet(viewsets.ViewSet):
    """
    Returns the requesting user's personal LLM spend analysis across PostHog products.

    Queries are run server-side against PostHog's internal analytics team
    (settings.LLM_ANALYTICS_INTERNAL_TEAM_ID) and are strictly scoped to the
    authenticated user's PostHog distinct_id — callers cannot pivot to other
    users' data. Routes through `execute_with_ai_events_fallback` so reads hit
    the dedicated `ai_events` table when enabled, with the shared `events`
    table as a fallback. Optionally filter tool / model / trace breakdowns to
    a single `ai_product` via the `product` query param; `by_product` always
    returns the full cross-product breakdown. The endpoint is only registered
    on US Cloud + dev/test envs; hobby/self-hosted deploys never see this URL.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_throttles(self):
        return [
            PersonalSpendBurstThrottle(),
            PersonalSpendSustainedThrottle(),
            PersonalSpendDailyThrottle(),
        ]

    @extend_schema(
        parameters=[_SpendQueryParamsSerializer],
        responses={
            200: PersonalSpendAnalysisResponseSerializer,
            400: None,
            401: None,
        },
        description=(
            "Return a structured personal LLM spend analysis for the requesting user over the last "
            "`days` days. Pass `product=<ai_product>` to scope tool / model / trace breakdowns to a "
            "single product (e.g. `posthog_code`); omit it for an aggregate view. `by_product` is "
            "always returned for cross-product visibility."
        ),
        tags=["LLM Analytics"],
    )
    def list(self, request: Request) -> Response:
        user = cast(User, request.user)
        distinct_id = user.distinct_id
        if not distinct_id:
            raise exceptions.PermissionDenied("User has no distinct_id on record; cannot scope spend analysis.")

        params = _SpendQueryParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        days = params.validated_data["days"]
        product = params.validated_data["product"]
        limit = params.validated_data["limit"]
        refresh = params.validated_data["refresh"]

        cache_key = _cache_key(distinct_id, days, product, limit)

        if not refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

        team_id = _internal_team_id()
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            logger.exception("personal_spend.team_missing", team_id=team_id)
            raise exceptions.NotFound("Internal analytics team is not provisioned on this deployment.")

        summary = _fetch_summary(team, distinct_id, days, product)
        by_tool = _fetch_by_tool(team, distinct_id, days, product, limit)
        scoped = summary["scoped_cost_usd"] or 0.0
        # `cost_usd` in by_tool can exceed scoped_cost_usd because multi-tool generations
        # contribute to every tool. `share_of_scoped` is independent per row, so agents can
        # present headline percentages directly without reconciling sums.
        for row in by_tool["items"]:
            row["share_of_scoped"] = (row["cost_usd"] / scoped) if scoped > 0 else 0.0

        payload = {
            "summary": summary,
            "by_product": _fetch_by_product(team, distinct_id, days, limit),
            "by_tool": by_tool,
            "by_model": _fetch_by_model(team, distinct_id, days, product, limit),
            "top_traces": _fetch_top_traces(team, distinct_id, days, product, limit),
        }

        response_data = PersonalSpendAnalysisResponseSerializer(payload).data
        cache.set(cache_key, response_data, timeout=CACHE_TIMEOUT_SECONDS)
        return Response(response_data, status=status.HTTP_200_OK)


def personal_spend_eu_redirect(request: HttpRequest) -> HttpResponseRedirect:
    """Redirect EU callers to the US-hosted endpoint where the data actually lives.

    EU PostHog Cloud forwards its product LLM telemetry to PostHog Cloud US, so the
    spend analysis only runs there. Returning a 302 makes the new home discoverable
    instead of serving a silent 404. Callers still need a US-valid auth token.
    """
    target = "https://us.posthog.com/api/llm_analytics/@me/spend/"
    query = request.META.get("QUERY_STRING", "")
    if query:
        target = f"{target}?{query}"
    return HttpResponseRedirect(target)
