"""
Personal LLM spend analysis endpoint.

Surfaces the requesting user's own LLM spend across PostHog products (last N
days) by running a fixed set of HogQL queries against PostHog's internal cloud
analytics team. Optionally filter to a single `ai_product` (e.g. `posthog_code`,
`background_agents`) — when omitted, results aggregate across every product
captured by LLM analytics for that user.

Endpoint:
- GET /api/llm_analytics/personal_spend/?days=30&product=<key>&refresh=false
"""

from __future__ import annotations

from typing import Any, cast

from django.conf import settings
from django.core.cache import cache

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions, permissions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team, User
from posthog.rate_limit import PersonalSpendBurstThrottle, PersonalSpendDailyThrottle, PersonalSpendSustainedThrottle

logger = structlog.get_logger(__name__)

TOP_TRACES_LIMIT = 10
TOP_TOOLS_LIMIT = 20
TOP_MODELS_LIMIT = 10
TOP_PRODUCTS_LIMIT = 10
MAX_PRODUCT_KEY_LENGTH = 64

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 30

CACHE_TIMEOUT_SECONDS = 300


def _internal_team_id() -> int:
    return settings.LLM_ANALYTICS_INTERNAL_TEAM_ID


def _cache_key(distinct_id: str, days: int, product: str | None) -> str:
    product_slot = product or "_all"
    return f"personal_spend:{distinct_id}:{days}:{product_slot}"


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
        help_text="Last tool the model called on the generation (`$ai_tools_called`). Null = pure text response with no tool call.",
    )
    generation_count = serializers.IntegerField(
        help_text="Number of $ai_generation events that ended with this tool call."
    )
    cost_usd = serializers.FloatField(help_text="Total cost in USD for generations ending with this tool.")
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


class PersonalSpendAnalysisResponseSerializer(serializers.Serializer):
    """Structured personal LLM spend analysis for the requesting user."""

    summary = _SummarySerializer(help_text="High-level totals for the lookback window.")
    by_product = _ProductBreakdownRowSerializer(
        many=True,
        help_text="Spend grouped by the `ai_product` property — always across all products, never filtered.",
    )
    by_tool = _ToolBreakdownRowSerializer(
        many=True,
        help_text="Spend grouped by the last tool called on each generation. Scoped to `product` when set. Ordered by cost descending.",
    )
    by_model = _ModelBreakdownRowSerializer(
        many=True,
        help_text="Spend grouped by `$ai_model`. Scoped to `product` when set. Ordered by cost descending.",
    )
    top_traces = _TopTraceRowSerializer(
        many=True,
        help_text="Most expensive trace IDs (sessions) in the window. Scoped to `product` when set.",
    )


def _email_filter(email: str) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["person", "properties", "email"]),
        right=ast.Constant(value=email),
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


def _fetch_summary(team: Team, email: str, days: int, product: str | None) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            countIf({product_filter}) AS scoped_event_count,
            round(sumIf(toFloat(properties.$ai_total_cost_usd), {product_filter}), 6) AS scoped_cost_usd,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS total_cost_usd
        FROM events
        WHERE {event_in} AND {email_filter} AND {timestamp_filter}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "email_filter": _email_filter(email),
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


def _fetch_by_product(team: Team, email: str, days: int) -> list[dict[str, Any]]:
    query = parse_select(
        """
        SELECT
            properties.ai_product AS product,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd
        FROM events
        WHERE {event_in} AND {email_filter} AND {timestamp_filter}
        GROUP BY product
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=TOP_PRODUCTS_LIMIT),
        },
        team=team,
        query_type="PersonalSpendByProduct",
    )
    return [
        {
            "product": row[0] if row[0] is not None else None,
            "event_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
        }
        for row in (result.results or [])
    ]


def _fetch_by_tool(team: Team, email: str, days: int, product: str | None) -> list[dict[str, Any]]:
    query = parse_select(
        """
        SELECT
            properties.$ai_tools_called AS tool,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            round(avg(toFloat(properties.$ai_input_tokens)), 0) AS avg_input_tokens
        FROM events
        WHERE equals(event, '$ai_generation')
            AND {product_filter}
            AND {email_filter}
            AND {timestamp_filter}
        GROUP BY tool
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=TOP_TOOLS_LIMIT),
        },
        team=team,
        query_type="PersonalSpendByTool",
    )
    return [
        {
            "tool": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "avg_input_tokens": float(row[3] or 0.0),
        }
        for row in (result.results or [])
    ]


def _fetch_by_model(team: Team, email: str, days: int, product: str | None) -> list[dict[str, Any]]:
    query = parse_select(
        """
        SELECT
            properties.$ai_model AS model,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            sum(toFloat(properties.$ai_input_tokens)) AS input_tokens,
            sum(toFloat(properties.$ai_output_tokens)) AS output_tokens
        FROM events
        WHERE {event_in}
            AND {product_filter}
            AND {email_filter}
            AND {timestamp_filter}
        GROUP BY model
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "product_filter": _product_filter(product),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=TOP_MODELS_LIMIT),
        },
        team=team,
        query_type="PersonalSpendByModel",
    )
    return [
        {
            "model": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "input_tokens": int(row[3] or 0),
            "output_tokens": int(row[4] or 0),
        }
        for row in (result.results or [])
    ]


def _fetch_top_traces(team: Team, email: str, days: int, product: str | None) -> list[dict[str, Any]]:
    query = parse_select(
        """
        SELECT
            properties.$ai_trace_id AS trace_id,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            min(timestamp) AS started_at
        FROM events
        WHERE equals(event, '$ai_generation')
            AND {product_filter}
            AND {email_filter}
            AND {timestamp_filter}
        GROUP BY trace_id
        ORDER BY cost_usd DESC
        LIMIT {limit}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "product_filter": _product_filter(product),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=TOP_TRACES_LIMIT),
        },
        team=team,
        query_type="PersonalSpendTopTraces",
    )
    return [
        {
            "trace_id": row[0] if row[0] is not None else None,
            "generation_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
            "started_at": row[3],
        }
        for row in (result.results or [])
    ]


class PersonalSpendViewSet(viewsets.ViewSet):
    """
    Returns the requesting user's personal LLM spend analysis across PostHog products.

    Queries are run server-side against PostHog's internal analytics team
    (settings.LLM_ANALYTICS_INTERNAL_TEAM_ID) and are strictly scoped to the
    authenticated user's email — callers cannot pivot to other users' data.
    Optionally filter tool / model / trace breakdowns to a single `ai_product`
    via the `product` query param; `by_product` always returns the full
    cross-product breakdown. The endpoint is only registered on US Cloud +
    dev/test envs; hobby/self-hosted deploys never see this URL.
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
        email = getattr(user, "email", None)
        if not email:
            raise exceptions.PermissionDenied("User has no email on record; cannot scope spend analysis.")

        params = _SpendQueryParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        days = params.validated_data["days"]
        product = params.validated_data["product"]
        refresh = params.validated_data["refresh"]

        distinct_id = user.distinct_id or str(user.uuid)
        cache_key = _cache_key(distinct_id, days, product)

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

        payload = {
            "summary": _fetch_summary(team, email, days, product),
            "by_product": _fetch_by_product(team, email, days),
            "by_tool": _fetch_by_tool(team, email, days, product),
            "by_model": _fetch_by_model(team, email, days, product),
            "top_traces": _fetch_top_traces(team, email, days, product),
        }

        response_data = PersonalSpendAnalysisResponseSerializer(payload).data
        cache.set(cache_key, response_data, timeout=CACHE_TIMEOUT_SECONDS)
        return Response(response_data, status=status.HTTP_200_OK)
