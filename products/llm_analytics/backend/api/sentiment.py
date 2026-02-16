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
from posthog.temporal.llm_analytics.sentiment.on_demand import OnDemandSentimentInput

from products.llm_analytics.backend.api.metrics import llma_track_latency

logger = structlog.get_logger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24 hours — events are immutable once ingested
BATCH_MAX_TRACE_IDS = 25


class SentimentRequestSerializer(serializers.Serializer):
    trace_id = serializers.CharField(required=True)
    force_refresh = serializers.BooleanField(default=False, required=False)


class SentimentBatchRequestSerializer(serializers.Serializer):
    trace_ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=BATCH_MAX_TRACE_IDS,
        required=True,
    )
    force_refresh = serializers.BooleanField(default=False, required=False)


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

    def _execute_workflow(self, client, trace_id: str) -> dict:
        workflow_input = OnDemandSentimentInput(
            team_id=self.team_id,
            trace_id=trace_id,
        )
        workflow_id = f"llma-sentiment-{self.team_id}-{trace_id}-{int(time.time() * 1000)}"

        return asyncio.run(
            client.execute_workflow(
                "llma-sentiment-on-demand",
                workflow_input,
                id=workflow_id,
                task_queue=settings.LLMA_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=2),
                task_timeout=timedelta(seconds=30),
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

        cache_key = self._get_cache_key(trace_id)
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached, status=status.HTTP_200_OK)

        try:
            client = sync_connect()
            result = self._execute_workflow(client, trace_id)

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

                async def _run_all():
                    tasks = []
                    for tid in misses:
                        workflow_input = OnDemandSentimentInput(
                            team_id=self.team_id,
                            trace_id=tid,
                        )
                        workflow_id = f"llma-sentiment-{self.team_id}-{tid}-{int(time.time() * 1000)}"
                        tasks.append(
                            client.execute_workflow(
                                "llma-sentiment-on-demand",
                                workflow_input,
                                id=workflow_id,
                                task_queue=settings.LLMA_TASK_QUEUE,
                                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                                retry_policy=RetryPolicy(maximum_attempts=2),
                                task_timeout=timedelta(seconds=30),
                            )
                        )
                    return await asyncio.gather(*tasks, return_exceptions=True)

                workflow_results = asyncio.run(_run_all())
            except Exception as e:
                logger.exception(
                    "Failed to connect to Temporal for batch sentiment",
                    team_id=self.team_id,
                    trace_ids=misses,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to compute sentiment"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            to_cache: dict[str, dict] = {}
            for tid, result in zip(misses, workflow_results):
                if isinstance(result, Exception):
                    logger.exception(
                        "Failed to compute sentiment in batch",
                        trace_id=tid,
                        team_id=self.team_id,
                        error=str(result),
                    )
                    results[tid] = {"error": "Failed to compute sentiment"}
                else:
                    results[tid] = result
                    to_cache[self._get_cache_key(tid)] = result

            if to_cache:
                cache.set_many(to_cache, timeout=CACHE_TTL)

        return Response({"results": results}, status=status.HTTP_200_OK)
