"""CRUD + evaluation API for metrics pipelines (topology of metrics).

The nested config serializers document the wire shape for OpenAPI/generated
types; the graph invariants (unique ids, resolvable edges, acyclicity) are
enforced once, in `parse_pipeline_config`, which `validate_config` delegates
to. Collision-prone vocabulary fields (aggregation, op, scope, format) stay
`CharField`s — the parser rejects unknown values, and this keeps the spec
free of duplicate enum components.
"""

import datetime as dt
from dataclasses import asdict
from typing import cast

from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import report_user_action
from posthog.models.user import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.rate_limit import ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle

from products.metrics.backend.facade.api import (
    create_pipeline,
    evaluate_pipeline,
    get_pipeline,
    list_pipelines,
    parse_pipeline_config,
    soft_delete_pipeline,
    update_pipeline,
)
from products.metrics.backend.facade.contracts import (
    MAX_PIPELINE_BREAKDOWN_TOP_N,
    MAX_PIPELINE_NODES,
    MAX_PIPELINE_STATS_PER_NODE,
    PIPELINES_FEATURE_FLAG,
    PipelineNotFoundError,
)

__all__ = ["MetricsPipelineViewSet"]

# Bounds an evaluation window so a single tick can't scan an unbounded range.
MAX_EVALUATION_WINDOW = dt.timedelta(days=7)
DEFAULT_EVALUATION_WINDOW = dt.timedelta(minutes=30)


class PipelineFilterSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=255, help_text="Attribute name to filter on (e.g. 'k8s.pod.name').")
    op = serializers.CharField(
        max_length=16,
        required=False,
        default="eq",
        help_text="Comparison operator: one of 'eq', 'neq', 'regex', 'not_regex'.",
    )
    value = serializers.CharField(
        allow_blank=True, max_length=1024, help_text="Value to compare against; the pattern for regex operators."
    )
    scope = serializers.CharField(
        max_length=16,
        required=False,
        default="auto",
        help_text="Where the attribute lives: 'resource', 'attribute', or 'auto'.",
    )


class PipelineThresholdBoundsSerializer(serializers.Serializer):
    lower = serializers.FloatField(
        required=False, allow_null=True, help_text="Values below this breach the severity. Omit for no lower bound."
    )
    upper = serializers.FloatField(
        required=False, allow_null=True, help_text="Values above this breach the severity. Omit for no upper bound."
    )


class PipelineThresholdsSerializer(serializers.Serializer):
    warn = PipelineThresholdBoundsSerializer(
        required=False, allow_null=True, help_text="Bounds whose breach marks the stat degraded."
    )
    crit = PipelineThresholdBoundsSerializer(
        required=False, allow_null=True, help_text="Bounds whose breach marks the stat critical."
    )


class PipelineBreakdownSerializer(serializers.Serializer):
    group_by_key = serializers.CharField(
        max_length=255, help_text="Label to split the stat's breakdown table by (e.g. 'partition_id')."
    )
    top_n = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=MAX_PIPELINE_BREAKDOWN_TOP_N,
        help_text="Rows shown before the remainder rolls into one 'others' row.",
    )
    scope = serializers.CharField(
        max_length=16, required=False, default="auto", help_text="Attribute scope: 'resource', 'attribute', or 'auto'."
    )


class PipelineStatSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64, help_text="Stat id, unique within its node.")
    label = serializers.CharField(max_length=120, help_text="Display label for the stat.")
    format = serializers.CharField(
        max_length=16,
        required=False,
        default="count",
        help_text="Display format hint: 'rate', 'bytes', 'pct', 'count', or 'duration'.",
    )
    metric_name = serializers.CharField(max_length=255, help_text="Exact ingested metric name this stat queries.")
    aggregation = serializers.CharField(
        max_length=32,
        required=False,
        default="sum",
        help_text="Aggregation per time bucket: 'sum', 'avg', 'count', 'rate', 'increase', 'quantile', or 'histogram_quantile'.",
    )
    quantile = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Quantile in (0, 1) for the quantile aggregations.",
    )
    metric_type = serializers.CharField(
        max_length=32,
        required=False,
        allow_null=True,
        help_text="Optional OTel metric type constraint (e.g. 'gauge', 'sum', 'histogram').",
    )
    filters = PipelineFilterSerializer(
        many=True, required=False, default=list, help_text="Label predicates ANDed onto the stat's query."
    )
    thresholds = PipelineThresholdsSerializer(
        required=False, allow_null=True, help_text="Warn/crit bounds evaluated against the stat's latest value."
    )
    breakdown = PipelineBreakdownSerializer(
        required=False, allow_null=True, help_text="Optional per-label breakdown table under the stat."
    )


class PipelineLinkSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=120, help_text="Link text shown on the drill panel.")
    url = serializers.CharField(max_length=2048, help_text="Destination URL.")


class PipelineNodeSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=64, help_text="Node id, unique within the pipeline; edges reference it.")
    name = serializers.CharField(max_length=120, help_text="Display name of the component.")
    kind = serializers.CharField(
        max_length=120, required=False, allow_blank=True, default="", help_text="Free-form component kind subtitle."
    )
    stats = PipelineStatSerializer(
        many=True, help_text=f"Health stats on this node (at most {MAX_PIPELINE_STATS_PER_NODE})."
    )
    headline_stat_ids = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=list,
        help_text="Stat ids shown on the collapsed node card, in order.",
    )
    links = PipelineLinkSerializer(
        many=True, required=False, default=list, help_text="External deep links shown on the drill panel."
    )
    note = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="Free-form operator note shown on the drill panel."
    )


class PipelineEdgeSerializer(serializers.Serializer):
    source = serializers.CharField(max_length=64, help_text="Upstream node id.")
    target = serializers.CharField(max_length=64, help_text="Downstream node id.")
    metric_name = serializers.CharField(max_length=255, help_text="Metric measuring throughput along this edge.")
    aggregation = serializers.CharField(
        max_length=32, required=False, default="sum", help_text="Aggregation per time bucket; same vocabulary as stats."
    )
    quantile = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Quantile in (0, 1) for the quantile aggregations.",
    )
    metric_type = serializers.CharField(
        max_length=32, required=False, allow_null=True, help_text="Optional OTel metric type constraint."
    )
    filters = PipelineFilterSerializer(
        many=True, required=False, default=list, help_text="Label predicates ANDed onto the edge's query."
    )
    baseline_offset = serializers.CharField(
        max_length=16,
        required=False,
        default="-7d",
        help_text="How far back the comparison window sits, e.g. '-7d', '-24h', '-1w'.",
    )
    hot_multiplier = serializers.FloatField(
        required=False, default=2.0, help_text="Current/baseline ratio at which the edge renders hot. Must exceed 1."
    )


class PipelineVariableSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64, help_text="Variable key referenced when evaluating.")
    label = serializers.CharField(max_length=120, help_text="Display label of the selector.")
    filter_key = serializers.CharField(
        max_length=255, help_text="Metric label the chosen value filters on (e.g. 'k8s.cluster.name')."
    )
    options = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        default=list,
        help_text="Allowed values; empty accepts any value.",
    )
    default = serializers.CharField(
        max_length=255, required=False, allow_null=True, help_text="Value applied when none is passed to evaluate."
    )


class PipelineConfigSerializer(serializers.Serializer):
    nodes = PipelineNodeSerializer(many=True, help_text=f"Topology nodes (at most {MAX_PIPELINE_NODES}).")
    edges = PipelineEdgeSerializer(
        many=True, required=False, default=list, help_text="Directed flows between nodes; the graph must stay acyclic."
    )
    variables = PipelineVariableSerializer(
        many=True, required=False, default=list, help_text="Pipeline-level selectors injected into every query."
    )


class PipelineActorSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="User id.")
    email = serializers.CharField(help_text="User email.")
    first_name = serializers.CharField(allow_blank=True, help_text="User first name.")


class MetricsPipelineSerializer(serializers.Serializer):
    """Read shape of a stored pipeline (mirrors `MetricsPipelineRecord`)."""

    id = serializers.CharField(help_text="Pipeline UUID.")
    name = serializers.CharField(help_text="Display name of the pipeline.")
    description = serializers.CharField(allow_blank=True, help_text="What this pipeline observes and who owns it.")
    config = PipelineConfigSerializer(help_text="The topology: nodes with health stats, edges with baselines.")
    enabled = serializers.BooleanField(help_text="Disabled pipelines stay listed but are not evaluated.")
    created_at = serializers.CharField(help_text="Creation time, ISO 8601.")
    created_by = PipelineActorSerializer(allow_null=True, help_text="User who created the pipeline.")
    updated_at = serializers.CharField(allow_null=True, help_text="Last update time, ISO 8601.")


