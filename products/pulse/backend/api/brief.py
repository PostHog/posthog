import asyncio
from typing import cast

from django.conf import settings
from django.db.models import QuerySet

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.schema import NodeKind

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.temporal.common.client import sync_connect

from products.pulse.backend.models import BriefConfig, ProductBrief
from products.pulse.backend.sources.anchored_insights import resolve_metric_insight
from products.pulse.backend.temporal.inputs import (
    GENERATE_BRIEF_WORKFLOW_NAME,
    GenerateBriefWorkflowInputs,
    pulse_brief_workflow_id,
)

PULSE_FEATURE_FLAG = "pulse"


class BriefAnchorsSerializer(serializers.Serializer):
    dashboards = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="IDs of the dashboards this brief is anchored on.",
    )
    insights = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Short IDs of the insights this brief is anchored on.",
    )


class BriefGoalMetricSerializer(serializers.Serializer):
    insight_short_id = serializers.CharField(
        allow_blank=False,
        help_text="Short ID of the team-owned trends insight tracking progress toward the goal.",
    )


class BriefConfigSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created the config.")
    anchors = BriefAnchorsSerializer(
        required=False,
        help_text="Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards.",
    )
    goal_metric = BriefGoalMetricSerializer(
        required=False,
        allow_null=True,
        help_text="Insight whose trend measures progress toward the goal. Null when the goal is qualitative.",
    )

    class Meta:
        model = BriefConfig
        fields = [
            "id",
            "name",
            "focus_prompt",
            "anchors",
            "goal",
            "goal_metric",
            "enabled",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Human-readable name for this brief focus."},
            "focus_prompt": {
                "help_text": 'Free-text focus steering gathering and tone, e.g. "we\'re the feature flags team".'
            },
            "goal": {
                "help_text": 'Free-text goal this focus drives toward, e.g. "increase subscription usage". Briefs open with progress toward it.'
            },
            "enabled": {"help_text": "Whether this config generates briefs."},
        }

    def validate_goal_metric(self, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return value
        # Same ownership check style as the config reference on pulse_brief subscriptions, via
        # the same resolver the collectors read the metric with: a metric must be a live insight
        # in the caller's team.
        insight = resolve_metric_insight(self.context["get_team"](), value["insight_short_id"])
        if insight is None:
            raise serializers.ValidationError("This insight does not exist or does not belong to your team.")
        # Reject at write time what the collector can only silently degrade on later: the goal
        # metric contract is trends-only, matching the field's help_text.
        source_kind = ((insight.query or {}).get("source") or {}).get("kind")
        if source_kind != NodeKind.TRENDS_QUERY:
            raise serializers.ValidationError("The goal metric must be a trends insight.")
        return value

    def validate(self, attrs: dict) -> dict:
        # Explicit-key fallbacks so a PATCH sending only one of the pair validates the resulting
        # row, not just the request payload.
        goal = attrs.get("goal", self.instance.goal if self.instance else "")
        goal_metric = attrs.get("goal_metric", self.instance.goal_metric if self.instance else None)
        if goal_metric and not goal.strip():
            # Without a goal the metric is never read — reject instead of silently no-oping.
            raise serializers.ValidationError({"goal_metric": ["A goal metric requires a goal."]})
        return attrs


class ProductBriefSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who requested the brief.")
    sections = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
        help_text="Generated brief sections: kind, title, markdown, citations, confidence.",
    )
    sources_used = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Names of the brief sources that contributed items.",
    )

    class Meta:
        model = ProductBrief
        fields = [
            "id",
            "config",
            "status",
            "trigger",
            "period_days",
            "sections",
            "sources_used",
            "error",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "config": {"help_text": "The brief config this brief was generated for, if any."},
            "status": {
                "help_text": "Lifecycle status: generating, ready, quiet (nothing confident to say), or failed."
            },
            "trigger": {"help_text": "What started the generation: on_demand or scheduled."},
            "period_days": {"help_text": "Number of days the brief covers."},
            "error": {"help_text": "Error detail when status is failed."},
        }


