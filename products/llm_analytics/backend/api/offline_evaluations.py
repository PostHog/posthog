from collections import namedtuple

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
from posthog.permissions import AccessControlPermission

from products.llm_analytics.backend.api.metrics import llma_track_latency

logger = structlog.get_logger(__name__)

OFFLINE_EXPERIMENT_ITEMS_LIMIT = 20000

# Preflight on `events` so the `(team_id, toDate(timestamp), event)` sort
# key prunes by date; `posthog.ai_events` is keyed `(team_id, trace_id,
# timestamp)` and can't prune until trace_id is bounded.
_OFFLINE_EXPERIMENT_ITEMS_PREFLIGHT_SQL = """
SELECT
    nullIf(properties.$ai_experiment_item_id, '') as item_id,
    argMax(properties.$ai_experiment_item_name, timestamp) as experiment_item_name,
    argMax(properties.$ai_experiment_name, timestamp) as experiment_name,
    nullIf(properties.$ai_metric_name, '') as metric_name,
    nullIf(properties.$ai_metric_version, '') as metric_version,
    argMax(properties.$ai_status, timestamp) as status,
    argMax(properties.$ai_score, timestamp) as score,
    argMax(properties.$ai_score_min, timestamp) as score_min,
    argMax(properties.$ai_score_max, timestamp) as score_max,
    argMax(properties.$ai_result_type, timestamp) as result_type,
    argMax(properties.$ai_reasoning, timestamp) as reasoning,
    argMax(properties.$ai_trace_id, timestamp) as trace_id,
    argMax(properties.$ai_dataset_id, timestamp) as dataset_id,
    argMax(properties.$ai_dataset_item_id, timestamp) as dataset_item_id,
    argMax(properties.$ai_expected, timestamp) as ai_expected,
    max(timestamp) as last_seen_at,
    min(timestamp) as first_seen_at
FROM events
WHERE
    event = '$ai_evaluation'
    AND properties.$ai_experiment_id = {experiment_id}
    AND nullIf(properties.$ai_experiment_item_id, '') IS NOT NULL
    AND ({date_from_is_null} OR timestamp >= parseDateTimeBestEffort({date_from}))
    AND ({date_to_is_null} OR timestamp <= parseDateTimeBestEffort({date_to}))
GROUP BY item_id, metric_name, metric_version
ORDER BY last_seen_at DESC
LIMIT {limit}
"""

_OFFLINE_EXPERIMENT_ITEMS_HEAVY_SQL = """
SELECT
    trace_id,
    argMax(input, timestamp) as ai_input,
    argMax(output, timestamp) as ai_output
FROM posthog.ai_events AS ai_events
WHERE event = '$ai_evaluation'
    AND trace_id IN {trace_ids}
    AND timestamp >= {ts_start}
    AND timestamp <= {ts_end}
GROUP BY trace_id
"""

_PreflightRow = namedtuple(
    "_PreflightRow",
    [
        "item_id",
        "experiment_item_name",
        "experiment_name",
        "metric_name",
        "metric_version",
        "status",
        "score",
        "score_min",
        "score_max",
        "result_type",
        "reasoning",
        "trace_id",
        "dataset_id",
        "dataset_item_id",
        "ai_expected",
        "last_seen_at",
        "first_seen_at",
    ],
)


class OfflineExperimentItemsRequestSerializer(serializers.Serializer):
    experiment_id = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text="`$ai_experiment_id` whose offline-evaluation items to return.",
    )
    date_from = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Lower bound on `timestamp` (ISO-8601). Omit to leave the lower bound open.",
    )
    date_to = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Upper bound on `timestamp` (ISO-8601). Omit to leave the upper bound open.",
    )


class OfflineExperimentItemsResponseSerializer(serializers.Serializer):
    results = serializers.ListField(
        child=serializers.ListField(),
        help_text="Tuple-positional rows; positions match `RawOfflineExperimentMetricRow` in the frontend.",
    )


class LLMAnalyticsOfflineEvaluationsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "llm_analytics"
    scope_object_read_actions = ["experiment_items"]
    permission_classes = [AccessControlPermission]

    @extend_schema(
        request=OfflineExperimentItemsRequestSerializer,
        responses={
            200: OfflineExperimentItemsResponseSerializer,
            400: OpenApiTypes.OBJECT,
            500: OpenApiTypes.OBJECT,
        },
        tags=["LLM Analytics"],
    )
    @action(detail=False, methods=["post"], url_path="experiment_items")
    @llma_track_latency("llma_offline_evaluations_experiment_items")
    @monitor(feature=None, endpoint="llma_offline_evaluations_experiment_items", method="POST")
    def experiment_items(self, request: Request, **kwargs) -> Response:
        serializer = OfflineExperimentItemsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        experiment_id: str = serializer.validated_data["experiment_id"]
        date_from: str | None = serializer.validated_data.get("date_from") or None
        date_to: str | None = serializer.validated_data.get("date_to") or None

        # Parse-time, not execute-time: `properties.$ai_* + GROUP BY +
        # {placeholder}` trips `HogVMException: Global variable not found:
        # properties` in bytecode. parse_select-time substitution embeds
        # Constants into the AST and bypasses the bytecode path.
        preflight_placeholders: dict[str, ast.Expr] = {
            "experiment_id": ast.Constant(value=experiment_id),
            # `parseDateTimeBestEffort` rejects "", so the `_is_null` flags
            # short-circuit the range filter when no bound was passed.
            "date_from": ast.Constant(value=date_from or ""),
            "date_to": ast.Constant(value=date_to or ""),
            "date_from_is_null": ast.Constant(value=date_from is None),
            "date_to_is_null": ast.Constant(value=date_to is None),
            "limit": ast.Constant(value=OFFLINE_EXPERIMENT_ITEMS_LIMIT),
        }
        preflight_query = parse_select(_OFFLINE_EXPERIMENT_ITEMS_PREFLIGHT_SQL, placeholders=preflight_placeholders)

        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=self.team_id):
            try:
                preflight_result = execute_hogql_query(
                    query=preflight_query,
                    placeholders={},
                    team=self.team,
                    query_type="LLMOfflineEvaluationItemsResolve",
                    limit_context=LimitContext.QUERY,
                )
            except Exception as e:
                logger.exception(
                    "Failed to resolve offline evaluation experiment items",
                    team_id=self.team_id,
                    experiment_id=experiment_id,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to fetch offline evaluation items"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            preflight_rows = [_PreflightRow(*row) for row in (preflight_result.results or [])]
            if not preflight_rows:
                return Response({"results": []}, status=status.HTTP_200_OK)

            traced_rows = [row for row in preflight_rows if row.trace_id]
            trace_ids = [str(row.trace_id) for row in traced_rows]
            ai_input_output_by_trace: dict[str, tuple] = {}

            if trace_ids:
                ts_start = min(row.first_seen_at for row in traced_rows)
                ts_end = max(row.last_seen_at for row in traced_rows)

                heavy_query = parse_select(_OFFLINE_EXPERIMENT_ITEMS_HEAVY_SQL)
                try:
                    heavy_result = execute_with_ai_events_fallback(
                        query=heavy_query,
                        placeholders={
                            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids]),
                            "ts_start": ast.Constant(value=ts_start),
                            "ts_end": ast.Constant(value=ts_end),
                        },
                        team=self.team,
                        query_type="LLMOfflineEvaluationItems",
                        limit_context=LimitContext.QUERY,
                    )
                except Exception as e:
                    logger.exception(
                        "Failed to fetch offline evaluation items heavy columns",
                        team_id=self.team_id,
                        experiment_id=experiment_id,
                        error=str(e),
                    )
                    return Response(
                        {"error": "Failed to fetch offline evaluation items"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                ai_input_output_by_trace = {
                    str(trace_id): (ai_input, ai_output)
                    for trace_id, ai_input, ai_output in (heavy_result.results or [])
                }

        results = []
        for row in preflight_rows:
            ai_input, ai_output = ai_input_output_by_trace.get(str(row.trace_id), (None, None))
            results.append(
                [
                    row.item_id,
                    row.experiment_item_name,
                    row.experiment_name,
                    row.metric_name,
                    row.metric_version,
                    row.status,
                    row.score,
                    row.score_min,
                    row.score_max,
                    row.result_type,
                    row.reasoning,
                    row.trace_id,
                    row.dataset_id,
                    row.dataset_item_id,
                    ai_input,
                    ai_output,
                    row.ai_expected,
                    row.last_seen_at,
                ]
            )
        return Response({"results": results}, status=status.HTTP_200_OK)
