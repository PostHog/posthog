import asyncio
from typing import cast

from django.conf import settings
from django.db.models import QuerySet

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.common.client import sync_connect

from products.pulse.backend.config import WORKFLOW_EXECUTION_TIMEOUT
from products.pulse.backend.models import BriefConfig, ProductBrief
from products.pulse.backend.temporal.inputs import GENERATE_BRIEF_WORKFLOW_NAME, GenerateBriefWorkflowInputs

PULSE_FEATURE_FLAG = "pulse"

logger = structlog.get_logger(__name__)


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


class BriefSettingsSerializer(serializers.Serializer):
    # Per-config tunables overriding config.DEFAULT_BRIEF_SETTINGS. Each optional and range-bounded;
    # ranges kept in sync with config._RANGES. Omitted keys keep their default.
    min_abs_change_pct = serializers.FloatField(
        required=False,
        min_value=1.0,
        max_value=1000.0,
        help_text="Minimum absolute percent change for a movement to count as significant. Default 20.",
    )
    min_baseline_value = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1_000_000.0,
        help_text="Minimum per-sample baseline volume before a movement is considered. Default 10.",
    )
    max_anchor_insights = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Maximum anchor insights gathered per brief. Default 10.",
    )
    fallback_dashboard_count = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=20,
        help_text="How many recent dashboards to pull insights from when no anchors are set. Default 3.",
    )
    confidence_threshold = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Minimum confidence for a section or opportunity to survive the gate. Default 0.6.",
    )
    max_opportunities = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=20,
        help_text="Maximum opportunities kept per brief. Default 3.",
    )


class BriefConfigSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created the config.")
    anchors = BriefAnchorsSerializer(
        required=False,
        help_text="Anchor resources the brief gathers movements from. Empty anchors fall back to the team's most recently accessed dashboards.",
    )
    settings = BriefSettingsSerializer(
        required=False,
        help_text="Per-config tunables overriding the system defaults. Omitted knobs keep their default.",
    )

    class Meta:
        model = BriefConfig
        fields = [
            "id",
            "name",
            "focus_prompt",
            "anchors",
            "settings",
            "enabled",
            "deleted",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "created_by", "updated_at"]
        extra_kwargs = {
            "name": {"help_text": "Human-readable name for this brief focus."},
            "focus_prompt": {
                "help_text": 'Free-text focus steering gathering and tone, e.g. "we\'re the feature flags team". Max 2000 characters.'
            },
            "enabled": {"help_text": "Whether this config generates briefs."},
            "deleted": {
                "help_text": "Soft-delete flag. Deleted configs are hidden from lists but recoverable by patching this back to false."
            },
        }


class PeriodSerializer(serializers.Serializer):
    period_type = serializers.ChoiceField(
        choices=["last_n_days", "since_last_run"],
        source="type",
        help_text="How the brief window is chosen: a fixed lookback (last_n_days) or since the last ready brief.",
    )
    days = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=90,
        help_text="Lookback length in days. Required and used only when period_type is last_n_days.",
    )

    def validate(self, attrs: dict) -> dict:
        if attrs.get("type") == "last_n_days" and attrs.get("days") is None:
            raise serializers.ValidationError({"days": "days is required when period_type is last_n_days."})
        return attrs


class ProductBriefSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who requested the brief.")
    period = PeriodSerializer(read_only=True, help_text="The resolved-at-gather period spec the brief covers.")
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
            "period",
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
    period = PeriodSerializer(
        required=False,
        help_text="Period the brief should cover. Defaults to the last 7 days.",
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
        configs = BriefConfig.objects.for_team(self.team_id).select_related("created_by").order_by("-created_at")
        # Lists hide soft-deleted configs; detail routes keep them reachable so a
        # PATCH {"deleted": false} can restore one.
        if self.action == "list":
            configs = configs.filter(deleted=False)
        return configs

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(team=self.team, created_by=cast(User, self.request.user))
        report_user_action(
            cast(User, self.request.user),
            "pulse config created",
            {"config_id": str(serializer.instance.id)},
            team=self.team,
        )

    def perform_destroy(self, instance: BriefConfig) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted", "updated_at"])
        report_user_action(
            cast(User, self.request.user),
            "pulse config deleted",
            {"config_id": str(instance.id)},
            team=self.team,
        )


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
            500: OpenApiResponse(description="Dispatch to the generation workflow failed; the brief is marked failed"),
        },
    )
    @action(methods=["POST"], detail=False, url_path="generate")
    def generate(self, request: Request, **kwargs) -> Response:
        if not self.team.organization.is_ai_data_processing_approved:
            raise ValidationError("AI data processing must be approved for this organization to generate briefs.")

        request_serializer = GenerateBriefRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        config_id = request_serializer.validated_data.get("config_id")
        # validate() normalizes source="type"; rebuild the stored spec (default: last 7 days).
        validated_period = request_serializer.validated_data.get("period")
        if validated_period:
            period = {"type": validated_period["type"]}
            if validated_period.get("days") is not None:
                period["days"] = validated_period["days"]
        else:
            period = {"type": "last_n_days", "days": 7}

        config = None
        if config_id is not None:
            config = BriefConfig.objects.for_team(self.team_id).filter(id=config_id, deleted=False).first()
            if config is None:
                raise ValidationError("Brief config not found.")

        user = cast(User, request.user)
        brief = ProductBrief.objects.for_team(self.team_id).create(
            team_id=self.team_id,
            config=config,
            created_by=user,
            status=ProductBrief.Status.GENERATING,
            trigger=ProductBrief.Trigger.ON_DEMAND,
            period=period,
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
                        period=period,
                        slo=SloConfig(
                            operation=SloOperation.PULSE_BRIEF_GENERATION,
                            area=SloArea.ANALYTIC_PLATFORM,
                            team_id=self.team_id,
                            resource_id=str(brief.id),
                            distinct_id=str(user.distinct_id),
                            start_properties={"trigger": "on_demand", "config_id": str(config.id) if config else None},
                            completion_properties={
                                "trigger": "on_demand",
                                "config_id": str(config.id) if config else None,
                            },
                        ),
                    ),
                    # Keyed on team+config (not brief id) so a second generate while one is
                    # running for the same focus hits WorkflowAlreadyStartedError.
                    id=f"pulse-brief-{self.team_id}-{config.id if config else 'default'}",
                    task_queue=settings.ANALYTICS_PLATFORM_TASK_QUEUE,
                    execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
                )
            )
        except WorkflowAlreadyStartedError:
            report_user_action(
                user,
                "pulse brief generation contended",
                {"config_id": str(config.id) if config else None},
                team=self.team,
            )
            try:
                brief.delete()
            except Exception:
                # A failed delete must not strand the row in GENERATING.
                logger.exception("pulse_brief_duplicate_cleanup_failed", team_id=self.team_id, brief_id=str(brief.id))
                ProductBrief.objects.for_team(self.team_id).filter(id=brief.id).update(
                    status=ProductBrief.Status.FAILED, error="Brief generation already in progress"
                )
            return Response({"detail": "Brief generation already in progress"}, status=status.HTTP_409_CONFLICT)
        except Exception as exc:
            # Dispatch never reached Temporal — mark the row FAILED so it can't strand in GENERATING.
            # Return the failed brief's id+status (not a bare raise) so the frontend can surface it.
            logger.exception("pulse_brief_dispatch_failed", team_id=self.team_id, brief_id=str(brief.id))
            ProductBrief.objects.for_team(self.team_id).filter(id=brief.id).update(
                status=ProductBrief.Status.FAILED, error=str(exc)
            )
            return Response(
                {
                    "detail": "Brief generation could not be started.",
                    "brief": {"id": str(brief.id), "status": ProductBrief.Status.FAILED.value},
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        report_user_action(
            user,
            "pulse brief generated",
            {"config_id": str(config.id) if config else None, "period": period, "trigger": "on_demand"},
            team=self.team,
        )
        return Response(ProductBriefSerializer(brief).data, status=status.HTTP_201_CREATED)
