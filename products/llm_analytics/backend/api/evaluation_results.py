from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.permissions import AccessControlPermission

from products.llm_analytics.backend.api.metrics import llma_track_latency

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class EvaluationResultSerializer(serializers.Serializer):
    uuid = serializers.CharField(read_only=True)
    timestamp = serializers.DateTimeField(read_only=True)
    evaluation_id = serializers.CharField(read_only=True)
    evaluation_name = serializers.CharField(read_only=True)
    generation_id = serializers.CharField(read_only=True)
    trace_id = serializers.CharField(read_only=True, allow_null=True)
    result = serializers.BooleanField(read_only=True, allow_null=True)
    reasoning = serializers.CharField(read_only=True, allow_null=True)
    applicable = serializers.BooleanField(read_only=True, allow_null=True)


class EvaluationResultsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Query evaluation results ($ai_evaluation events).

    GET /api/environments/:id/llm_analytics/evaluation_results/
        ?evaluation_id=<uuid>       Filter by evaluation UUID
        &generation_id=<uuid>       Filter by generation event UUID
        &result=pass|fail|na        Filter by result status
        &limit=50                   Max results (default 50, max 200)
    """

    scope_object = "evaluation"
    permission_classes = [IsAuthenticated, AccessControlPermission]
    serializer_class = EvaluationResultSerializer

    @llma_track_latency("llma_evaluation_results_list")
    @monitor(feature=None, endpoint="llma_evaluation_results_list", method="GET")
    def list(self, request: Request, **kwargs) -> Response:
        evaluation_id = request.query_params.get("evaluation_id")
        generation_id = request.query_params.get("generation_id")
        result_filter = request.query_params.get("result")
        try:
            limit = min(int(request.query_params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
        except (ValueError, TypeError):
            return Response({"error": "limit must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        if not evaluation_id and not generation_id:
            return Response(
                {"error": "At least one of evaluation_id or generation_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        where_conditions: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$ai_evaluation"),
            ),
        ]

        if evaluation_id:
            where_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$ai_evaluation_id"]),
                    right=ast.Constant(value=evaluation_id),
                )
            )

        if generation_id:
            where_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$ai_target_event_id"]),
                    right=ast.Constant(value=generation_id),
                )
            )

        not_na_guard = ast.Or(
            exprs=[
                ast.Call(name="isNull", args=[ast.Field(chain=["properties", "$ai_evaluation_applicable"])]),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["properties", "$ai_evaluation_applicable"]),
                    right=ast.Constant(value=False),
                ),
            ]
        )

        if result_filter == "pass":
            where_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$ai_evaluation_result"]),
                    right=ast.Constant(value=True),
                )
            )
            where_conditions.append(not_na_guard)
        elif result_filter == "fail":
            where_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$ai_evaluation_result"]),
                    right=ast.Constant(value=False),
                )
            )
            where_conditions.append(not_na_guard)
        elif result_filter == "na":
            where_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$ai_evaluation_applicable"]),
                    right=ast.Constant(value=False),
                )
            )

        query = parse_select(
            """
            SELECT
                uuid,
                timestamp,
                properties.$ai_evaluation_id as evaluation_id,
                properties.$ai_evaluation_name as evaluation_name,
                properties.$ai_target_event_id as generation_id,
                properties.$ai_trace_id as trace_id,
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
                query_type="EvaluationResultsList",
                query=query,
                placeholders={
                    "where_clause": ast.And(exprs=where_conditions),
                    "limit": ast.Constant(value=limit),
                },
                team=self.team,
            )

        results = [
            {
                "uuid": str(row[0]),
                "timestamp": row[1],
                "evaluation_id": str(row[2]) if row[2] else "",
                "evaluation_name": row[3] or "",
                "generation_id": str(row[4]) if row[4] else "",
                "trace_id": str(row[5]) if row[5] else None,
                "result": None if row[8] is False else row[6],
                "reasoning": row[7] or None,
                "applicable": row[8],
            }
            for row in (query_result.results or [])
        ]

        return Response({"results": results, "count": len(results)})
