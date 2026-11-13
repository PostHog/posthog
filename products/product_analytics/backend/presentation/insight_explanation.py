import re
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
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import AccessControlPermission, APIScopePermission, TeamMemberAccessPermission

from products.product_analytics.backend.facade import api
from products.product_analytics.backend.facade.contracts import ChartExplanation, ChartExplanationAuthor
from products.product_analytics.backend.facade.models import Insight

# The text caps match the explain-chart MCP tool's input schema.
MAX_EXPLANATION_BYTES = 300_000
MAX_EVIDENCE_QUERY_BYTES = 10_000
MAX_SERIES_POINTS = 5_000
MAX_FUNNEL_STEPS = 50
# Evidence may only link to GitHub pull requests and commits. Anything else is a query or a saved insight.
GITHUB_CHANGE_LINK = re.compile(
    r"https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+/(pull/\d+|commit/[0-9a-fA-F]{7,40})/?"
)


class InsightExplanationCreateThrottle(UserRateThrottle):
    scope = "insight_explanation_create"
    rate = "120/hour"


class StoryEvidenceChartType(models.TextChoices):
    LINE = "line", "Line"
    BAR = "bar", "Bar"


class ChartExplanationShape(models.TextChoices):
    TIME_SERIES = "time_series", "Time series"
    FUNNEL_STEPS = "funnel_steps", "Funnel steps"


QUERY_KIND_BY_SHAPE = {
    ChartExplanationShape.TIME_SERIES: "TrendsQuery",
    ChartExplanationShape.FUNNEL_STEPS: "FunnelsQuery",
}


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
    series = StoryEvidenceSeriesSerializer(many=True, max_length=20, help_text="The lines or bars to draw.")  # type: ignore[call-arg]
    yAxisLabel = serializers.CharField(allow_null=True, allow_blank=True, help_text="The y-axis label, if any.")


class StoryEvidenceSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=400, help_text="One fact that supports the chapter, in one sentence.")
    query = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        allow_null=True,
        required=False,
        help_text="The query that shows the fact. The page links to it.",
    )
    insightShortId = serializers.RegexField(
        r"^[A-Za-z0-9]{8}$",
        allow_null=True,
        required=False,
        help_text="The short id of a saved insight that shows the fact. The page links to it.",
    )
    url = serializers.CharField(
        max_length=500,
        allow_null=True,
        required=False,
        help_text="A link to the GitHub pull request or commit behind the fact. No other links are accepted.",
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

    def validate_url(self, value: str | None) -> str | None:
        if value is not None and not GITHUB_CHANGE_LINK.fullmatch(value):
            raise serializers.ValidationError("Only links to a GitHub pull request or commit are accepted.")
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
    summary = serializers.CharField(
        allow_null=True, allow_blank=True, max_length=400, help_text="What happened in this moment."
    )
    cause = serializers.CharField(
        allow_null=True, allow_blank=True, max_length=600, help_text="The likely cause of this moment."
    )
    confidence = serializers.ChoiceField(
        choices=StoryConfidence.choices, allow_null=True, help_text="How sure the investigation is of the cause."
    )
    confidenceReason = serializers.CharField(
        allow_null=True, allow_blank=True, max_length=200, help_text="Why the confidence is what it is."
    )
    evidence = StoryEvidenceSerializer(many=True, max_length=6, help_text="The facts behind the cause.")  # type: ignore[call-arg]


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


class StoryFunnelStepSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, max_length=400, help_text="The step's name.")
    count = serializers.IntegerField(min_value=0, help_text="How many reached the step.")


