"""On-demand sentiment analysis for LLM traces and generations.

Triggers a Temporal workflow to classify sentiment on $ai_generation user messages
and returns the result synchronously (blocks until Temporal completes).
"""

import time
import uuid
import asyncio
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
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

logger = structlog.get_logger(__name__)


class SentimentRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=BATCH_MAX_TRACE_IDS,
        required=True,
    )
    force_refresh = serializers.BooleanField(default=False, required=False)
    date_from = serializers.CharField(required=False, default=None, allow_null=True)
    date_to = serializers.CharField(required=False, default=None, allow_null=True)


class MessageSentimentSerializer(serializers.Serializer):
    label = serializers.CharField()  # type: ignore[assignment]
    score = serializers.FloatField()
    scores = serializers.DictField(child=serializers.FloatField())


class GenerationSentimentSerializer(serializers.Serializer):
    label = serializers.CharField()  # type: ignore[assignment]
    score = serializers.FloatField()
    scores = serializers.DictField(child=serializers.FloatField())
    messages = serializers.DictField(child=MessageSentimentSerializer())


class SentimentResponseSerializer(serializers.Serializer):
    trace_id = serializers.CharField()
    label = serializers.CharField()  # type: ignore[assignment]
    score = serializers.FloatField()
    scores = serializers.DictField(child=serializers.FloatField())
    generations = serializers.DictField(child=GenerationSentimentSerializer())
    generation_count = serializers.IntegerField()
    message_count = serializers.IntegerField()


class SentimentBatchResponseSerializer(serializers.Serializer):
    results = serializers.DictField(child=SentimentResponseSerializer())


class GenerationSentimentRequestSerializer(serializers.Serializer):
    generation_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=BATCH_MAX_GENERATION_IDS,
        required=True,
    )
    force_refresh = serializers.BooleanField(default=False, required=False)
    date_from = serializers.CharField(required=False, default=None, allow_null=True)
    date_to = serializers.CharField(required=False, default=None, allow_null=True)


class GenerationSentimentBatchResponseSerializer(serializers.Serializer):
    results = serializers.DictField(child=GenerationSentimentSerializer())


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

        trace_ids: list[str] = serializer.validated_data["trace_ids"]
        force_refresh: bool = serializer.validated_data["force_refresh"]
        date_from: str | None = serializer.validated_data.get("date_from")
        date_to: str | None = serializer.validated_data.get("date_to")

        results: dict[str, dict] = {}
        misses: list[str] = []

        if not force_refresh:
            cache_keys = {tid: self._cache_key("trace", tid) for tid in trace_ids}
            cached_values = cache.get_many(list(cache_keys.values()))

            for tid in trace_ids:
                cached = cached_values.get(cache_keys[tid])
                if cached is not None:
                    results[tid] = cached
                else:
                    misses.append(tid)
        else:
            misses = list(trace_ids)

        if misses:
            try:
                client = sync_connect()
                batch_results = self._execute_workflow(
                    client,
                    misses,
                    analysis_level="trace",
                    date_from=date_from,
                    date_to=date_to,
                )

                for tid in misses:
                    trace_result = batch_results.get(tid)
                    if trace_result:
                        results[tid] = trace_result
                    else:
                        results[tid] = {"error": "Failed to compute sentiment"}

            except Exception as e:
                logger.exception(
                    "Failed to compute sentiment",
                    team_id=self.team_id,
                    trace_ids=misses,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to compute sentiment"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response({"results": results}, status=status.HTTP_200_OK)

    @extend_schema(
        request=GenerationSentimentRequestSerializer,
        responses={
            200: GenerationSentimentBatchResponseSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        tags=["LLM Analytics"],
    )
    @action(detail=False, methods=["post"], url_path="generations")
    @llma_track_latency("llma_sentiment_generations")
    @monitor(feature=None, endpoint="llma_sentiment_generations", method="POST")
    def generations(self, request: Request, **kwargs) -> Response:
        serializer = GenerationSentimentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        generation_ids: list[str] = serializer.validated_data["generation_ids"]
        force_refresh: bool = serializer.validated_data["force_refresh"]
        date_from: str | None = serializer.validated_data.get("date_from")
        date_to: str | None = serializer.validated_data.get("date_to")

        results: dict[str, dict] = {}
        misses: list[str] = []

        if not force_refresh:
            cache_keys = {gid: self._cache_key("generation", gid) for gid in generation_ids}
            cached_values = cache.get_many(list(cache_keys.values()))

            for gid in generation_ids:
                cached = cached_values.get(cache_keys[gid])
                if cached is not None:
                    results[gid] = cached
                else:
                    misses.append(gid)
        else:
            misses = list(generation_ids)

        if misses:
            try:
                client = sync_connect()
                batch_results = self._execute_workflow(
                    client,
                    misses,
                    analysis_level="generation",
                    date_from=date_from,
                    date_to=date_to,
                )

                for gid in misses:
                    gen_result = batch_results.get(gid)
                    if gen_result:
                        results[gid] = gen_result
                    else:
                        results[gid] = {"error": "Failed to compute sentiment"}

            except Exception as e:
                logger.exception(
                    "Failed to compute generation sentiment",
                    team_id=self.team_id,
                    generation_ids=misses,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to compute generation sentiment"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response({"results": results}, status=status.HTTP_200_OK)
