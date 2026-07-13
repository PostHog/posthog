import asyncio
from typing import Any, cast, get_args

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

from posthog.schema import NodeKind

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission
from posthog.slo.types import SloArea, SloConfig, SloOperation
from posthog.temporal.common.client import sync_connect

from products.pulse.backend.config import WORKFLOW_EXECUTION_TIMEOUT
from products.pulse.backend.generation.goal import MetricState
from products.pulse.backend.models import BriefConfig, ProductBrief
from products.pulse.backend.sources.anchored_insights import resolve_metric_insight
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
    max_annotations = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        help_text="Maximum annotations gathered as context per brief. Default 20.",
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
    settings = BriefSettingsSerializer(
        required=False,
        help_text="Per-config tunables overriding the system defaults. Omitted knobs keep their default.",
    )
    # Required, non-blank: pursuing a goal is the point of a focus, so every config states one.
    # partial_update skips required, so a PATCH that omits goal keeps the stored one; a PATCH
    # sending "" is rejected by allow_blank=False, so an existing goal can't be cleared.
    goal = serializers.CharField(
        required=True,
        allow_blank=False,
        help_text='Free-text goal this focus drives toward, e.g. "increase subscription usage". Briefs open with progress toward it.',
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
            "settings",
            "enabled",
            "deleted",
            "accountability_min_age_days",
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
            "accountability_min_age_days": {
                "min_value": 1,
                "help_text": "How many days old a surfaced opportunity must be before the accountability section re-scores it. Defaults to 7.",
            },
        }

    def validate_goal(self, value: str) -> str:
        # allow_blank=False rejects "", but a whitespace-only goal is just as absent.
        if not value.strip():
            raise serializers.ValidationError("This field may not be blank.")
        return value

    def validate_goal_metric(self, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return value
        # A metric must be a live insight in the caller's team, resolved via the same helper the
        # collectors read the metric with.
        insight = resolve_metric_insight(self.context["get_team"](), value["insight_short_id"])
        if insight is None:
            raise serializers.ValidationError("This insight does not exist or does not belong to your team.")
        # Reject at write time what the collector can only silently degrade on later: the goal
        # metric contract is trends-only, matching the field's help_text. Guard the query shape —
        # the JSONField can hold a non-dict, and .get() on that would 500 instead of validating.
        query = insight.query if isinstance(insight.query, dict) else {}
        source = query.get("source")
        source_kind = source.get("kind") if isinstance(source, dict) else None
        if source_kind != NodeKind.TRENDS_QUERY:
            raise serializers.ValidationError("The goal metric must be a trends insight.")
        # Store the discriminated shape so non-insight goal sources (events, experiment
        # conversions) can be added later without a migration. The API input stays
        # {insight_short_id}; the "type" key is internal and dropped from reads.
        return {"type": "insight", "insight_short_id": value["insight_short_id"]}

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # goal is required and non-clearable at the field level, so this only bites a legacy row
        # (blank goal predating enforcement) that a PATCH tries to attach a metric to. Explicit-key
        # fallbacks so a PATCH sending only one of the pair validates the resulting row.
        goal = attrs.get("goal", self.instance.goal if self.instance else "")
        goal_metric = attrs.get("goal_metric", self.instance.goal_metric if self.instance else None)
        if goal_metric and not goal.strip():
            # Without a goal the metric is never read — reject instead of silently no-oping.
            raise serializers.ValidationError({"goal_metric": ["A goal metric requires a goal."]})
        return attrs


class BriefGoalStatusSerializer(serializers.Serializer):
    """Frozen goal-metric snapshot from generation: where the goal metric stood when the brief ran.
    Read-only projection of the stored GoalStatus (generation/goal.py)."""

    # ChoiceField (not CharField) so the fixed MetricState set flows downstream as a string enum,
    # letting the frontend gate (metric_state === 'ok') be compiler-checked.
    metric_state = serializers.ChoiceField(
        # Derived from the MetricState Literal (generation/goal.py) so the two can't drift.
        choices=list(get_args(MetricState)),
        help_text="'none' (qualitative goal, no metric), 'ok' (rates below are populated), or 'unavailable' (a metric is configured but could not be read this period).",
    )
    metric_label = serializers.CharField(
        allow_null=True, required=False, help_text="Name of the insight tracking the goal, when one is configured."
    )
    insight_short_id = serializers.CharField(
        allow_null=True, required=False, help_text="Short ID of the goal-metric insight, for linking through to it."
    )
    current_rate = serializers.CharField(
        allow_null=True, required=False, help_text="Per-day rate over the brief's period, e.g. '4.2/day avg'."
    )
    previous_rate = serializers.CharField(
        allow_null=True, required=False, help_text="Per-day rate over the preceding period, for comparison."
    )
    delta_pct = serializers.FloatField(
        allow_null=True,
        required=False,
        help_text="Percentage change of current vs previous rate; null off a zero baseline.",
    )


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


class BriefSectionCitationSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Cited resource type, e.g. insight or dashboard.")
    ref = serializers.CharField(help_text="Stable id of the cited resource within its type.")
    label = serializers.CharField(help_text="Human-readable name of the cited resource, for display.")
    url = serializers.CharField(
        allow_blank=True, help_text="Deep link into the app, or empty when the resource has no navigable target."
    )


class BriefSectionSerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="Section kind, e.g. what_happened or what_to_build_next.")
    title = serializers.CharField(help_text="Short section heading.")
    markdown = serializers.CharField(help_text="Section body rendered as markdown.")
    citations = BriefSectionCitationSerializer(many=True, help_text="PostHog resources this section cites as evidence.")
    confidence = serializers.FloatField(help_text="Model confidence in this section, 0.0-1.0.")


