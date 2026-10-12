"""DRF views that import a Grafana dashboard or a dashboard screenshot as a new dashboard."""

import base64
import binascii
from dataclasses import asdict
from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.exceptions import Conflict
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission, posthog_feature_flag_enabled
from posthog.rate_limit import (
    AIBurstRateThrottle,
    AISustainedRateThrottle,
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
)

from products.metrics.backend.facade.api import (
    check_dashboard_panel_queries,
    get_dashboard_import,
    start_dashboard_import,
)
from products.metrics.backend.facade.contracts import (
    METRICS_DASHBOARD_IMPORT_FEATURE_FLAG,
    METRICS_FEATURE_FLAG,
    DashboardImportError,
    DashboardImportInProgress,
    DashboardImportNotAllowed,
    DashboardImportRequest,
    PanelQueryCheckRequest,
)
from products.metrics.backend.facade.enums import (
    DashboardImportSource,
    DashboardImportState,
    PanelImportOutcome,
    PanelQueryLanguage,
)
from products.metrics.backend.presentation.api import Op

__all__ = ["MetricsDashboardImportViewSet"]

MAX_GRAFANA_JSON_CHARACTERS = 5 * 1024 * 1024
# Base64 makes 5 MB of image bytes about 6.7 million characters.
MAX_IMAGE_BASE64_CHARACTERS = 7 * 1024 * 1024
MAX_CHECKED_PANELS = 20


class DashboardImportCreateSerializer(serializers.Serializer):
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=DashboardImportSource.choices,
        help_text="What to import: 'grafana' reads a Grafana dashboard JSON model, 'screenshot' reads an image of a dashboard.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=400,
        help_text="Name of the new dashboard. Defaults to the Grafana dashboard title, or to 'Imported dashboard'.",
    )
    grafana_json = serializers.CharField(
        required=False,
        trim_whitespace=False,
        max_length=MAX_GRAFANA_JSON_CHARACTERS,
        help_text="The Grafana dashboard JSON model as text, from Dashboard settings > JSON Model or from an export. Required when source is 'grafana'.",
    )
    image_base64 = serializers.CharField(
        required=False,
        max_length=MAX_IMAGE_BASE64_CHARACTERS,
        help_text="The screenshot as base64, without a data URL prefix. PNG, JPEG, WebP or GIF, at most 5 MB. Required when source is 'screenshot'.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["source"] == DashboardImportSource.GRAFANA and not attrs.get("grafana_json", "").strip():
            raise ValidationError({"grafana_json": "Paste the Grafana dashboard JSON."})
        if attrs["source"] == DashboardImportSource.SCREENSHOT:
            encoded = attrs.get("image_base64", "")
            if not encoded:
                raise ValidationError({"image_base64": "Add a screenshot of the dashboard."})
            try:
                attrs["image"] = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise ValidationError({"image_base64": "The screenshot is not valid base64."})
        return attrs


class DashboardImportSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="Number of panels in the input.")
    imported = serializers.IntegerField(help_text="Panels imported with the same meaning.")
    approximated = serializers.IntegerField(help_text="Panels imported with a change in what they show.")
    failed = serializers.IntegerField(help_text="Panels that have no working query.")
    skipped = serializers.IntegerField(help_text="Panels with no PostHog equivalent.")


class DashboardImportPanelSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Panel key in the import, for example 'p12' for Grafana panel 12.")
    title = serializers.CharField(help_text="Panel title.")
    outcome = serializers.ChoiceField(choices=PanelImportOutcome.choices, help_text="What happened to the panel.")
    reason = serializers.CharField(allow_blank=True, help_text="What changed, or why the panel failed or was skipped.")


class DashboardImportSerializer(serializers.Serializer):
    id = serializers.CharField(
        allow_null=True,
        help_text="Id to poll for the status. Null when the import finished in the request, with no agent.",
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=DashboardImportSource.choices, help_text="What the import reads."
    )
    status = serializers.ChoiceField(choices=DashboardImportState.choices, help_text="Where the import is.")
    dashboard_name = serializers.CharField(help_text="Name of the new dashboard.")
    progress = serializers.CharField(
        allow_null=True, help_text="Latest progress message of the import agent, while the import runs."
    )
    dashboard_id = serializers.IntegerField(allow_null=True, help_text="Id of the new dashboard, when it exists.")
    error = serializers.CharField(allow_null=True, help_text="Why the import failed, when it failed.")
    summary = DashboardImportSummarySerializer(allow_null=True, help_text="Panel counts, when the import ended.")
    panels = DashboardImportPanelSerializer(many=True, help_text="The outcome for each panel, when the import ended.")


class PanelFilterSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=255, help_text="Attribute name, for example 'service.name'.")
    op = serializers.ChoiceField(choices=Op.choices, help_text="Comparison. Regex operators use RE2.")
    value = serializers.CharField(allow_blank=True, max_length=1024, help_text="Value or regex to compare against.")


class PanelBuilderClauseSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64, help_text="Alias that a formula uses, for example 'a'.")
    metric_name = serializers.CharField(max_length=255, help_text="Exact metric name.")
    aggregation = serializers.ChoiceField(
        choices=["sum", "avg", "count", "min", "max", "p95", "rate", "increase", "histogram_quantile"],
        help_text="Aggregation for each bucket, with the same meaning as in the metrics query API.",
    )
    quantile = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Quantile between 0 and 1. Required for 'histogram_quantile'. The other aggregations ignore it.",
    )
    filters = PanelFilterSerializer(many=True, required=False, help_text="Attribute filters, joined with AND.")
    group_by = serializers.ListField(
        child=serializers.CharField(max_length=255),
        required=False,
        help_text="Attribute names that split the result into series.",
    )


