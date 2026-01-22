"""
Django REST API endpoint for LLM evaluation results summarization.

This ViewSet provides AI-powered summarization of evaluation results,
identifying patterns in passing and failing evaluations.

Endpoints:
- POST /api/environments/:id/llm_analytics/evaluation_summary/ - Summarize evaluation runs
"""

import time
import hashlib
from typing import cast

from django.core.cache import cache

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.rate_limit import (
    LLMAnalyticsSummarizationBurstThrottle,
    LLMAnalyticsSummarizationDailyThrottle,
    LLMAnalyticsSummarizationSustainedThrottle,
)

from products.llm_analytics.backend.api.metrics import llma_track_latency
from products.llm_analytics.backend.summarization.llm.evaluation_summary import summarize_evaluation_runs
from products.llm_analytics.backend.summarization.models import OpenAIModel

logger = structlog.get_logger(__name__)


class EvaluationRunDataSerializer(serializers.Serializer):
    generation_id = serializers.CharField(help_text="Unique identifier for the generation being evaluated")
    result = serializers.BooleanField(
        allow_null=True,
        help_text="Whether the evaluation passed (true), failed (false), or was N/A (null)",
    )
    reasoning = serializers.CharField(help_text="The LLM judge's explanation for the result")


class EvaluationSummaryRequestSerializer(serializers.Serializer):
    evaluation_id = serializers.CharField(help_text="Unique identifier for the evaluation being summarized")
    evaluation_runs = serializers.ListField(
        child=EvaluationRunDataSerializer(),
        min_length=1,
        max_length=100,
        help_text="List of evaluation runs to summarize (max 100)",
    )
    filter = serializers.ChoiceField(
        choices=["all", "pass", "fail", "na"],
        default="all",
        required=False,
        help_text="Filter type that was applied ('all', 'pass', 'fail', or 'na')",
    )
    force_refresh = serializers.BooleanField(
        default=False,
        required=False,
        help_text="If true, bypass cache and generate a fresh summary",
    )


