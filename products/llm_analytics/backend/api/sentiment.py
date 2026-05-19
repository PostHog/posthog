"""On-demand sentiment analysis for LLM traces and generations.

Triggers a Temporal workflow to classify sentiment on $ai_generation user messages
and returns the result synchronously (blocks until Temporal completes).
"""

import time
import uuid
import asyncio
from collections import namedtuple
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.schema import HogQLFilters

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import LLMAnalyticsSentimentBurstThrottle, LLMAnalyticsSentimentSustainedThrottle
from posthog.temporal.common.client import sync_connect
from posthog.temporal.llm_analytics.sentiment.constants import (
    BATCH_MAX_GENERATION_IDS,
    BATCH_MAX_TRACE_IDS,
    CACHE_KEY_PREFIX,
    MAX_RETRY_ATTEMPTS,
    WORKFLOW_NAME,
    WORKFLOW_TIMEOUT_BATCH_SECONDS,
)
from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput

from products.llm_analytics.backend.api.metrics import llma_track_latency

# Maximum rows returned from sentiment_generations.sql per call. Matches the
# frontend's GENERATIONS_PAGE_SIZE so a single page request gets the full slice
# in one round-trip. Baked into `_SENTIMENT_GENERATIONS_SQL` at import time
# below so this is the single source of truth.
GENERATIONS_QUERY_LIMIT = 200

logger = structlog.get_logger(__name__)

ANALYSIS_LEVEL_CHOICES = ["trace", "generation"]
BATCH_MAX_BY_LEVEL = {
    "trace": BATCH_MAX_TRACE_IDS,
    "generation": BATCH_MAX_GENERATION_IDS,
}


class SentimentRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=BATCH_MAX_GENERATION_IDS,
        required=True,
        help_text="Trace IDs (analysis_level=trace) or generation event UUIDs (analysis_level=generation).",
    )
    analysis_level = serializers.ChoiceField(
        choices=ANALYSIS_LEVEL_CHOICES,
        default="trace",
        required=False,
        help_text="Whether the IDs are 'trace' IDs or 'generation' IDs.",
    )
    force_refresh = serializers.BooleanField(
        default=False,
        required=False,
        help_text="If true, bypass cache and reclassify.",
    )
    date_from = serializers.CharField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Start of date range for the lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d.",
    )
    date_to = serializers.CharField(
        required=False,
        default=None,
        allow_null=True,
        help_text="End of date range for the lookup. Defaults to now.",
    )


class MessageSentimentSerializer(serializers.Serializer):
    label = serializers.CharField()  # type: ignore[assignment]
    score = serializers.FloatField()
    scores = serializers.DictField(child=serializers.FloatField())


class SentimentResultSerializer(serializers.Serializer):
    label = serializers.CharField()  # type: ignore[assignment]
    score = serializers.FloatField()
    scores = serializers.DictField(child=serializers.FloatField())
    messages = serializers.DictField(child=MessageSentimentSerializer())
    message_count = serializers.IntegerField()


class SentimentBatchResponseSerializer(serializers.Serializer):
    results = serializers.DictField(child=SentimentResultSerializer())


# Preflight runs against `events` (not `posthog.ai_events`): the events sort
# key starts `(team_id, toDate(timestamp), event)` so date filtering prunes
# granules cheaply, while ai_events is `(team_id, trace_id, timestamp)` —
# unusable for date pruning until trace_id is bounded.
_SENTIMENT_GENERATIONS_PREFLIGHT_SQL = f"""
SELECT
    argMax(uuid, timestamp) as uuid,
    properties.$ai_trace_id as trace_id,
    argMax(properties.$ai_model, timestamp) as model,
    argMax(distinct_id, timestamp) as distinct_id,
    max(timestamp) as timestamp,
    min(timestamp) as created_at
FROM events
WHERE event = '$ai_generation'
    AND length(coalesce(properties.$ai_trace_id, '')) > 0
    AND {{filters}}
GROUP BY trace_id
ORDER BY timestamp DESC, trace_id DESC
LIMIT {GENERATIONS_QUERY_LIMIT}
"""