class AccountabilityStatusLineSerializer(serializers.Serializer):
    # A then-vs-now re-score of a past opportunity, computed deterministically in code (see
    # generation/accountability.OpportunityStatusLine) and persisted on the brief.
    opportunity_id = serializers.CharField(help_text="ID of the opportunity this status line re-scores.")
    kind = serializers.CharField(help_text="Opportunity kind at the time the brief was generated.")
    status = serializers.CharField(help_text="Opportunity lifecycle status at the time the brief was generated.")
    title = serializers.CharField(help_text="Opportunity title.")
    age_days = serializers.IntegerField(help_text="How many days ago the opportunity was first suggested.")
    baseline_summary = serializers.CharField(help_text="Human-readable metric rate at suggestion time.")
    current_summary = serializers.CharField(
        help_text='Human-readable metric rate now, or "metric no longer available" when it can\'t be re-read.'
    )
    delta_pct = serializers.FloatField(
        allow_null=True,
        help_text="Percentage change from the baseline rate to the current rate; null when it can't be computed.",
    )


class ProductBriefSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who requested the brief.")
    goal_status = BriefGoalStatusSerializer(
        read_only=True,
        allow_null=True,
        help_text="Frozen goal-metric progress snapshot from when the brief was generated. Null for config-less briefs and briefs generated from an empty gather.",
    )
    period = PeriodSerializer(read_only=True, help_text="The resolved-at-gather period spec the brief covers.")
    sections = BriefSectionSerializer(
        many=True,
        read_only=True,
        help_text="Generated brief sections, most important first.",
    )
    accountability = AccountabilityStatusLineSerializer(
        many=True,
        read_only=True,
        help_text="Then-vs-now re-scores of past opportunities surfaced with this brief.",
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
            "accountability",
            "sources_used",
            "goal_status",
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
    # The list view stays light: full section markdown and accountability re-scores are only
    # shipped on retrieve. Omitting them from fields is sufficient — DRF drops declared fields
    # not listed there.
    class Meta(ProductBriefSerializer.Meta):
        fields = [f for f in ProductBriefSerializer.Meta.fields if f not in {"sections", "accountability"}]
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
            # `code` is a cross-boundary contract with pulseLogic's AI_CONSENT_ERROR_CODE.
            raise ValidationError(
                "AI data processing must be approved for this organization to generate briefs.",
                code="ai_consent_required",
            )

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