class PanelBuilderQuerySerializer(serializers.Serializer):
    clauses = PanelBuilderClauseSerializer(many=True, help_text="One clause for each series.")
    formula = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Arithmetic over clause aliases, for example 'a / b'.",
    )


class PanelQueryCheckSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=64, help_text="Panel key. The result for the panel carries the same key.")
    language = serializers.ChoiceField(
        choices=PanelQueryLanguage.choices,
        help_text="'promql' or 'builder' for metrics, 'histogram' for a latency heatmap, 'hogql' for logs and traces.",
    )
    promql = serializers.CharField(
        required=False, allow_null=True, help_text="PromQL expression. Used when language is 'promql'."
    )
    builder = PanelBuilderQuerySerializer(
        required=False, allow_null=True, help_text="Builder query. Used when language is 'builder'."
    )
    histogram_metric = serializers.CharField(
        required=False, allow_null=True, help_text="Histogram metric name. Used when language is 'histogram'."
    )
    hogql = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="SQL SELECT over logs or posthog.trace_spans with {filters} in the WHERE clause. Used when language is 'hogql'.",
    )


class PanelQueryCheckRequestSerializer(serializers.Serializer):
    panels = serializers.ListField(
        child=PanelQueryCheckSerializer(),
        min_length=1,
        max_length=MAX_CHECKED_PANELS,
        help_text=f"Up to {MAX_CHECKED_PANELS} panel queries to check.",
    )


class PanelQueryCheckResultSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Panel key from the request.")
    valid = serializers.BooleanField(help_text="True when the query can go on a dashboard.")
    error = serializers.CharField(allow_null=True, help_text="Why the query cannot go on a dashboard.")
    notes = serializers.ListField(
        child=serializers.CharField(), help_text="Warnings that do not block the query, such as no recent data."
    )


class PanelQueryCheckResponseSerializer(serializers.Serializer):
    results = PanelQueryCheckResultSerializer(many=True, help_text="One result for each checked panel.")


class MetricsDashboardImportViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "metrics"
    serializer_class = _FallbackSerializer
    posthog_feature_flag = METRICS_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action == "create":
            return ["metrics:read", "dashboard:write", "insight:write"]
        return ["metrics:read"]

    def get_throttles(self) -> list[Any]:
        if self.action == "create":
            return [AIBurstRateThrottle(), AISustainedRateThrottle()]
        if self.action == "validate":
            return [ClickHouseBurstRateThrottle(), ClickHouseSustainedRateThrottle()]
        return super().get_throttles()

    def _require_import_flag(self, request: Request) -> None:
        if not posthog_feature_flag_enabled(
            METRICS_DASHBOARD_IMPORT_FEATURE_FLAG,
            str(cast(User, request.user).distinct_id),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise PermissionDenied("Dashboard import is not enabled for this user.")

    @extend_schema(
        request=DashboardImportCreateSerializer,
        responses={
            201: DashboardImportSerializer,
            403: OpenApiResponse(description="AI data processing is off, the AI credits ran out, or no access."),
            409: OpenApiResponse(description="The user already has an import that is running."),
        },
        description=(
            "Import a Grafana dashboard JSON model or a dashboard screenshot as a new dashboard. Panels that "
            "match the project's metrics import at once. An AI agent converts the rest, and the response then "
            "has an id to poll."
        ),
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        self._require_import_flag(request)
        access = self.user_access_control
        if not access.check_access_level_for_resource(
            "dashboard", "editor"
        ) or not access.check_access_level_for_resource("insight", "editor"):
            raise PermissionDenied("You need editor access to dashboards and insights to import a dashboard.")
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)

        body = DashboardImportCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            result = start_dashboard_import(
                team=self.team,
                user=cast(User, request.user),
                request=DashboardImportRequest(
                    source=DashboardImportSource(body.validated_data["source"]),
                    name=body.validated_data.get("name") or None,
                    grafana_json=body.validated_data.get("grafana_json"),
                    image=body.validated_data.get("image"),
                ),
            )
        except DashboardImportInProgress as error:
            raise Conflict(str(error))
        except DashboardImportNotAllowed as error:
            raise PermissionDenied(str(error))
        except DashboardImportError as error:
            raise ValidationError(str(error))
        return Response(DashboardImportSerializer(asdict(result)).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: DashboardImportSerializer})
    def retrieve(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """Status of one of the user's dashboard imports. Poll it until the status is not 'running'."""
        self._require_import_flag(request)
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        result = get_dashboard_import(team=self.team, user=cast(User, request.user), import_id=str(pk))
        if result is None:
            raise NotFound("No dashboard import with this id.")
        return Response(DashboardImportSerializer(asdict(result)).data)

    @extend_schema(request=PanelQueryCheckRequestSerializer, responses={200: PanelQueryCheckResponseSerializer})
    @action(detail=False, methods=["POST"])
    def validate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Check dashboard panel queries before they go on a dashboard: the metrics must exist, PromQL must
        run, and SQL must compile and read only logs or traces."""
        self._require_import_flag(request)
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        body = PanelQueryCheckRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        panels = [
            PanelQueryCheckRequest(
                key=panel["key"],
                language=PanelQueryLanguage(panel["language"]),
                promql=panel.get("promql"),
                builder=panel.get("builder"),
                histogram_metric=panel.get("histogram_metric"),
                hogql=panel.get("hogql"),
            )
            for panel in body.validated_data["panels"]
        ]
        results = check_dashboard_panel_queries(team=self.team, user=cast(User, request.user), panels=panels)
        return Response(PanelQueryCheckResponseSerializer({"results": [asdict(item) for item in results]}).data)