class MetricsPipelineWriteSerializer(serializers.Serializer):
    """Write shape for create/update. `config` is fully revalidated by
    `parse_pipeline_config` on every write."""

    name = serializers.CharField(max_length=400, help_text="Display name of the pipeline.")
    description = serializers.CharField(
        required=False, allow_blank=True, default="", help_text="What this pipeline observes and who owns it."
    )
    config = PipelineConfigSerializer(help_text="The topology: nodes with health stats, edges with baselines.")
    enabled = serializers.BooleanField(
        required=False, default=True, help_text="Disabled pipelines stay listed but are not evaluated."
    )

    def validate_config(self, value: dict) -> dict:
        try:
            parse_pipeline_config(value)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        return value


class PipelineListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total pipelines for the team.")
    results = MetricsPipelineSerializer(many=True, help_text="The team's pipelines, newest first.")


class PipelineEvaluateRequestSerializer(serializers.Serializer):
    variables = serializers.DictField(
        child=serializers.CharField(max_length=255, help_text="Chosen value for the variable."),
        required=False,
        default=dict,
        help_text="Variable values keyed by variable key; unset variables fall back to their defaults.",
    )
    date_from = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Window start (ISO 8601). Defaults to 30 minutes ago."
    )
    date_to = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Window end (ISO 8601), exclusive. Defaults to now."
    )

    def validate(self, attrs: dict) -> dict:
        date_to = attrs.get("date_to") or timezone.now()
        date_from = attrs.get("date_from") or date_to - DEFAULT_EVALUATION_WINDOW
        if date_from >= date_to:
            raise serializers.ValidationError("date_from must be before date_to")
        if date_to - date_from > MAX_EVALUATION_WINDOW:
            raise serializers.ValidationError(f"the evaluation window is capped at {MAX_EVALUATION_WINDOW.days} days")
        attrs["date_from"], attrs["date_to"] = date_from, date_to
        return attrs


class PipelineBreakdownRowSerializer(serializers.Serializer):
    label = serializers.CharField(help_text="Label value of the row (e.g. the partition id).")
    value = serializers.FloatField(help_text="Latest reported value for the row.")


class PipelineStatResultSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Stat id from the config.")
    label = serializers.CharField(help_text="Display label from the config.")
    format = serializers.CharField(help_text="Display format hint from the config.")
    value = serializers.FloatField(allow_null=True, help_text="Latest reported value; null when the stat is silent.")
    state = serializers.CharField(help_text="Health verdict: 'healthy', 'degraded', 'critical', or 'no_data'.")
    breakdown_rows = PipelineBreakdownRowSerializer(
        many=True, help_text="Top breakdown rows, when the stat configures a breakdown."
    )
    breakdown_others = PipelineBreakdownRowSerializer(
        allow_null=True, help_text="Rollup of the rows beyond top_n; null when nothing was rolled up."
    )


class PipelineNodeResultSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Node id from the config.")
    state = serializers.CharField(help_text="Worst reporting stat's verdict; 'no_data' when every stat is silent.")
    stats = PipelineStatResultSerializer(many=True, help_text="Per-stat verdicts, in config order.")


class PipelinePointSerializer(serializers.Serializer):
    time = serializers.CharField(help_text="Bucket start, ISO 8601.")
    value = serializers.FloatField(allow_null=True, help_text="Bucket value; null renders a gap.")


class PipelineEdgeResultSerializer(serializers.Serializer):
    source = serializers.CharField(help_text="Upstream node id.")
    target = serializers.CharField(help_text="Downstream node id.")
    current_value = serializers.FloatField(allow_null=True, help_text="Mean throughput over the current window.")
    baseline_value = serializers.FloatField(allow_null=True, help_text="Mean throughput over the baseline window.")
    multiplier = serializers.FloatField(
        allow_null=True, help_text="current/baseline ratio; null when the baseline had no signal."
    )
    hot = serializers.BooleanField(help_text="True when the multiplier reached the edge's hot_multiplier.")
    points = PipelinePointSerializer(many=True, help_text="Current-window series for the sparkline.")


class PipelineAlertSerializer(serializers.Serializer):
    severity = serializers.CharField(help_text="'warning' or 'critical'.")
    node_id = serializers.CharField(help_text="Node whose stat breached.")
    stat_id = serializers.CharField(help_text="The breached stat.")
    message = serializers.CharField(help_text="Human-readable alert line for the strip.")


class PipelineEvaluationSerializer(serializers.Serializer):
    nodes = PipelineNodeResultSerializer(many=True, help_text="Per-node verdicts, in config order.")
    edges = PipelineEdgeResultSerializer(many=True, help_text="Per-edge throughput vs baseline, in config order.")
    alerts = PipelineAlertSerializer(many=True, help_text="Derived alert strip, critical entries first.")
    date_from = serializers.CharField(help_text="Evaluated window start, ISO 8601.")
    date_to = serializers.CharField(help_text="Evaluated window end, ISO 8601.")


class MetricsPipelineViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Model-free viewset: the metrics product is isolated, so all data access
    goes through the facade's pipeline functions and their contracts."""

    scope_object = "metrics"
    serializer_class = MetricsPipelineSerializer
    lookup_value_regex = r"[^/]+"
    # Pipelines gate independently of the base metrics viewer so the surface
    # can roll out on its own schedule. Added to the mixin's default
    # permissions, not replacing them.
    posthog_feature_flag = PIPELINES_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]

    @extend_schema(
        responses={200: PipelineListResponseSerializer},
        description="List the team's pipelines, newest first.",
    )
    def list(self, request: Request, *args, **kwargs) -> Response:
        records = list_pipelines(team=self.team)
        return Response({"count": len(records), "results": [asdict(record) for record in records]})

    @extend_schema(
        request=MetricsPipelineWriteSerializer,
        responses={201: MetricsPipelineSerializer},
        description="Create a pipeline from a validated topology config.",
    )
    def create(self, request: Request, *args, **kwargs) -> Response:
        write_serializer = MetricsPipelineWriteSerializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)
        params = write_serializer.validated_data
        user = cast(User, request.user)
        record = create_pipeline(
            team=self.team,
            created_by_id=user.pk,
            name=params["name"],
            description=params["description"],
            config=params["config"],
            enabled=params["enabled"],
        )
        report_user_action(user, "metrics pipeline created", team=self.team)
        return Response(asdict(record), status=status.HTTP_201_CREATED)

    @extend_schema(
        responses={200: MetricsPipelineSerializer},
        description="Fetch one pipeline.",
    )
    def retrieve(self, request: Request, pk: str, *args, **kwargs) -> Response:
        try:
            return Response(asdict(get_pipeline(team=self.team, pipeline_id=pk)))
        except PipelineNotFoundError:
            raise NotFound("Pipeline not found")

    @extend_schema(
        request=MetricsPipelineWriteSerializer,
        responses={200: MetricsPipelineSerializer},
        description="Patch a pipeline; omitted fields stay unchanged. The config is fully revalidated.",
    )
    def partial_update(self, request: Request, pk: str, *args, **kwargs) -> Response:
        write_serializer = MetricsPipelineWriteSerializer(data=request.data, partial=True)
        write_serializer.is_valid(raise_exception=True)
        params = write_serializer.validated_data
        try:
            record = update_pipeline(
                team=self.team,
                pipeline_id=pk,
                name=params.get("name"),
                description=params.get("description"),
                config=params.get("config"),
                enabled=params.get("enabled"),
            )
        except PipelineNotFoundError:
            raise NotFound("Pipeline not found")
        report_user_action(cast(User, request.user), "metrics pipeline updated", team=self.team)
        return Response(asdict(record))

    @extend_schema(
        responses={204: None},
        description="Soft-delete a pipeline: the row is retained but stops appearing in lists.",
    )
    def destroy(self, request: Request, pk: str, *args, **kwargs) -> Response:
        try:
            soft_delete_pipeline(team=self.team, pipeline_id=pk)
        except PipelineNotFoundError:
            raise NotFound("Pipeline not found")
        report_user_action(cast(User, request.user), "metrics pipeline deleted", team=self.team)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=PipelineEvaluateRequestSerializer,
        responses={200: PipelineEvaluationSerializer},
        description="Evaluate every node stat and edge of the pipeline over one window and derive the alert strip.",
    )
    @action(
        detail=True,
        methods=["POST"],
        required_scopes=["metrics:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def evaluate(self, request: Request, pk: str, *args, **kwargs) -> Response:
        try:
            record = get_pipeline(team=self.team, pipeline_id=pk)
        except PipelineNotFoundError:
            raise NotFound("Pipeline not found")
        # Honour the `enabled` flag here rather than only in a future scheduler,
        # so switching a pipeline off actually stops its ClickHouse queries.
        if not record.enabled:
            raise ParseError("This pipeline is disabled. Enable it to evaluate.")
        request_serializer = PipelineEvaluateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        params = request_serializer.validated_data

        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        try:
            config = parse_pipeline_config(record.config)
            evaluation = evaluate_pipeline(
                team=self.team,
                config=config,
                date_from=params["date_from"],
                date_to=params["date_to"],
                variable_values=params["variables"] or None,
            )
        except ValueError as e:
            raise ParseError(str(e))

        report_user_action(cast(User, request.user), "metrics pipeline evaluated", team=self.team)
        return Response(asdict(evaluation), status=status.HTTP_200_OK)
