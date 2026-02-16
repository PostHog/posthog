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
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import LLMAnalyticsSentimentBurstThrottle, LLMAnalyticsSentimentSustainedThrottle
from posthog.temporal.common.client import sync_connect
from posthog.temporal.llm_analytics.sentiment.on_demand import OnDemandSentimentInput

from products.llm_analytics.backend.api.metrics import llma_track_latency

logger = structlog.get_logger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24 hours — events are immutable once ingested


class SentimentRequestSerializer(serializers.Serializer):
    trace_id = serializers.CharField(required=True)
    force_refresh = serializers.BooleanField(default=False, required=False)


class LLMAnalyticsSentimentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]

    def get_throttles(self):
        return [
            LLMAnalyticsSentimentBurstThrottle(),
            LLMAnalyticsSentimentSustainedThrottle(),
        ]

    def _get_cache_key(self, trace_id: str) -> str:
        return f"llm_sentiment:{self.team_id}:{trace_id}"

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

        workflow_input = OnDemandSentimentInput(
            team_id=self.team_id,
            trace_id=trace_id,
        )
        workflow_id = f"llma-sentiment-{self.team_id}-{trace_id}-{int(time.time() * 1000)}"

        try:
            client = sync_connect()
            result = asyncio.run(
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
