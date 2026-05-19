"""
Token spend analysis endpoint for PostHog Code users.

Surfaces the requesting user's own LLM spend (last N days) by running a
fixed set of HogQL queries against PostHog's internal cloud analytics team
(where PostHog Code reports `$ai_generation` / `$ai_embedding` events).

Endpoint:
- GET /api/llm_analytics/posthog_code_spend/?days=30
"""

from __future__ import annotations

from typing import Any

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

from posthog.models import Team
from posthog.rate_limit import (
    PostHogCodeSpendBurstThrottle,
    PostHogCodeSpendDailyThrottle,
    PostHogCodeSpendSustainedThrottle,
)

logger = structlog.get_logger(__name__)

AI_PRODUCT_POSTHOG_CODE = "posthog_code"
TOP_TRACES_LIMIT = 10
TOP_TOOLS_LIMIT = 20
TOP_MODELS_LIMIT = 10
TOP_PRODUCTS_LIMIT = 10

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 30

CACHE_TIMEOUT_SECONDS = 300


def _internal_team_id() -> int:
    return settings.POSTHOG_CODE_ANALYTICS_TEAM_ID


def _cache_key(distinct_id: str, days: int) -> str:
    return f"posthog_code_spend:{distinct_id}:{days}"


class _SpendQueryParamsSerializer(serializers.Serializer):
    days = serializers.IntegerField(
        required=False,
        min_value=MIN_DAYS,
        max_value=MAX_DAYS,
        default=DEFAULT_DAYS,
        help_text=f"Lookback window in days for the spend analysis ({MIN_DAYS}-{MAX_DAYS}). Defaults to {DEFAULT_DAYS}.",
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
        help_text="`$ai_trace_id` of the session — opaque string scoped to PostHog Code.",
    )
    generation_count = serializers.IntegerField(help_text="Number of $ai_generation events in this trace.")
    cost_usd = serializers.FloatField(help_text="Total cost in USD for this trace.")
    started_at = serializers.DateTimeField(allow_null=True, help_text="Timestamp of the earliest event in this trace.")


class _SummarySerializer(serializers.Serializer):
    period_days = serializers.IntegerField(help_text="Lookback window in days used for the analysis.")
    total_cost_usd = serializers.FloatField(
        help_text="Total LLM cost in USD across all `ai_product` values for the user."
    )
    event_count = serializers.IntegerField(help_text="Total $ai_generation + $ai_embedding events captured.")
    posthog_code_cost_usd = serializers.FloatField(
        help_text="Total cost in USD attributed to `ai_product = 'posthog_code'`.",
    )
    posthog_code_event_count = serializers.IntegerField(
        help_text="Total $ai_generation events where `ai_product = 'posthog_code'`."
    )


