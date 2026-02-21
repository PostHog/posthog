"""On-demand sentiment analysis for LLM traces.

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
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import LLMAnalyticsSentimentBurstThrottle, LLMAnalyticsSentimentSustainedThrottle
from posthog.temporal.common.client import sync_connect
from posthog.temporal.llm_analytics.sentiment.constants import (
    BATCH_MAX_TRACE_IDS,
    CACHE_TTL,
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


class LLMAnalyticsSentimentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]
    throttle_classes = [
        LLMAnalyticsSentimentBurstThrottle,
        LLMAnalyticsSentimentSustainedThrottle,
    ]

    def _get_cache_key(self, trace_id: str) -> str:
        return f"llm_sentiment:{self.team_id}:{trace_id}"

    def _execute_workflow(
        self,
        client,
        trace_ids: list[str],
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, dict]:
        workflow_input = ClassifySentimentInput(
            team_id=self.team_id,
            trace_ids=trace_ids,
            date_from=date_from,
            date_to=date_to,
        )
        workflow_id = f"llma-sentiment-{self.team_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        return asyncio.run(
            client.execute_workflow(
                WORKFLOW_NAME,
                workflow_input,
                id=workflow_id,
                task_queue=settings.LLMA_TASK_QUEUE,
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
            cache_keys = {tid: self._get_cache_key(tid) for tid in trace_ids}
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
                    date_from=date_from,
                    date_to=date_to,
                )

                to_cache: dict[str, dict] = {}
                for tid in misses:
                    trace_result = batch_results.get(tid)
                    if trace_result:
                        results[tid] = trace_result
                        to_cache[self._get_cache_key(tid)] = trace_result
                    else:
                        results[tid] = {"error": "Failed to compute sentiment"}

                if to_cache:
                    cache.set_many(to_cache, timeout=CACHE_TTL)

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
