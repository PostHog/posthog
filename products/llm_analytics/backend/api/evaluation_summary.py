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

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.event_usage import report_user_action
from posthog.models import Team, User
from posthog.permissions import AccessControlPermission
from posthog.rate_limit import (
    LLMAnalyticsSummarizationBurstThrottle,
    LLMAnalyticsSummarizationDailyThrottle,
    LLMAnalyticsSummarizationSustainedThrottle,
)

from products.llm_analytics.backend.api.metrics import llma_track_latency
from products.llm_analytics.backend.models.evaluations import Evaluation
from products.llm_analytics.backend.summarization.constants import EVALUATION_SUMMARY_MAX_RUNS
from products.llm_analytics.backend.summarization.llm.evaluation_summary import summarize_evaluation_runs
from products.llm_analytics.backend.summarization.models import OpenAIModel

logger = structlog.get_logger(__name__)


class EvaluationSummaryRequestSerializer(serializers.Serializer):
    """Request serializer for evaluation summary - accepts IDs only, fetches data server-side."""

    evaluation_id = serializers.UUIDField(help_text="UUID of the evaluation config to summarize")
    filter = serializers.ChoiceField(
        choices=["all", "pass", "fail", "na"],
        default="all",
        required=False,
        help_text="Filter type to apply ('all', 'pass', 'fail', or 'na')",
    )
    generation_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        max_length=EVALUATION_SUMMARY_MAX_RUNS,
        help_text=f"Optional: specific generation IDs to include in summary (max {EVALUATION_SUMMARY_MAX_RUNS})",
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


