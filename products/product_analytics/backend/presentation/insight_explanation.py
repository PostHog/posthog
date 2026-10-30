import json
from functools import cached_property
from typing import Any

from django.db import models
from django.db.models import QuerySet

from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.throttling import BaseThrottle, UserRateThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.product_analytics.backend.models import Insight, InsightExplanation

MAX_EXPLANATION_BYTES = 1_000_000


class InsightExplanationCreateThrottle(UserRateThrottle):
    scope = "insight_explanation_create"
    rate = "120/hour"


class StoryEvidenceChartType(models.TextChoices):
    LINE = "line", "Line"
    BAR = "bar", "Bar"


class StoryConfidence(models.TextChoices):
    HIGH = "high", "High confidence"
    MEDIUM = "medium", "Medium confidence"
    LOW = "low", "Low confidence"


class StoryEvidenceSeriesSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True, help_text="The breakdown value or column this line draws.")
    values = serializers.ListField(
        child=serializers.FloatField(allow_null=True),
        help_text="One value per label. Null where the breakdown value has no row for that point.",
    )


class StoryEvidenceChartSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=StoryEvidenceChartType.choices, help_text="How the evidence chart draws its series."
    )
    labels = serializers.ListField(child=serializers.CharField(allow_blank=True), help_text="The x-axis points.")
    ticks = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        required=False,
        help_text="The axis label of each point, which leaves out a date that repeats.",
    )
    series = StoryEvidenceSeriesSerializer(many=True, help_text="The lines or bars to draw.")
    yAxisLabel = serializers.CharField(allow_null=True, allow_blank=True, help_text="The y-axis label, if any.")


class StoryEvidenceSerializer(serializers.Serializer):
    text = serializers.CharField(help_text="One fact that supports the chapter.")
    url = serializers.URLField(allow_null=True, help_text="A PostHog link that shows the fact.")
    query = serializers.DictField(
        child=serializers.JSONField(), allow_null=True, required=False, help_text="The query that shows the fact."
    )
    queryTool = serializers.CharField(
        allow_null=True, required=False, help_text="The MCP query tool that can redraw `query`."
    )
    chart = StoryEvidenceChartSerializer(
        allow_null=True, required=False, help_text="The fact drawn as a chart, from its SQL."
    )


class StoryChapterSerializer(serializers.Serializer):
    title = serializers.CharField(help_text="The moment on the chart this chapter explains.")
    range = serializers.ListField(
        child=serializers.IntegerField(min_value=0),
        min_length=2,
        max_length=2,
        allow_null=True,
        help_text="Inclusive indexes into the series' points. Null when the chapter's dates match no point.",
    )
    summary = serializers.CharField(allow_null=True, help_text="What happened in this moment.")
    cause = serializers.CharField(allow_null=True, help_text="The likely cause of this moment.")
    confidence = serializers.ChoiceField(
        choices=StoryConfidence.choices, allow_null=True, help_text="How sure the investigation is of the cause."
    )
    confidenceReason = serializers.CharField(allow_null=True, help_text="Why the confidence is what it is.")
    evidence = StoryEvidenceSerializer(many=True, help_text="The facts behind the cause.")


class StorySeriesResultSerializer(serializers.Serializer):
    label = serializers.CharField(required=False, allow_blank=True, help_text="The series name.")
    data = serializers.ListField(child=serializers.FloatField(), required=False, help_text="One value per point.")
    days = serializers.ListField(
        child=serializers.CharField(), required=False, help_text="The date of each point, in the query's timezone."
    )


class ExplainChartDataSerializer(serializers.Serializer):
    query = serializers.DictField(child=serializers.JSONField(), help_text="The TrendsQuery the explanation follows.")
    results = StorySeriesResultSerializer(many=True, help_text="Every series on the chart when it was explained.")
    seriesIndex = serializers.IntegerField(min_value=0, help_text="The index in `results` the explanation follows.")
    insightName = serializers.CharField(allow_null=True, allow_blank=True, help_text="The insight's name.")
    lastPointInProgress = serializers.BooleanField(help_text="Whether the last point's period had not ended yet.")
    headline = serializers.CharField(help_text="One sentence a person could read in place of the whole explanation.")
    chapters = StoryChapterSerializer(many=True, help_text="The moments that stand out, in reading order.")
    warnings = serializers.ListField(
        child=serializers.JSONField(), required=False, help_text="Warnings the chart's query came back with."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["seriesIndex"] >= len(attrs["results"]):
            raise serializers.ValidationError({"seriesIndex": "There is no series at this index."})
        return attrs


class InsightExplanationSerializer(serializers.ModelSerializer):
    data = ExplainChartDataSerializer(help_text="The chart explanation, as the insight page shows it.")

    class Meta:
        model = InsightExplanation
        fields = ["id", "data", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_data(self, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value)) > MAX_EXPLANATION_BYTES:
            raise serializers.ValidationError("The explanation is too large to save.")
        return value

    def create(self, validated_data: dict[str, Any]) -> InsightExplanation:
        view = self.context["view"]
        return InsightExplanation.objects.create(
            team_id=view.team_id,
            insight=view.insight,
            created_by=self.context["request"].user,
            data=validated_data["data"],
        )


class InsightExplanationViewSet(
    TeamAndOrgViewSetMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    scope_object = "insight"
    # Saving an explanation changes nothing anyone else sees, so it needs only read access to the insight.
    scope_object_read_actions = ["retrieve", "create"]
    scope_object_write_actions: list[str] = []
    queryset = InsightExplanation.objects.unscoped()
    serializer_class = InsightExplanationSerializer

    @cached_property
    def insight(self) -> Insight:
        try:
            insight = Insight.objects.filter(
                pk=int(self.parents_query_dict["insight_id"]), team__project_id=self.team.project_id, deleted=False
            ).first()
        except ValueError:
            raise NotFound("Insight not found.")
        if insight is None or not self.user_access_control.check_access_level_for_object(insight, "viewer"):
            raise NotFound("Insight not found.")
        return insight

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(insight=self.insight)

    def get_throttles(self) -> list[BaseThrottle]:
        throttles = super().get_throttles()
        if self.action == "create":
            throttles.append(InsightExplanationCreateThrottle())
        return throttles