class TokenSpendAnalysisResponseSerializer(serializers.Serializer):
    """Structured PostHog Code spend analysis for the requesting user."""

    summary = _SummarySerializer(help_text="High-level totals for the lookback window.")
    by_product = _ProductBreakdownRowSerializer(
        many=True,
        help_text="Spend grouped by the `ai_product` property — shows posthog_code share vs background_agents etc.",
    )
    by_tool = _ToolBreakdownRowSerializer(
        many=True,
        help_text="Spend grouped by the last tool called on each generation (PostHog Code only). Ordered by cost descending.",
    )
    by_model = _ModelBreakdownRowSerializer(
        many=True,
        help_text="Spend grouped by `$ai_model` (PostHog Code only). Ordered by cost descending.",
    )
    top_traces = _TopTraceRowSerializer(
        many=True,
        help_text="Most expensive trace IDs (sessions) in the window (PostHog Code only).",
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


def _fetch_summary(team: Team, email: str, days: int) -> dict[str, Any]:
    query = parse_select(
        """
        SELECT
            countIf(equals(properties.ai_product, {posthog_code})) AS posthog_code_event_count,
            round(sumIf(toFloat(properties.$ai_total_cost_usd), equals(properties.ai_product, {posthog_code})), 6) AS posthog_code_cost_usd,
            count() AS event_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS total_cost_usd
        FROM events
        WHERE {event_in} AND {email_filter} AND {timestamp_filter}
        """
    )
    result = execute_hogql_query(
        query=query,
        placeholders={
            "posthog_code": ast.Constant(value=AI_PRODUCT_POSTHOG_CODE),
            "event_in": _event_in(["$ai_generation", "$ai_embedding"]),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
        },
        team=team,
        query_type="PostHogCodeSpendSummary",
    )
    row = (result.results or [(0, 0.0, 0, 0.0)])[0]
    return {
        "period_days": days,
        "posthog_code_event_count": int(row[0] or 0),
        "posthog_code_cost_usd": float(row[1] or 0.0),
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
        query_type="PostHogCodeSpendByProduct",
    )
    return [
        {
            "product": row[0] if row[0] is not None else None,
            "event_count": int(row[1] or 0),
            "cost_usd": float(row[2] or 0.0),
        }
        for row in (result.results or [])
    ]


def _fetch_by_tool(team: Team, email: str, days: int) -> list[dict[str, Any]]:
    query = parse_select(
        """
        SELECT
            properties.$ai_tools_called AS tool,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            round(avg(toFloat(properties.$ai_input_tokens)), 0) AS avg_input_tokens
        FROM events
        WHERE equals(event, '$ai_generation')
            AND {ai_product_eq}
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
            "ai_product_eq": _ai_product_eq(AI_PRODUCT_POSTHOG_CODE),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=TOP_TOOLS_LIMIT),
        },
        team=team,
        query_type="PostHogCodeSpendByTool",
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


def _fetch_by_model(team: Team, email: str, days: int) -> list[dict[str, Any]]:
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
            AND {ai_product_eq}
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
            "ai_product_eq": _ai_product_eq(AI_PRODUCT_POSTHOG_CODE),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=TOP_MODELS_LIMIT),
        },
        team=team,
        query_type="PostHogCodeSpendByModel",
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


def _fetch_top_traces(team: Team, email: str, days: int) -> list[dict[str, Any]]:
    query = parse_select(
        """
        SELECT
            properties.$ai_trace_id AS trace_id,
            count() AS generation_count,
            round(sum(toFloat(properties.$ai_total_cost_usd)), 6) AS cost_usd,
            min(timestamp) AS started_at
        FROM events
        WHERE equals(event, '$ai_generation')
            AND {ai_product_eq}
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
            "ai_product_eq": _ai_product_eq(AI_PRODUCT_POSTHOG_CODE),
            "email_filter": _email_filter(email),
            "timestamp_filter": _timestamp_filter(days),
            "limit": ast.Constant(value=TOP_TRACES_LIMIT),
        },
        team=team,
        query_type="PostHogCodeSpendTopTraces",
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


class PostHogCodeSpendViewSet(viewsets.ViewSet):
    """
    Returns the requesting user's PostHog Code LLM spend analysis.

    Queries are run server-side against PostHog's internal analytics team
    (settings.POSTHOG_CODE_ANALYTICS_TEAM_ID) and are strictly scoped to
    the authenticated user's email — callers cannot pivot to other users'
    data. The endpoint is only registered on US Cloud + dev/test envs;
    hobby/self-hosted deploys never see this URL.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get_throttles(self):
        return [
            PostHogCodeSpendBurstThrottle(),
            PostHogCodeSpendSustainedThrottle(),
            PostHogCodeSpendDailyThrottle(),
        ]

    @extend_schema(
        parameters=[_SpendQueryParamsSerializer],
        responses={
            200: TokenSpendAnalysisResponseSerializer,
            400: None,
            401: None,
        },
        description=(
            "Return a structured spend analysis for the requesting user's PostHog Code "
            "usage over the last `days` days. Includes totals, breakdowns by ai_product, "
            "tool, and model, plus the most expensive traces."
        ),
        tags=["LLM Analytics"],
    )
    def list(self, request: Request) -> Response:
        user = request.user
        email = getattr(user, "email", None)
        if not email:
            raise exceptions.PermissionDenied("User has no email on record; cannot scope spend analysis.")

        params = _SpendQueryParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        days = params.validated_data["days"]
        refresh = params.validated_data["refresh"]

        distinct_id = user.distinct_id or str(user.uuid)
        cache_key = _cache_key(distinct_id, days)

        if not refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

        team_id = _internal_team_id()
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            logger.exception("posthog_code_spend.team_missing", team_id=team_id)
            raise exceptions.NotFound("Internal analytics team is not provisioned on this deployment.")

        payload = {
            "summary": _fetch_summary(team, email, days),
            "by_product": _fetch_by_product(team, email, days),
            "by_tool": _fetch_by_tool(team, email, days),
            "by_model": _fetch_by_model(team, email, days),
            "top_traces": _fetch_top_traces(team, email, days),
        }

        response_data = TokenSpendAnalysisResponseSerializer(payload).data
        cache.set(cache_key, response_data, timeout=CACHE_TIMEOUT_SECONDS)
        return Response(response_data, status=status.HTTP_200_OK)