_SENTIMENT_GENERATIONS_HEAVY_SQL = """
SELECT
    trace_id,
    argMax(input, timestamp) as ai_input
FROM posthog.ai_events AS ai_events
WHERE event = '$ai_generation'
    AND trace_id IN {trace_ids}
    AND uuid IN {uuids}
    AND timestamp >= {ts_start}
    AND timestamp <= {ts_end}
GROUP BY trace_id
"""

_PreflightRow = namedtuple("_PreflightRow", ["uuid", "trace_id", "model", "distinct_id", "timestamp", "created_at"])


class SentimentGenerationsRequestSerializer(serializers.Serializer):
    """Filter shape mirrors the previous frontend `api.query({filters: ...})` payload.

    `filters` accepts the same `HogQLFilters` schema that the legacy frontend HogQL
    path used (dateRange, filterTestAccounts, properties), so the migration is
    behaviour-preserving for callers that pass a request unchanged.
    """

    filters = serializers.JSONField(required=False, default=dict)


class SentimentGenerationsRowSerializer(serializers.Serializer):
    uuid = serializers.CharField(allow_null=True)
    trace_id = serializers.CharField(allow_null=True)
    ai_input = serializers.JSONField(allow_null=True)
    model = serializers.CharField(allow_null=True)
    distinct_id = serializers.CharField(allow_null=True)
    timestamp = serializers.CharField(allow_null=True)
    created_at = serializers.CharField(allow_null=True)


class SentimentGenerationsResponseSerializer(serializers.Serializer):
    # Shape kept tuple-style to match the existing frontend transformer (see
    # `llmAnalyticsSentimentLogic.ts::fetchGenerations`); positions:
    # [uuid, trace_id, ai_input, model, distinct_id, timestamp, created_at].
    results = serializers.ListField(child=serializers.ListField())


class LLMAnalyticsSentimentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]
    throttle_classes = [
        LLMAnalyticsSentimentBurstThrottle,
        LLMAnalyticsSentimentSustainedThrottle,
    ]

    def _cache_key(self, level: str, id_: str) -> str:
        return f"{CACHE_KEY_PREFIX}:{level}:{self.team_id}:{id_}"

    def _execute_workflow(
        self,
        client,
        ids: list[str],
        analysis_level: str = "trace",
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, dict]:
        workflow_input = ClassifySentimentInput(
            team_id=self.team_id,
            ids=ids,
            analysis_level=analysis_level,
            date_from=date_from,
            date_to=date_to,
        )
        workflow_id = f"llma-sentiment-{self.team_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        return asyncio.run(
            client.execute_workflow(
                WORKFLOW_NAME,
                workflow_input,
                id=workflow_id,
                task_queue=settings.LLMA_SENTIMENT_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=MAX_RETRY_ATTEMPTS),
                task_timeout=timedelta(seconds=WORKFLOW_TIMEOUT_BATCH_SECONDS),
            )
        )

    @extend_schema(
        request=SentimentRequestSerializer,
        responses={
            200: SentimentBatchResponseSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        tags=["LLM Analytics"],
    )
    @llma_track_latency("llma_sentiment_create")
    @monitor(feature=None, endpoint="llma_sentiment_create", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        serializer = SentimentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ids: list[str] = serializer.validated_data["ids"]
        analysis_level: str = serializer.validated_data["analysis_level"]
        force_refresh: bool = serializer.validated_data["force_refresh"]
        date_from: str | None = serializer.validated_data.get("date_from")
        date_to: str | None = serializer.validated_data.get("date_to")

        max_size = BATCH_MAX_BY_LEVEL[analysis_level]
        if len(ids) > max_size:
            return Response(
                {"ids": [f"Ensure this field has no more than {max_size} elements."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results: dict[str, dict] = {}
        misses: list[str] = []

        if not force_refresh:
            cache_keys = {id_: self._cache_key(analysis_level, id_) for id_ in ids}
            cached_values = cache.get_many(list(cache_keys.values()))

            for id_ in ids:
                cached = cached_values.get(cache_keys[id_])
                if cached is not None:
                    results[id_] = cached
                else:
                    misses.append(id_)
        else:
            misses = list(ids)

        if misses:
            try:
                client = sync_connect()
                batch_results = self._execute_workflow(
                    client,
                    misses,
                    analysis_level=analysis_level,
                    date_from=date_from,
                    date_to=date_to,
                )

                for id_ in misses:
                    result = batch_results.get(id_)
                    if result:
                        results[id_] = result
                    else:
                        results[id_] = {"error": "Failed to compute sentiment"}

            except Exception as e:
                logger.exception(
                    "Failed to compute sentiment",
                    team_id=self.team_id,
                    analysis_level=analysis_level,
                    ids=misses,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to compute sentiment"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response({"results": results}, status=status.HTTP_200_OK)

    @extend_schema(
        request=SentimentGenerationsRequestSerializer,
        responses={
            200: SentimentGenerationsResponseSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        tags=["LLM Analytics"],
    )
    @action(detail=False, methods=["post"], url_path="generations")
    @llma_track_latency("llma_sentiment_generations")
    @monitor(feature=None, endpoint="llma_sentiment_generations", method="POST")
    def generations(self, request: Request, **kwargs) -> Response:
        serializer = SentimentGenerationsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        filters_payload = serializer.validated_data.get("filters") or {}
        # Narrow to pydantic's ValidationError so unrelated 500s (e.g. a future
        # import shift making `HogQLFilters` resolve to None) surface as 500
        # rather than getting masked as a 400. Heavy property filters (`$ai_input`
        # etc.) would read as NULL on the dedicated path — assumed not exposed
        # in the sentiment-tab UI's property picker, which only surfaces
        # non-heavy props.
        try:
            filters = HogQLFilters.model_validate(filters_payload)
        except PydanticValidationError as e:
            # `e.errors()` is a structured list of pydantic error dicts — safe to
            # serialize and free of stack-trace context. `str(e)` would surface
            # the full exception representation (CodeQL flagged it as info exposure).
            return Response({"filters": e.errors()}, status=status.HTTP_400_BAD_REQUEST)

        preflight_query = replace_filters(parse_select(_SENTIMENT_GENERATIONS_PREFLIGHT_SQL), filters, self.team)

        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=self.team_id):
            try:
                preflight_result = execute_hogql_query(
                    query=preflight_query,
                    placeholders={},
                    team=self.team,
                    query_type="LLMSentimentGenerationsTraceIdResolve",
                    limit_context=LimitContext.QUERY,
                )
            except Exception as e:
                logger.exception(
                    "Failed to resolve sentiment generations trace_ids",
                    team_id=self.team_id,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to fetch sentiment generations"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            preflight_rows = [_PreflightRow(*row) for row in (preflight_result.results or [])]
            if not preflight_rows:
                return Response({"results": []}, status=status.HTTP_200_OK)

            trace_ids = [str(row.trace_id) for row in preflight_rows]
            uuids = [str(row.uuid) for row in preflight_rows]
            ts_start = min(row.created_at for row in preflight_rows)
            ts_end = max(row.timestamp for row in preflight_rows)

            heavy_query = parse_select(_SENTIMENT_GENERATIONS_HEAVY_SQL)
            try:
                heavy_result = execute_with_ai_events_fallback(
                    query=heavy_query,
                    placeholders={
                        "trace_ids": ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids]),
                        "uuids": ast.Tuple(exprs=[ast.Constant(value=u) for u in uuids]),
                        "ts_start": ast.Constant(value=ts_start),
                        "ts_end": ast.Constant(value=ts_end),
                    },
                    team=self.team,
                    query_type="LLMSentimentGenerations",
                    limit_context=LimitContext.QUERY,
                )
            except Exception as e:
                logger.exception(
                    "Failed to fetch sentiment generations",
                    team_id=self.team_id,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to fetch sentiment generations"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        ai_input_by_trace = {str(trace_id): ai_input for trace_id, ai_input in (heavy_result.results or [])}
        results = [
            [
                row.uuid,
                row.trace_id,
                ai_input_by_trace.get(str(row.trace_id)),
                row.model,
                row.distinct_id,
                row.timestamp,
                row.created_at,
            ]
            for row in preflight_rows
        ]
        return Response({"results": results}, status=status.HTTP_200_OK)
