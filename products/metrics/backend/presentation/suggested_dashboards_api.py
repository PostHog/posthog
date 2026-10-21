"""DRF views for suggested metrics dashboards: the suggestions of a team, and the staff review of the bank."""

from dataclasses import asdict
from typing import Any, cast

from django.http import HttpResponse

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.documentation import _FallbackSerializer
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import User
from posthog.permissions import IsStaffUser, PostHogFeatureFlagPermission, posthog_feature_flag_enabled

from products.metrics.backend.facade.api import (
    analyze_team_metrics_now,
    approve_dashboard_template,
    create_suggested_dashboard,
    dashboard_template_picture,
    get_dashboard_template,
    list_dashboard_templates,
    list_suggested_dashboards,
    open_dashboard_template_preview,
    reject_dashboard_template,
)
from products.metrics.backend.facade.contracts import (
    METRICS_FEATURE_FLAG,
    METRICS_SUGGESTED_DASHBOARDS_FEATURE_FLAG,
    SuggestedDashboardError,
    SuggestedDashboardNotFound,
)
from products.metrics.backend.facade.enums import DashboardTemplateSource, DashboardTemplateStatus

__all__ = ["MetricsDashboardTemplateViewSet", "MetricsSuggestedDashboardViewSet"]

UUID_REGEX = "[0-9a-fA-F-]{36}"


class MetricsSuggestedDashboardSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Suggestion id.")
    template_id = serializers.UUIDField(help_text="The bank dashboard that the suggestion is for.")
    name = serializers.CharField(help_text="Dashboard name.")
    description = serializers.CharField(allow_blank=True, help_text="What the dashboard shows.")
    reason = serializers.CharField(allow_blank=True, help_text="Why the dashboard suits this project. Can be empty.")
    panel_count = serializers.IntegerField(help_text="Number of charts on the dashboard.")
    matched_metric_count = serializers.IntegerField(
        help_text="Number of the project's metrics that the dashboard uses."
    )
    coverage = serializers.FloatField(help_text="Share of the dashboard's charts that have data in this project.")
    dashboard_id = serializers.IntegerField(
        allow_null=True, help_text="The dashboard that someone in the project created from this suggestion."
    )


class MetricsCreatedDashboardSerializer(serializers.Serializer):
    dashboard_id = serializers.IntegerField(help_text="The id of the dashboard.")


class MetricsDashboardTemplateRoundSerializer(serializers.Serializer):
    round = serializers.IntegerField(help_text="Check round, from 1.")
    has_picture = serializers.BooleanField(help_text="True when the round rendered a picture of the dashboard.")
    looks_good = serializers.BooleanField(allow_null=True, help_text="The verdict of the model on the picture.")
    problems = serializers.ListField(child=serializers.CharField(), help_text="The problems that the model saw.")
    revised = serializers.BooleanField(help_text="True when the model corrected the panels after this round.")


class MetricsDashboardTemplateSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Template id.")
    key = serializers.CharField(help_text="Stable key: the bank file name, or a digest of the metric names.")
    name = serializers.CharField(help_text="Dashboard name.")
    description = serializers.CharField(allow_blank=True, help_text="What the dashboard shows.")
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=DashboardTemplateSource.choices, help_text="Curated in code, or generated."
    )
    status = serializers.ChoiceField(choices=DashboardTemplateStatus.choices, help_text="Review status.")
    metric_names = serializers.ListField(child=serializers.CharField(), help_text="Metric names that the charts read.")
    panel_titles = serializers.ListField(child=serializers.CharField(), help_text="Chart titles, top to bottom.")
    created_at = serializers.DateTimeField(help_text="When the template entered the bank.")
    suggestion_count = serializers.IntegerField(help_text="Number of projects that have the template suggested.")
    source_team_id = serializers.IntegerField(allow_null=True, help_text="Project whose metrics generated it.")
    preview_team_id = serializers.IntegerField(allow_null=True, help_text="Project of the preview dashboard.")
    preview_dashboard_id = serializers.IntegerField(
        allow_null=True, help_text="Unlisted dashboard that shows the template with live data."
    )
    rounds = MetricsDashboardTemplateRoundSerializer(many=True, help_text="The picture check rounds of the generation.")
    dropped_panels = serializers.ListField(
        child=serializers.CharField(), help_text="Drafted charts whose queries failed the checks."
    )
    error = serializers.CharField(allow_null=True, help_text="Why the generation failed.")
    reviewed_by = serializers.CharField(allow_null=True, help_text="Who approved or rejected the template.")
    reviewed_at = serializers.DateTimeField(allow_null=True, help_text="When the template was approved or rejected.")


class MetricsSuggestedDashboardViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "metrics"
    serializer_class = _FallbackSerializer
    posthog_feature_flag = METRICS_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    lookup_value_regex = UUID_REGEX

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        if self.action == "dashboard":
            return ["metrics:read", "dashboard:write", "insight:write"]
        return ["metrics:read"]

    def _require_flag(self, request: Request) -> None:
        if not posthog_feature_flag_enabled(
            METRICS_SUGGESTED_DASHBOARDS_FEATURE_FLAG,
            str(cast(User, request.user).distinct_id),
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
        ):
            raise PermissionDenied("Suggested dashboards are not enabled for this user.")

    @extend_schema(responses={200: MetricsSuggestedDashboardSerializer(many=True)})
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Dashboards from the metrics dashboard bank that suit the metrics this project sends, best fit first."""
        self._require_flag(request)
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        suggestions = list_suggested_dashboards(team=self.team)
        return Response(MetricsSuggestedDashboardSerializer([asdict(item) for item in suggestions], many=True).data)

    @extend_schema(
        request=None,
        responses={
            201: MetricsCreatedDashboardSerializer,
            400: OpenApiResponse(description="The project no longer sends the metrics of this dashboard."),
        },
    )
    @action(detail=True, methods=["POST"])
    def dashboard(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """Create the suggested dashboard in this project, with only the charts whose metrics the project sends.
        A second call returns the dashboard that the first one created."""
        self._require_flag(request)
        access = self.user_access_control
        if not access.check_access_level_for_resource(
            "dashboard", "editor"
        ) or not access.check_access_level_for_resource("insight", "editor"):
            raise PermissionDenied("You need editor access to dashboards and insights to create a dashboard.")
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        try:
            dashboard_id = create_suggested_dashboard(
                team=self.team, user=cast(User, request.user), suggestion_id=str(pk)
            )
        except SuggestedDashboardNotFound as error:
            raise NotFound(str(error))
        except SuggestedDashboardError as error:
            raise ValidationError(str(error))
        return Response(
            MetricsCreatedDashboardSerializer({"dashboard_id": dashboard_id}).data, status=status.HTTP_201_CREATED
        )


class MetricsDashboardTemplateViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """The metrics dashboard bank, for the PostHog staff review. The bank is instance-wide."""

    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    permission_classes = [IsStaffUser]
    lookup_value_regex = UUID_REGEX

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                enum=DashboardTemplateStatus.values,
                required=False,
                description="Only templates with this status.",
            )
        ],
        responses={200: MetricsDashboardTemplateSerializer(many=True)},
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The templates of the metrics dashboard bank, newest first."""
        raw_status = request.query_params.get("status")
        if raw_status and raw_status not in DashboardTemplateStatus.values:
            raise ValidationError({"status": "Unknown status."})
        templates = list_dashboard_templates(status=DashboardTemplateStatus(raw_status) if raw_status else None)
        return Response(MetricsDashboardTemplateSerializer([asdict(item) for item in templates], many=True).data)

    @extend_schema(responses={200: MetricsDashboardTemplateSerializer})
    def retrieve(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        try:
            template = get_dashboard_template(template_id=str(pk))
        except SuggestedDashboardNotFound as error:
            raise NotFound(str(error))
        return Response(MetricsDashboardTemplateSerializer(asdict(template)).data)

    @extend_schema(
        request=None,
        responses={
            200: MetricsCreatedDashboardSerializer,
            400: OpenApiResponse(description="This project sends none of the metrics of the template."),
        },
    )
    @action(detail=True, methods=["POST"])
    def preview(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """The unlisted dashboard that shows the template with this project's data. Built when it does not exist.
        Changes on it, by hand or with PostHog AI, become the template when it is approved."""
        tag_queries(product=Product.METRICS, feature=Feature.QUERY)
        try:
            dashboard_id = open_dashboard_template_preview(
                team=self.team, user=cast(User, request.user), template_id=str(pk)
            )
        except SuggestedDashboardNotFound as error:
            raise NotFound(str(error))
        except SuggestedDashboardError as error:
            raise ValidationError(str(error))
        return Response(MetricsCreatedDashboardSerializer({"dashboard_id": dashboard_id}).data)

    @extend_schema(request=None, responses={200: MetricsDashboardTemplateSerializer})
    @action(detail=True, methods=["POST"])
    def approve(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """Approve the template, so that projects whose metrics fit it see it as a suggestion."""
        try:
            template = approve_dashboard_template(user=cast(User, request.user), template_id=str(pk))
        except SuggestedDashboardNotFound as error:
            raise NotFound(str(error))
        except SuggestedDashboardError as error:
            raise ValidationError(str(error))
        return Response(MetricsDashboardTemplateSerializer(asdict(template)).data)

    @extend_schema(request=None, responses={200: MetricsDashboardTemplateSerializer})
    @action(detail=True, methods=["POST"])
    def reject(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> Response:
        """Reject the template. Projects stop seeing it, and the same metrics do not generate it again."""
        try:
            template = reject_dashboard_template(user=cast(User, request.user), template_id=str(pk))
        except SuggestedDashboardNotFound as error:
            raise NotFound(str(error))
        except SuggestedDashboardError as error:
            raise ValidationError(str(error))
        return Response(MetricsDashboardTemplateSerializer(asdict(template)).data)

    @extend_schema(
        parameters=[OpenApiParameter("round", OpenApiTypes.INT, required=True, description="Check round, from 1.")],
        responses={(200, "image/png"): OpenApiResponse(description="The picture of the preview dashboard.")},
    )
    @action(detail=True, methods=["GET"])
    def picture(self, request: Request, pk: str | None = None, *args: Any, **kwargs: Any) -> HttpResponse:
        """The picture that a generation round rendered of the preview dashboard."""
        try:
            round_number = int(request.query_params.get("round", ""))
        except ValueError:
            raise ValidationError({"round": "Give the round as a number."})
        try:
            content = dashboard_template_picture(template_id=str(pk), round_number=round_number)
        except SuggestedDashboardNotFound as error:
            raise NotFound(str(error))
        if content is None:
            raise NotFound("This round has no picture.")
        response = HttpResponse(content, content_type="image/png")
        response["Cache-Control"] = "private, max-age=3600"
        return response

    @extend_schema(request=None, responses={202: None})
    @action(detail=False, methods=["POST"])
    def analyze(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Analyze the metric names of this project now, and generate dashboards for new groups of metrics."""
        analyze_team_metrics_now(team=self.team)
        return Response(status=status.HTTP_202_ACCEPTED)
