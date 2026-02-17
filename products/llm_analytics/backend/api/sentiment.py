"""On-demand sentiment analysis for LLM traces.

Triggers a Temporal workflow to classify sentiment on $ai_generation user messages
and returns the result synchronously (blocks until Temporal completes).
"""

import time
import asyncio
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache

import structlog
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import (
    LLMAnalyticsSentimentBatchBurstThrottle,
    LLMAnalyticsSentimentBatchSustainedThrottle,
    LLMAnalyticsSentimentBurstThrottle,
    LLMAnalyticsSentimentSustainedThrottle,
)
from posthog.temporal.common.client import sync_connect
from posthog.temporal.llm_analytics.sentiment.constants import (
    MAX_RETRY_ATTEMPTS,
    WORKFLOW_TIMEOUT_BATCH_SECONDS,
    WORKFLOW_TIMEOUT_SINGLE_SECONDS,
)
from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput

from products.llm_analytics.backend.api.metrics import llma_track_latency

logger = structlog.get_logger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24 hours — events are immutable once ingested
BATCH_MAX_TRACE_IDS = 25
WORKFLOW_NAME = "llma-sentiment-classify"


class SentimentRequestSerializer(serializers.Serializer):
    trace_id = serializers.CharField(required=True)
    force_refresh = serializers.BooleanField(default=False, required=False)
    date_from = serializers.CharField(required=False, default=None, allow_null=True)
    date_to = serializers.CharField(required=False, default=None, allow_null=True)


class SentimentBatchRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=BATCH_MAX_TRACE_IDS,
        required=True,
    )
    force_refresh = serializers.BooleanField(default=False, required=False)
    date_from = serializers.CharField(required=False, default=None, allow_null=True)
    date_to = serializers.CharField(required=False, default=None, allow_null=True)


class LLMAnalyticsSentimentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]

    def get_throttles(self):
        if self.action == "batch":
            return [
                LLMAnalyticsSentimentBatchBurstThrottle(),
                LLMAnalyticsSentimentBatchSustainedThrottle(),
            ]
        return [
            LLMAnalyticsSentimentBurstThrottle(),
            LLMAnalyticsSentimentSustainedThrottle(),
        ]

    def _get_cache_key(self, trace_id: str) -> str:
        return f"llm_sentiment:{self.team_id}:{trace_id}"

    def _execute_workflow(
        self,
        client,
        trace_ids: list[str],
        date_from: str | None = None,
        date_to: str | None = None,
        task_timeout: timedelta = timedelta(seconds=WORKFLOW_TIMEOUT_SINGLE_SECONDS),
    ) -> dict[str, dict]:
        workflow_input = ClassifySentimentInput(
            team_id=self.team_id,
            trace_ids=trace_ids,
            date_from=date_from,
            date_to=date_to,
        )
        import uuid

        workflow_id = f"llma-sentiment-{self.team_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"

        return asyncio.run(
            client.execute_workflow(
                WORKFLOW_NAME,
                workflow_input,
                id=workflow_id,
                task_queue=settings.LLMA_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=MAX_RETRY_ATTEMPTS),
                task_timeout=task_timeout,
            )
        )

    @llma_track_latency("llma_sentiment")
    @monitor(feature=None, endpoint="llma_sentiment", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        serializer = SentimentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        trace_id = serializer.validated_data["trace_id"]
        force_refresh = serializer.validated_data["force_refresh"]
        date_from = serializer.validated_data.get("date_from")
        date_to = serializer.validated_data.get("date_to")

        cache_key = self._get_cache_key(trace_id)
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

        try:
            client = sync_connect()
            results = self._execute_workflow(client, [trace_id], date_from=date_from, date_to=date_to)
            result = results[trace_id]

            cache.set(cache_key, result, timeout=CACHE_TTL)

            logger.info(
                "Sentiment computed",
                trace_id=trace_id,
                team_id=self.team_id,
                label=result.get("label"),
                generation_count=result.get("generation_count"),
                message_count=result.get("message_count"),
            )

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception(
                "Failed to compute sentiment",
                trace_id=trace_id,
                team_id=self.team_id,
                error=str(e),
            )
            return Response(
                {"error": "Failed to compute sentiment"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(methods=["POST"], detail=False, url_path="batch")
    @llma_track_latency("llma_sentiment_batch")
    @monitor(feature=None, endpoint="llma_sentiment_batch", method="POST")
    def batch(self, request: Request, **kwargs) -> Response:
        serializer = SentimentBatchRequestSerializer(data=request.data)
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
                    task_timeout=timedelta(seconds=WORKFLOW_TIMEOUT_BATCH_SECONDS),
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
                    "Failed to compute batch sentiment",
                    team_id=self.team_id,
                    trace_ids=misses,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to compute sentiment"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response({"results": results}, status=status.HTTP_200_OK)
