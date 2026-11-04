import json
from functools import cached_property
from typing import Any, cast
from uuid import UUID

from django.db import models

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle
from rest_framework.views import APIView
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import AccessControlPermission, APIScopePermission, TeamMemberAccessPermission

from products.product_analytics.backend.facade import api
from products.product_analytics.backend.facade.contracts import ChartExplanation, ChartExplanationAuthor
from products.product_analytics.backend.facade.models import Insight

# The text caps match the explain-chart MCP tool's input schema.
MAX_EXPLANATION_BYTES = 300_000
MAX_EVIDENCE_QUERY_BYTES = 10_000
MAX_SERIES_POINTS = 5_000


class InsightExplanationCreateThrottle(UserRateThrottle):
    scope = "insight_explanation_create"
    rate = "120/hour"


class StoryEvidenceChartType(models.TextChoices):
    LINE = "line", "Line"
    BAR = "bar", "Bar"


class ChartExplanationShape(models.TextChoices):
    TIME_SERIES = "time_series", "Time series"


class StoryEvidenceQueryTool(models.TextChoices):
    QUERY_TRENDS = "query-trends", "Trends"
    QUERY_FUNNEL = "query-funnel", "Funnel"
    QUERY_RETENTION = "query-retention", "Retention"
    QUERY_STICKINESS = "query-stickiness", "Stickiness"
    QUERY_PATHS = "query-paths", "Paths"
    QUERY_LIFECYCLE = "query-lifecycle", "Lifecycle"


QUERY_KIND_BY_TOOL = {
    StoryEvidenceQueryTool.QUERY_TRENDS: "TrendsQuery",
    StoryEvidenceQueryTool.QUERY_FUNNEL: "FunnelsQuery",
    StoryEvidenceQueryTool.QUERY_RETENTION: "RetentionQuery",
    StoryEvidenceQueryTool.QUERY_STICKINESS: "StickinessQuery",
    StoryEvidenceQueryTool.QUERY_PATHS: "PathsQuery",
    StoryEvidenceQueryTool.QUERY_LIFECYCLE: "LifecycleQuery",
}


class StoryConfidence(models.TextChoices):
    HIGH = "high", "High confidence"
    MEDIUM = "medium", "Medium confidence"
    LOW = "low", "Low confidence"


class StoryEvidenceSeriesSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, help_text="The breakdown value or column this line draws.")
    values = serializers.ListField(
        child=serializers.FloatField(allow_null=True),
        max_length=MAX_SERIES_POINTS,
        help_text="One value per label. Null where the breakdown value has no row for that point.",
    )


class StoryEvidenceChartSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=StoryEvidenceChartType.choices, help_text="How the evidence chart draws its series."
    )
    labels = serializers.ListField(
        child=serializers.CharField(allow_blank=True), max_length=MAX_SERIES_POINTS, help_text="The x-axis points."
    )
    ticks = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        max_length=MAX_SERIES_POINTS,
        required=False,
        help_text="The axis label of each point, which leaves out a date that repeats.",
    )
    series = StoryEvidenceSeriesSerializer(many=True, max_length=20, help_text="The lines or bars to draw.")
    yAxisLabel = serializers.CharField(allow_null=True, allow_blank=True, help_text="The y-axis label, if any.")


class StoryEvidenceSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=400, help_text="One fact that supports the chapter, in one sentence.")
    query = serializers.DictField(
        child=serializers.JSONField(),
        allow_null=True,
        required=False,
        help_text="The query that shows the fact. The page links to it.",
    )
    queryTool = serializers.ChoiceField(
        choices=StoryEvidenceQueryTool.choices,
        allow_null=True,
        required=False,
        help_text="The MCP query tool that can redraw `query`. The page redraws the query only when this is set.",
    )
    chart = StoryEvidenceChartSerializer(
        allow_null=True, required=False, help_text="The fact drawn as a chart, from its SQL."
    )

    def validate_query(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and len(json.dumps(value)) > MAX_EVIDENCE_QUERY_BYTES:
            raise serializers.ValidationError("The query is too large to save.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        tool = attrs.get("queryTool")
        if tool is not None:
            query = attrs.get("query") or {}
            if query.get("kind", "TrendsQuery") != QUERY_KIND_BY_TOOL[tool]:
                raise serializers.ValidationError({"queryTool": "This tool cannot redraw a query of this kind."})
        return attrs


class StoryChapterSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=80, help_text="The moment on the chart this chapter explains.")
    range = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        min_length=2,
        max_length=2,
        allow_null=True,
        help_text="Inclusive indexes into the series' points. Null when the chapter's dates match no point.",
    )
    summary = serializers.CharField(allow_null=True, max_length=400, help_text="What happened in this moment.")
    cause = serializers.CharField(allow_null=True, max_length=600, help_text="The likely cause of this moment.")
    confidence = serializers.ChoiceField(
        choices=StoryConfidence.choices, allow_null=True, help_text="How sure the investigation is of the cause."
    )
    confidenceReason = serializers.CharField(
        allow_null=True, max_length=200, help_text="Why the confidence is what it is."
    )
    evidence = StoryEvidenceSerializer(many=True, max_length=6, help_text="The facts behind the cause.")


class StorySeriesResultSerializer(serializers.Serializer):
    label = serializers.CharField(  # type: ignore[assignment]
        required=False, allow_blank=True, max_length=400, help_text="The series name."
    )
    data = serializers.ListField(  # type: ignore[assignment]
        child=serializers.FloatField(),
        max_length=MAX_SERIES_POINTS,
        required=False,
        help_text="One value per point. Saved for the followed series only.",
    )
    days = serializers.ListField(
        child=serializers.CharField(),
        max_length=MAX_SERIES_POINTS,
        required=False,
        help_text="The date of each point, in the query's timezone. Saved for the followed series only.",
    )


