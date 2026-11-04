from django.db.models import QuerySet

from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.models.user import User
from posthog.oauth_provenance import get_oauth_access_token, is_sandbox_oauth_request
from posthog.ph_client import feature_enabled_or_false

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.feature_flags.backend.facade.api import user_can_edit_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.feature_flag_rollout_plan import FeatureFlagRolloutPlan
from products.feature_flags.backend.rollout_plans import advance_rollout_plan, start_rollout_plan, stop_rollout_plan

FEATURE_FLAG_ROLLOUT_AGENT_FLAG = "feature-flag-rollout-agent"
MAX_ROLLOUT_STEPS = 10
MAX_SOAK_HOURS = 24 * 14
MAX_TEXT_LENGTH = 4000
MAX_LISTED_PLANS = 20


class FeatureFlagRolloutPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeatureFlagRolloutPlan
        fields = [
            "id",
            "feature_flag",
            "condition_index",
            "percentages",
            "soak_hours",
            "health_checks",
            "status",
            "steps_applied",
            "next_check_at",
            "task_id",
            "last_summary",
            "stop_reason",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "The rollout plan ID."},
            "feature_flag": {"help_text": "The ID of the feature flag this plan rolls out."},
            "condition_index": {"help_text": "The index of the release condition this plan changes."},
            "percentages": {"help_text": "The approved rollout percentages, in the order they apply."},
            "soak_hours": {"help_text": "The minimum number of hours between two steps."},
            "health_checks": {"help_text": "What the agent checks before each step, as the person wrote it."},
            "status": {"help_text": "Whether the plan is active, completed, or stopped."},
            "steps_applied": {"help_text": "How many of the approved percentages are already applied."},
            "next_check_at": {"help_text": "The earliest time the next step can run. Null before the first step."},
            "task_id": {"help_text": "The ID of the task that runs the health checks."},
            "last_summary": {"help_text": "What the agent reported after its last passing check."},
            "stop_reason": {"help_text": "Why the plan stopped. Empty unless the status is stopped."},
            "created_at": {"help_text": "When the person approved the plan."},
        }


class FeatureFlagRolloutPlanCreateSerializer(serializers.Serializer):
    feature_flag = serializers.IntegerField(help_text="The ID of the feature flag to roll out.")
    condition_index = serializers.IntegerField(
        min_value=0, default=0, help_text="The index of the release condition to change."
    )
    percentages = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=100),
        min_length=1,
        max_length=MAX_ROLLOUT_STEPS,
        help_text="The approved rollout percentages in increasing order, such as [5, 25, 50, 100].",
    )
    soak_hours = serializers.IntegerField(
        min_value=1, max_value=MAX_SOAK_HOURS, help_text="The minimum number of hours between two steps."
    )
    health_checks = serializers.CharField(
        max_length=MAX_TEXT_LENGTH,
        help_text="Which insights or dashboards show that the feature is healthy, and what result stops the rollout.",
    )

    def validate_percentages(self, value: list[int]) -> list[int]:
        if any(later <= earlier for earlier, later in zip(value, value[1:])):
            raise serializers.ValidationError("Each percentage must be higher than the one before it.")
        return value


class FeatureFlagRolloutPlanListQuerySerializer(serializers.Serializer):
    feature_flag = serializers.IntegerField(help_text="The ID of the feature flag to list rollout plans for.")


class FeatureFlagRolloutPlanAdvanceSerializer(serializers.Serializer):
    summary = serializers.CharField(
        max_length=MAX_TEXT_LENGTH, help_text="A short summary of the health check results, with the numbers you read."
    )


class FeatureFlagRolloutPlanStopSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=MAX_TEXT_LENGTH, help_text="Why the rollout stops. The person who approved it reads this."
    )


class FeatureFlagRolloutPlanViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "feature_flag"
    serializer_class = FeatureFlagRolloutPlanSerializer
    pagination_class = None
    queryset = FeatureFlagRolloutPlan.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.select_related("feature_flag", "created_by").order_by("-created_at")

    @validated_request(
        query_serializer=FeatureFlagRolloutPlanListQuerySerializer,
        responses={200: FeatureFlagRolloutPlanSerializer(many=True)},
    )
    def list(self, request: ValidatedRequest, **kwargs: object) -> Response:
        """List the rollout plans of one feature flag, newest first."""
        flag_id = request.validated_query_data["feature_flag"]
        flag = FeatureFlag.objects.filter(team__project_id=self.team.project_id, pk=flag_id).first()
        if flag is None:
            raise exceptions.NotFound("This feature flag does not exist in this project.")
        access_control = UserAccessControl(user=request.user, team=self.team)
        if not access_control.check_access_level_for_object(flag, "viewer"):
            raise exceptions.PermissionDenied("You do not have access to this feature flag.")
        plans = self.safely_get_queryset(self.queryset).filter(feature_flag_id=flag_id)[:MAX_LISTED_PLANS]
        return Response(FeatureFlagRolloutPlanSerializer(plans, many=True).data)

    @validated_request(
        FeatureFlagRolloutPlanCreateSerializer,
        responses={201: FeatureFlagRolloutPlanSerializer},
    )
    def create(self, request: ValidatedRequest, **kwargs: object) -> Response:
        """Approve a rollout plan and start the agent that runs it.

        Only a person signed in to the app can do this, so an agent cannot approve its own plan.
        """
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            raise exceptions.PermissionDenied("Only a person signed in to PostHog can approve a rollout plan.")
        user = request.user
        assert isinstance(user, User)
        if not feature_enabled_or_false(
            FEATURE_FLAG_ROLLOUT_AGENT_FLAG,
            str(user.distinct_id),
            groups={"organization": str(self.team.organization_id), "project": str(self.team.uuid)},
            send_feature_flag_events=False,
        ):
            raise exceptions.PermissionDenied("Agent rollouts are not available for this project.")
        data = request.validated_data
        plan = start_rollout_plan(
            team=self.team,
            user=user,
            feature_flag_id=data["feature_flag"],
            condition_index=data["condition_index"],
            percentages=data["percentages"],
            soak_hours=data["soak_hours"],
            health_checks=data["health_checks"],
        )
        return Response(FeatureFlagRolloutPlanSerializer(plan).data, status=status.HTTP_201_CREATED)

    @validated_request(
        FeatureFlagRolloutPlanAdvanceSerializer,
        responses={200: FeatureFlagRolloutPlanSerializer},
    )
    @action(methods=["POST"], detail=True, required_scopes=["feature_flag_rollout_plan:write"])
    def advance(self, request: ValidatedRequest, **kwargs: object) -> Response:
        """Report that the health checks passed, so PostHog applies the next approved percentage.

        Only the run of this plan can call this. The caller sends no percentage and no flag, because the plan holds
        both. PostHog refuses a call before the time between steps has passed, and it schedules the next check.
        """
        plan = self.get_object()
        _require_plan_run(request, plan)
        plan = advance_rollout_plan(plan.pk, team=self.team, request=request, summary=request.validated_data["summary"])
        return Response(FeatureFlagRolloutPlanSerializer(plan).data)

    @validated_request(
        FeatureFlagRolloutPlanStopSerializer,
        responses={200: FeatureFlagRolloutPlanSerializer},
    )
    @action(methods=["POST"], detail=True, required_scopes=["feature_flag_rollout_plan:write"])
    def fail(self, request: ValidatedRequest, **kwargs: object) -> Response:
        """Report that a health check failed, so PostHog stops the rollout and notifies the person who approved it.

        Only the run of this plan can call this. The flag stays at its current percentage.
        """
        plan = self.get_object()
        _require_plan_run(request, plan)
        plan = stop_rollout_plan(
            plan, reason=request.validated_data["reason"], stopped_by=None, acting_user=request.user
        )
        return Response(FeatureFlagRolloutPlanSerializer(plan).data)

    @validated_request(
        FeatureFlagRolloutPlanStopSerializer,
        responses={200: FeatureFlagRolloutPlanSerializer},
    )
    @action(methods=["POST"], detail=True, required_scopes=["feature_flag:write"])
    def stop(self, request: ValidatedRequest, **kwargs: object) -> Response:
        """Stop the rollout, cancel the next health check, and leave the flag at its current percentage."""
        plan = self.get_object()
        if not user_can_edit_flag(plan.feature_flag, team=self.team, user=request.user):
            raise exceptions.PermissionDenied("You need editor access to this feature flag to stop its rollout.")
        plan = stop_rollout_plan(
            plan, reason=request.validated_data["reason"], stopped_by=request.user, acting_user=request.user
        )
        return Response(FeatureFlagRolloutPlanSerializer(plan).data)


def _require_plan_run(request: Request, plan: FeatureFlagRolloutPlan) -> None:
    task_id = getattr(get_oauth_access_token(request), "sandbox_task_id", None)
    if not is_sandbox_oauth_request(request) or task_id is None or task_id != plan.task_id:
        raise exceptions.PermissionDenied("Only the run of this rollout plan can do this.")