class EvaluationPatternSerializer(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField()
    frequency = serializers.CharField()
    example_reasoning = serializers.CharField()
    example_generation_ids = serializers.ListField(child=serializers.CharField())


class EvaluationSummaryStatisticsSerializer(serializers.Serializer):
    total_analyzed = serializers.IntegerField()
    pass_count = serializers.IntegerField()
    fail_count = serializers.IntegerField()
    na_count = serializers.IntegerField()


class EvaluationSummaryResponseSerializer(serializers.Serializer):
    overall_assessment = serializers.CharField()
    pass_patterns = EvaluationPatternSerializer(many=True)
    fail_patterns = EvaluationPatternSerializer(many=True)
    na_patterns = EvaluationPatternSerializer(many=True)
    recommendations = serializers.ListField(child=serializers.CharField())
    statistics = EvaluationSummaryStatisticsSerializer()


class LLMEvaluationSummaryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for LLM evaluation results summarization.

    Provides AI-powered analysis of evaluation runs to identify patterns
    in passing and failing evaluations.
    """

    scope_object = "llm_analytics"  # type: ignore[assignment]

    def get_throttles(self):
        """Apply rate limiting to prevent abuse of summarization endpoint."""
        return [
            LLMAnalyticsSummarizationBurstThrottle(),
            LLMAnalyticsSummarizationSustainedThrottle(),
            LLMAnalyticsSummarizationDailyThrottle(),
        ]

    # Cache timeout in seconds (1 hour)
    CACHE_TIMEOUT = 3600

    def _validate_feature_access(self, request: Request) -> None:
        """Validate that the user is authenticated and AI data processing is approved."""
        if not request.user.is_authenticated:
            raise exceptions.NotAuthenticated()

        if not self.organization.is_ai_data_processing_approved:
            raise exceptions.PermissionDenied(
                "AI data processing must be approved by your organization before using summarization"
            )

    def _get_cache_key(self, evaluation_id: str, filter_type: str, runs: list[dict]) -> str:
        """Generate cache key for evaluation summary results.

        The key includes a hash of the generation_ids to detect when
        the underlying runs have changed.
        """
        # Sort generation_ids for consistent hashing
        generation_ids = sorted(r["generation_id"] for r in runs)
        runs_hash = hashlib.md5(",".join(generation_ids).encode()).hexdigest()[:12]
        return f"llm_eval_summary:{self.team_id}:{evaluation_id}:{filter_type}:{runs_hash}"

    @extend_schema(
        request=EvaluationSummaryRequestSerializer,
        responses={
            200: EvaluationSummaryResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Evaluation Summary Request",
                description="Summarize evaluation results",
                value={
                    "evaluation_id": "eval_12345",
                    "evaluation_runs": [
                        {
                            "generation_id": "gen_abc123",
                            "result": True,
                            "reasoning": "Response was accurate and helpful",
                        },
                        {
                            "generation_id": "gen_def456",
                            "result": False,
                            "reasoning": "Response contained factual errors",
                        },
                        {
                            "generation_id": "gen_ghi789",
                            "result": True,
                            "reasoning": "Good formatting and clear explanation",
                        },
                    ],
                    "filter": "all",
                    "force_refresh": False,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Success Response",
                value={
                    "overall_assessment": "Evaluations show generally good quality with some factual accuracy issues.",
                    "pass_patterns": [
                        {
                            "title": "Clear Communication",
                            "description": "Responses consistently provided well-structured information",
                            "frequency": "common",
                            "example_reasoning": "Good formatting and clear explanation",
                            "example_generation_ids": ["gen_abc123", "gen_ghi789"],
                        }
                    ],
                    "fail_patterns": [
                        {
                            "title": "Factual Errors",
                            "description": "Some responses contained inaccurate information",
                            "frequency": "occasional",
                            "example_reasoning": "Response contained factual errors",
                            "example_generation_ids": ["gen_def456"],
                        }
                    ],
                    "recommendations": [
                        "Implement fact-checking for critical claims",
                        "Add source citations where applicable",
                    ],
                    "statistics": {"total_analyzed": 3, "pass_count": 2, "fail_count": 1, "na_count": 0},
                },
                response_only=True,
                status_codes=["200"],
            ),
        ],
        description="""
Generate an AI-powered summary of evaluation results.

This endpoint analyzes evaluation runs and identifies patterns in passing
and failing evaluations, providing actionable recommendations.

**Use Cases:**
- Understand why evaluations are passing or failing
- Identify systematic issues in LLM responses
- Get recommendations for improving response quality
- Review patterns across many evaluation runs at once
        """,
        tags=["LLM Analytics"],
    )
    @llma_track_latency("llma_evaluation_summary")
    @monitor(feature=None, endpoint="llma_evaluation_summary", method="POST")
    def create(self, request: Request, **kwargs) -> Response:
        """
        Summarize evaluation runs.

        POST /api/environments/:id/llm_analytics/evaluation_summary/
        """
        self._validate_feature_access(request)

        serializer = EvaluationSummaryRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            evaluation_id = serializer.validated_data["evaluation_id"]
            runs = serializer.validated_data["evaluation_runs"]
            filter_type = serializer.validated_data.get("filter", "all")
            force_refresh = serializer.validated_data.get("force_refresh", False)

            if len(runs) == 0:
                return Response(
                    {"error": "No evaluation runs to summarize"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            cache_key = self._get_cache_key(evaluation_id, filter_type, runs)

            # Check cache unless force_refresh is requested
            if not force_refresh:
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    logger.info(
                        "Returning cached evaluation summary",
                        evaluation_id=evaluation_id,
                        filter_type=filter_type,
                        team_id=self.team_id,
                    )
                    return Response(cached_result, status=status.HTTP_200_OK)

            start_time = time.time()
            summary = async_to_sync(summarize_evaluation_runs)(
                evaluation_runs=runs,
                team_id=self.team_id,
                model=OpenAIModel.GPT_5_MINI,
                filter_type=filter_type,
            )
            duration_seconds = time.time() - start_time

            result = summary.model_dump()

            # Override LLM-generated stats with ground truth computed from input
            result["statistics"] = {
                "total_analyzed": len(runs),
                "pass_count": sum(1 for r in runs if r["result"] is True),
                "fail_count": sum(1 for r in runs if r["result"] is False),
                "na_count": sum(1 for r in runs if r["result"] is None),
            }

            # Cache the result
            cache.set(cache_key, result, timeout=self.CACHE_TIMEOUT)

            logger.info(
                "Generated and cached evaluation summary",
                evaluation_id=evaluation_id,
                team_id=self.team_id,
                runs_count=len(runs),
                filter_type=filter_type,
                duration_seconds=duration_seconds,
                force_refresh=force_refresh,
            )

            report_user_action(
                cast(User, self.request.user),
                "llma evaluation summary generated",
                {
                    "evaluation_id": evaluation_id,
                    "runs_count": len(runs),
                    "filter": filter_type,
                    "duration_seconds": duration_seconds,
                    "force_refresh": force_refresh,
                    "pass_count": result["statistics"]["pass_count"],
                    "fail_count": result["statistics"]["fail_count"],
                },
                self.team,
            )

            return Response(result, status=status.HTTP_200_OK)

        except exceptions.ValidationError:
            raise
        except Exception as e:
            logger.exception(
                "Failed to generate evaluation summary",
                team_id=self.team_id,
                error=str(e),
            )
            return Response(
                {"error": "Failed to generate summary", "detail": "An error occurred while generating the summary"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
