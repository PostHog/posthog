"""Offline-evaluation experiment item listing.

Powers the "Offline evals → experiment items" view. Reads heavy `input` and
`output` from `posthog.ai_events` via `execute_with_ai_events_fallback` so
post-cutover items still surface their evaluated prompt + response.

The query groups by `(experiment_item_id, metric_name, metric_version)` —
one row per (item, metric) pair — and uses `argMax(..., timestamp)` to pick
the latest captured value for each field, which is why this can't ride on
`TraceQuery` or `TracesQuery` (their grouping axis is trace, not item).
"""

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

from posthog.api.monitoring import monitor
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
from posthog.permissions import AccessControlPermission

from products.llm_analytics.backend.api.metrics import llma_track_latency

logger = structlog.get_logger(__name__)

# `LIMIT` on the items query. Matches the frontend
# `OFFLINE_EXPERIMENT_ITEMS_LIMIT` constant.
OFFLINE_EXPERIMENT_ITEMS_LIMIT = 20000

# SQL for offline-evaluation experiment items. Heavy `input` / `output`
# come off the dedicated `ai_events` columns; non-heavy `$ai_*` props stay
# in `properties` JSON (and the resolver's column rewriter handles the
# events-fallback shape automatically).
_OFFLINE_EXPERIMENT_ITEMS_SQL = """
SELECT
    item_id,
    argMax(experiment_item_name, ts) as experiment_item_name,
    argMax(experiment_name, ts) as experiment_name,
    metric_name,
    metric_version,
    argMax(status, ts) as status,
    argMax(score, ts) as score,
    argMax(score_min, ts) as score_min,
    argMax(score_max, ts) as score_max,
    argMax(result_type, ts) as result_type,
    argMax(reasoning, ts) as reasoning,
    argMax(trace_id, ts) as trace_id,
    argMax(dataset_id, ts) as dataset_id,
    argMax(dataset_item_id, ts) as dataset_item_id,
    argMax(ai_input, ts) as ai_input,
    argMax(ai_output, ts) as ai_output,
    argMax(ai_expected, ts) as ai_expected,
    max(ts) as last_seen_at
FROM (
    -- Inner select projects every per-row field we want to argMax over.
    -- Putting `nullIf(...)` aliases here (instead of in the outer GROUP BY)
    -- avoids a HogQL quirk where outer GROUP BY references to aliased
    -- `properties.$ai_*` expressions were being mis-compiled into
    -- placeholder bytecode that referenced `properties` as a global.
    SELECT
        nullIf(properties.$ai_experiment_item_id, '') as item_id,
        properties.$ai_experiment_item_name as experiment_item_name,
        properties.$ai_experiment_name as experiment_name,
        nullIf(properties.$ai_metric_name, '') as metric_name,
        nullIf(properties.$ai_metric_version, '') as metric_version,
        properties.$ai_status as status,
        properties.$ai_score as score,
        properties.$ai_score_min as score_min,
        properties.$ai_score_max as score_max,
        properties.$ai_result_type as result_type,
        properties.$ai_reasoning as reasoning,
        ai_events.trace_id as trace_id,
        properties.$ai_dataset_id as dataset_id,
        properties.$ai_dataset_item_id as dataset_item_id,
        ai_events.input as ai_input,
        ai_events.output as ai_output,
        properties.$ai_expected as ai_expected,
        timestamp as ts
    FROM posthog.ai_events AS ai_events
    WHERE
        event = '$ai_evaluation'
        AND properties.$ai_experiment_id = {experiment_id}
        AND nullIf(properties.$ai_experiment_item_id, '') IS NOT NULL
        AND ({date_from_is_null} OR timestamp >= parseDateTimeBestEffort({date_from}))
        AND ({date_to_is_null} OR timestamp <= parseDateTimeBestEffort({date_to}))
)
GROUP BY item_id, metric_name, metric_version
ORDER BY last_seen_at DESC
LIMIT {limit}
"""


class OfflineExperimentItemsRequestSerializer(serializers.Serializer):
    experiment_id = serializers.CharField(required=True, allow_blank=False)
    date_from = serializers.CharField(required=False, allow_null=True, default=None)
    date_to = serializers.CharField(required=False, allow_null=True, default=None)


class OfflineExperimentItemsResponseSerializer(serializers.Serializer):
    # Tuple-positional rows; consumed by `offlineEvaluationsLogic.ts` as
    # `RawOfflineExperimentMetricRow`. Order matches `_OFFLINE_EXPERIMENT_ITEMS_SQL`.
    results = serializers.ListField(child=serializers.ListField())


class LLMAnalyticsOfflineEvaluationsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "llm_analytics"
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
        """Fetch experiment items for a given experiment_id, with heavy input/output."""
        serializer = OfflineExperimentItemsRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        experiment_id: str = serializer.validated_data["experiment_id"]
        date_from: str | None = serializer.validated_data.get("date_from") or None
        date_to: str | None = serializer.validated_data.get("date_to") or None

        # Parse-time placeholder substitution rather than execute-time.
        # Reason: HogQL has a quirk where placeholder-bytecode resolution
        # mis-fires on queries that combine `properties.$ai_*` field access
        # with a `GROUP BY` and an unrelated `{placeholder}`, raising
        # `HogVMException: Global variable not found: properties`. Substituting
        # at parse_select time produces a fully-resolved AST with embedded
        # Constant values, bypassing the bytecode path entirely. The values
        # are still typed-validated by the request serializer above, so this
        # is not a SQL-injection vector.
        query_placeholders: dict[str, ast.Expr] = {
            "experiment_id": ast.Constant(value=experiment_id),
            # `parseDateTimeBestEffort` rejects empty strings, so guard with
            # `{date_from_is_null}`/`{date_to_is_null}` to short-circuit the
            # range filter when the caller didn't pass a bound.
            "date_from": ast.Constant(value=date_from or ""),
            "date_to": ast.Constant(value=date_to or ""),
            "date_from_is_null": ast.Constant(value=date_from is None),
            "date_to_is_null": ast.Constant(value=date_to is None),
            "limit": ast.Constant(value=OFFLINE_EXPERIMENT_ITEMS_LIMIT),
        }
        query = parse_select(_OFFLINE_EXPERIMENT_ITEMS_SQL, placeholders=query_placeholders)

        with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=self.team_id):
            try:
                result = execute_with_ai_events_fallback(
                    query=query,
                    placeholders={},
                    team=self.team,
                    query_type="LLMOfflineEvaluationItems",
                    limit_context=LimitContext.QUERY,
                )
            except Exception as e:
                logger.exception(
                    "Failed to fetch offline evaluation experiment items",
                    team_id=self.team_id,
                    experiment_id=experiment_id,
                    error=str(e),
                )
                return Response(
                    {"error": "Failed to fetch offline evaluation items"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response({"results": result.results or []}, status=status.HTTP_200_OK)