class ProductBriefListSerializer(ProductBriefSerializer):
    # The list view stays light: full section markdown is only shipped on retrieve.
    # Omitting "sections" from fields is sufficient — DRF drops declared fields not listed there.
    class Meta(ProductBriefSerializer.Meta):
        fields = [f for f in ProductBriefSerializer.Meta.fields if f != "sections"]
        read_only_fields = fields


class GenerateBriefRequestSerializer(serializers.Serializer):
    config_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional brief config to generate for. Omit for the zero-config default brief.",
    )
    period_days = serializers.IntegerField(
        required=False,
        default=7,
        min_value=1,
        max_value=90,
        help_text="Number of days the brief should cover. Defaults to 7.",
    )


class BriefConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    serializer_class = BriefConfigSerializer
    posthog_feature_flag = PULSE_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    # Fail-closed manager raises if `.all()` runs at import; the real per-request
    # scoping happens in safely_get_queryset.
    queryset = BriefConfig.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[BriefConfig]) -> QuerySet[BriefConfig]:
        return BriefConfig.objects.for_team(self.team_id).select_related("created_by").order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(team=self.team, created_by=cast(User, self.request.user))


class ProductBriefViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    serializer_class = ProductBriefSerializer
    posthog_feature_flag = PULSE_FEATURE_FLAG
    permission_classes = [PostHogFeatureFlagPermission]
    queryset = ProductBrief.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[ProductBrief]) -> QuerySet[ProductBrief]:
        return (
            ProductBrief.objects.for_team(self.team_id).select_related("created_by", "config").order_by("-created_at")
        )

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return ProductBriefListSerializer
        return ProductBriefSerializer

    @extend_schema(
        request=GenerateBriefRequestSerializer,
        responses={
            201: ProductBriefSerializer,
            409: OpenApiResponse(description="A generation for this brief is already in progress"),
        },
    )
    @action(methods=["POST"], detail=False, url_path="generate")
    def generate(self, request: Request, **kwargs) -> Response:
        if not self.team.organization.is_ai_data_processing_approved:
            # Cross-boundary contract: the frontend (pulseLogic AI_CONSENT_ERROR_CODE) matches this
            # code to show the consent banner — rename both sides together.
            raise ValidationError(
                "AI data processing must be approved for this organization to generate briefs.",
                code="ai_consent_required",
            )

        request_serializer = GenerateBriefRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        config_id = request_serializer.validated_data.get("config_id")
        period_days = request_serializer.validated_data["period_days"]

        config = None
        if config_id is not None:
            config = BriefConfig.objects.for_team(self.team_id).filter(id=config_id).first()
            if config is None:
                raise ValidationError("Brief config not found.")

        brief = ProductBrief.objects.for_team(self.team_id).create(
            team_id=self.team_id,
            config=config,
            created_by=cast(User, request.user),
            status=ProductBrief.Status.GENERATING,
            trigger=ProductBrief.Trigger.ON_DEMAND,
            period_days=period_days,
        )

        try:
            temporal = sync_connect()
            asyncio.run(
                temporal.start_workflow(
                    GENERATE_BRIEF_WORKFLOW_NAME,
                    GenerateBriefWorkflowInputs(
                        team_id=self.team.id,
                        brief_id=str(brief.id),
                        brief_config_id=str(config.id) if config else None,
                        period_days=period_days,
                    ),
                    # Keyed on team+config (not brief id) so a second generate while one is
                    # running for the same focus hits WorkflowAlreadyStartedError.
                    id=pulse_brief_workflow_id(self.team_id, str(config.id) if config else None),
                    task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                )
            )
        except WorkflowAlreadyStartedError:
            # Collision policy (shared with cleanup_skipped_pulse_brief in the scheduled
            # subscription path): delete the stranded GENERATING row.
            brief.delete()
            return Response({"detail": "Brief generation already in progress"}, status=status.HTTP_409_CONFLICT)
        except Exception as exc:
            # Dispatch never reached Temporal — mark the row FAILED so it can't strand in GENERATING.
            ProductBrief.objects.for_team(self.team_id).filter(id=brief.id).update(
                status=ProductBrief.Status.FAILED, error=str(exc)
            )
            raise

        return Response(ProductBriefSerializer(brief).data, status=status.HTTP_201_CREATED)