class ExplainChartDataSerializer(serializers.Serializer):
    shape = serializers.ChoiceField(
        choices=ChartExplanationShape.choices,
        default=ChartExplanationShape.TIME_SERIES,
        help_text="What the explanation walks through, whichever insight drew the chart. A funnel over time is a time series too.",
    )
    query = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        help_text="The insight query the explanation follows: a TrendsQuery for a time series, a FunnelsQuery for funnel steps.",
    )
    results = StorySeriesResultSerializer(  # type: ignore[call-arg]
        many=True,
        max_length=1_000,
        required=False,
        help_text="Every series on the chart when it was explained. Time series only.",
    )
    steps = StoryFunnelStepSerializer(  # type: ignore[call-arg]
        many=True,
        min_length=2,
        max_length=MAX_FUNNEL_STEPS,
        required=False,
        help_text="The followed breakdown value's steps when it was explained. Funnel steps only.",
    )
    breakdowns = serializers.ListField(
        child=serializers.CharField(allow_blank=True, max_length=400),
        max_length=1_000,
        required=False,
        help_text="Every breakdown value's label, empty when the funnel has no breakdown. Funnel steps only.",
    )
    seriesIndex = serializers.IntegerField(
        min_value=0,
        help_text="The index in `results` the explanation follows, or the index in `breakdowns` on a funnel.",
    )
    insightName = serializers.CharField(
        allow_null=True, allow_blank=True, max_length=400, help_text="The insight's name."
    )
    lastPointInProgress = serializers.BooleanField(
        required=False, help_text="Whether the last point's period had not ended yet. Time series only."
    )
    headline = serializers.CharField(
        max_length=300, help_text="One sentence a person could read in place of the whole explanation."
    )
    chapters = StoryChapterSerializer(  # type: ignore[call-arg]
        many=True, min_length=1, max_length=8, help_text="The moments that stand out, in reading order."
    )
    warnings = serializers.ListField(
        child=serializers.JSONField(),
        max_length=20,
        required=False,
        help_text="Warnings the chart's query came back with.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        shape = attrs["shape"]
        if attrs["query"].get("kind", "TrendsQuery") != QUERY_KIND_BY_SHAPE[shape]:
            raise serializers.ValidationError({"query": "The query does not match the explanation's shape."})
        if shape == ChartExplanationShape.FUNNEL_STEPS:
            return self._validate_funnel_steps(attrs)
        return self._validate_time_series(attrs)

    def _validate_funnel_steps(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "steps" not in attrs:
            raise serializers.ValidationError({"steps": "A funnel explanation needs its steps."})
        breakdowns = attrs.setdefault("breakdowns", [])
        if attrs["seriesIndex"] >= max(len(breakdowns), 1):
            raise serializers.ValidationError({"seriesIndex": "There is no breakdown value at this index."})
        attrs.pop("results", None)
        attrs.pop("lastPointInProgress", None)
        return attrs

    def _validate_time_series(self, attrs: dict[str, Any]) -> dict[str, Any]:
        for field in ("results", "lastPointInProgress"):
            if field not in attrs:
                raise serializers.ValidationError({field: "A time series explanation needs this field."})
        attrs.pop("steps", None)
        attrs.pop("breakdowns", None)
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
        self._report_saved(request, explanation, updated=False)
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
        self._report_saved(request, explanation, updated=True)
        return Response(ChartExplanationSerializer(instance=explanation).data)

    def _report_saved(self, request: Request, explanation: ChartExplanation, *, updated: bool) -> None:
        # Each save hands the agent a link, so this counts the links people are given, split by MCP client.
        report_user_action(
            cast(User, request.user),
            "explain chart link saved",
            {
                "explanation_id": str(explanation.id),
                "insight_id": self.insight.short_id,
                "updated": updated,
            },
            team=self.team,
            request=request,
        )

    @extend_schema(responses={200: ChartExplanationSerializer})
    def retrieve(self, request: Request, pk: UUID, **kwargs: Any) -> Response:
        explanation = api.get_insight_explanation(
            team_id=self.insight.team_id, insight_id=self.insight.id, explanation_id=pk
        )
        if explanation is None:
            raise NotFound("Explanation not found.")
        return Response(ChartExplanationSerializer(instance=explanation).data)