def _fetch_evaluation_runs(
    team: Team,
    evaluation_id: str,
    filter_type: str = "all",
    generation_ids: list[str] | None = None,
    limit: int = EVALUATION_SUMMARY_MAX_RUNS,
) -> list[dict]:
    """
    Fetch evaluation runs from ClickHouse using HogQL.

    Args:
        team: Team object to query for
        evaluation_id: UUID of the evaluation config
        filter_type: Filter to apply ('all', 'pass', 'fail', 'na')
        generation_ids: Optional list of specific generation IDs to fetch
        limit: Maximum number of runs to return

    Returns:
        List of dicts with: generation_id, result, reasoning
    """
    # Build WHERE conditions using HogQL AST for safe parameterization
    where_conditions: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value="$ai_evaluation"),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["properties", "$ai_evaluation_id"]),
            right=ast.Constant(value=evaluation_id),
        ),
    ]

    # Add result filter conditions
    # Helper for "applicable is NULL or applicable != false" condition
    # This handles evaluations without N/A where applicable field is not set (NULL)
    def _applicable_or_null() -> ast.Expr:
        return ast.Or(
            exprs=[
                ast.Call(
                    name="isNull",
                    args=[ast.Field(chain=["properties", "$ai_evaluation_applicable"])],
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["properties", "$ai_evaluation_applicable"]),
                    right=ast.Constant(value=False),
                ),
            ]
        )

    if filter_type == "pass":
        where_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", "$ai_evaluation_result"]),
                right=ast.Constant(value=True),
            )
        )
        where_conditions.append(_applicable_or_null())
    elif filter_type == "fail":
        where_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", "$ai_evaluation_result"]),
                right=ast.Constant(value=False),
            )
        )
        where_conditions.append(_applicable_or_null())
    elif filter_type == "na":
        where_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", "$ai_evaluation_applicable"]),
                right=ast.Constant(value=False),
            )
        )

    # Add generation_ids filter if provided
    if generation_ids:
        where_conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["properties", "$ai_target_event_id"]),
                right=ast.Tuple(exprs=[ast.Constant(value=str(gid)) for gid in generation_ids]),
            )
        )

    query = parse_select(
        """
        SELECT
            properties.$ai_target_event_id as generation_id,
            properties.$ai_evaluation_result as result,
            properties.$ai_evaluation_reasoning as reasoning,
            properties.$ai_evaluation_applicable as applicable
        FROM events
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT {limit}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS):
        query_result = execute_hogql_query(
            query_type="EvaluationSummaryFetchRuns",
            query=query,
            placeholders={
                "where_clause": ast.And(exprs=where_conditions),
                "limit": ast.Constant(value=limit),
            },
            team=team,
        )

    # Transform to expected format
    # Columns: generation_id (0), result (1), reasoning (2), applicable (3)
    return [
        {
            "generation_id": str(row[0]) if row[0] else "",
            "result": None if row[3] is False else row[1],
            "reasoning": row[2] or "",
        }
        for row in (query_result.results or [])
    ]


class LLMEvaluationSummaryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    ViewSet for LLM evaluation results summarization.

    Provides AI-powered analysis of evaluation runs to identify patterns
    in passing and failing evaluations. Fetches data server-side by ID
    to prevent client-side data manipulation.
    """

    scope_object = "llm_analytics"
    permission_classes = [AccessControlPermission]

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
        the underlying runs have changed. Uses SHA256 for collision resistance.
        """
        # Sort generation_ids for consistent hashing
        generation_ids = sorted(r["generation_id"] for r in runs)
        runs_hash = hashlib.sha256(",".join(generation_ids).encode()).hexdigest()[:12]
        return f"llm_eval_summary:{self.team_id}:{evaluation_id}:{filter_type}:{runs_hash}"

    @extend_schema(
        request=EvaluationSummaryRequestSerializer,
        responses={
            200: EvaluationSummaryResponseSerializer,
            400: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        examples=[
            OpenApiExample(
                "Evaluation Summary Request",
                description="Summarize evaluation results by ID",
                value={
                    "evaluation_id": "550e8400-e29b-41d4-a716-446655440000",
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
                    "na_patterns": [],
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

Data is fetched server-side by evaluation ID to ensure data integrity.

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
            evaluation_id = str(serializer.validated_data["evaluation_id"])
            filter_type = serializer.validated_data.get("filter", "all")
            generation_ids = serializer.validated_data.get("generation_ids")
            force_refresh = serializer.validated_data.get("force_refresh", False)

            # Convert UUIDs to strings if provided
            generation_id_strs: list[str] | None = None
            if generation_ids:
                generation_id_strs = [str(gid) for gid in generation_ids]

            # Fetch evaluation config from Postgres
            try:
                evaluation = Evaluation.objects.get(
                    id=evaluation_id,
                    team_id=self.team_id,
                    deleted=False,
                )
            except Evaluation.DoesNotExist:
                return Response(
                    {"error": f"Evaluation {evaluation_id} not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Fetch evaluation runs from ClickHouse using HogQL
            runs = _fetch_evaluation_runs(
                team=self.team,
                evaluation_id=evaluation_id,
                filter_type=filter_type,
                generation_ids=generation_id_strs,
                limit=EVALUATION_SUMMARY_MAX_RUNS,
            )

            if len(runs) == 0:
                return Response(
                    {"error": "No evaluation runs found for the specified criteria"},
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

            user = cast(User, self.request.user)
            start_time = time.time()
            summary = async_to_sync(summarize_evaluation_runs)(
                evaluation_runs=runs,
                team_id=self.team_id,
                model=OpenAIModel.GPT_5_MINI,
                filter_type=filter_type,
                evaluation_name=evaluation.name,
                evaluation_description=evaluation.description or "",
                evaluation_prompt=evaluation.evaluation_config.get("prompt", ""),
                user_distinct_id=user.distinct_id or "",
            )
            duration_seconds = time.time() - start_time

            result = summary.model_dump()

            # Override LLM-generated stats with ground truth computed from fetched data
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
                user,
                "llma evaluation summary generated",
                {
                    "evaluation_id": evaluation_id,
                    "runs_count": len(runs),
                    "filter": filter_type,
                    "duration_seconds": duration_seconds,
                    "force_refresh": force_refresh,
                    "pass_count": result["statistics"]["pass_count"],
                    "fail_count": result["statistics"]["fail_count"],
                    "na_count": result["statistics"]["na_count"],
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