class ExplainChartDataSerializer(serializers.Serializer):
    shape = serializers.ChoiceField(
        choices=ChartExplanationShape.choices,
        default=ChartExplanationShape.TIME_SERIES,
        help_text="What the explanation walks through, whichever insight drew the chart. A funnel over time is a time series too.",
    )
    query = serializers.DictField(child=serializers.JSONField(), help_text="The insight query the explanation follows.")
    results = StorySeriesResultSerializer(
        many=True, max_length=1_000, help_text="Every series on the chart when it was explained."
    )
    seriesIndex = serializers.IntegerField(min_value=0, help_text="The index in `results` the explanation follows.")
    insightName = serializers.CharField(
        allow_null=True, allow_blank=True, max_length=400, help_text="The insight's name."
    )
    lastPointInProgress = serializers.BooleanField(help_text="Whether the last point's period had not ended yet.")
    headline = serializers.CharField(
        max_length=300, help_text="One sentence a person could read in place of the whole explanation."
    )
    chapters = StoryChapterSerializer(
        many=True, min_length=1, max_length=8, help_text="The moments that stand out, in reading order."
    )
    warnings = serializers.ListField(
        child=serializers.JSONField(),
        max_length=20,
        required=False,
        help_text="Warnings the chart's query came back with.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        followed = attrs["seriesIndex"]
        if followed >= len(attrs["results"]):
            raise serializers.ValidationError({"seriesIndex": "There is no series at this index."})
        # The page draws the live chart and reads the points of the followed series only.
        attrs["results"] = [
            result if index == followed else {key: value for key, value in result.items() if key == "label"}
            for index, result in enumerate(attrs["results"])
        ]
        return attrs


class InsightExplanationCreateSerializer(serializers.Serializer):
    data = ExplainChartDataSerializer(  # type: ignore[assignment]
        help_text="The chart explanation, as the insight page shows it."
    )

    def validate_data(self, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_EXPLANATION_BYTES:
            raise serializers.ValidationError("The explanation is too large to save.")
        return value


class ChartExplanationAuthorSerializer(DataclassSerializer):
    class Meta:
        dataclass = ChartExplanationAuthor
        extra_kwargs = {
            "id": {"help_text": "The user's id."},
            "first_name": {"help_text": "The user's first name."},
            "last_name": {"help_text": "The user's last name."},
            "email": {"help_text": "The user's email address."},
        }


class ChartExplanationSerializer(DataclassSerializer):
    data = ExplainChartDataSerializer(  # type: ignore[assignment]
        help_text="The chart explanation, as the insight page shows it."
    )
    created_by = ChartExplanationAuthorSerializer(
        allow_null=True, help_text="Who saved the explanation, directly or through an agent."
    )

    class Meta:
        dataclass = ChartExplanation
        extra_kwargs = {
            "id": {"help_text": "The explanation's id, which its link carries."},
            "insight_id": {"help_text": "The insight the explanation belongs to."},
            "created_at": {"help_text": "When the explanation was first saved."},
        }


class InsightExplanationAccessPermission(AccessControlPermission):
    # A create is refused at the resource level before object grants are read, so the view checks the parent insight.
    def has_permission(self, request: Request, view: APIView) -> bool:
        return getattr(view, "action", None) in ("create", "update") or super().has_permission(request, view)


class InsightExplanationViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "insight"
    scope_object_read_actions = ["retrieve"]
    scope_object_write_actions = ["create", "update"]
    path_parameters = {"pk": UUID, "insight_id": int}

    @cached_property
    def insight(self) -> Insight:
        insight = Insight.objects.filter(
            pk=self.kwargs["parent_lookup_insight_id"], team__project_id=self.team.project_id, deleted=False
        ).first()
        if insight is None:
            raise NotFound("Insight not found.")
        self.check_object_permissions(self.request, insight)
        return insight

    def dangerously_get_permissions(self) -> list[BasePermission]:
        return [
            IsAuthenticated(),
            APIScopePermission(),
            TeamMemberAccessPermission(),
            InsightExplanationAccessPermission(),
        ]

    def get_throttles(self) -> list[BaseThrottle]:
        throttles = super().get_throttles()
        if self.action in ("create", "update"):
            throttles.append(InsightExplanationCreateThrottle())
        return throttles

    @validated_request(
        request_serializer=InsightExplanationCreateSerializer,
        responses={201: OpenApiResponse(response=ChartExplanationSerializer)},
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        explanation = api.create_insight_explanation(
            team_id=self.insight.team_id,
            insight_id=self.insight.id,
            user_id=cast(User, request.user).id,
            data=request.validated_data["data"],
        )
        return Response(ChartExplanationSerializer(instance=explanation).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=InsightExplanationCreateSerializer,
        responses={200: OpenApiResponse(response=ChartExplanationSerializer)},
    )
    def update(self, request: ValidatedRequest, pk: UUID, **kwargs: Any) -> Response:
        explanation = api.update_insight_explanation(
            team_id=self.insight.team_id,
            insight_id=self.insight.id,
            explanation_id=pk,
            user_id=cast(User, request.user).id,
            data=request.validated_data["data"],
        )
        if explanation is None:
            raise NotFound("You saved no explanation of this insight with this id.")
        return Response(ChartExplanationSerializer(instance=explanation).data)

    @extend_schema(responses={200: ChartExplanationSerializer})
    def retrieve(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        explanation = api.get_insight_explanation(
            team_id=self.insight.team_id, insight_id=self.insight.id, explanation_id=pk
        )
        if explanation is None:
            raise NotFound("Explanation not found.")
        return Response(ChartExplanationSerializer(instance=explanation).data)
