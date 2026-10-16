from typing import cast

from django.db import models

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import OrganizationMembership, User
from posthog.permissions import APIScopePermission, TeamMemberLightManagementPermission

from products.signals.backend.trial_billing import TrialContinuation
from products.signals.backend.trial_policy import TrialRefused
from products.signals.backend.trial_service import TrialService


class TrialGrantStatus(models.TextChoices):
    NOT_CLAIMED = "not_claimed", "Not claimed"
    PENDING = "pending", "Billing activation pending"
    ACTIVE = "active", "Active"
    EXHAUSTED = "exhausted", "Exhausted"


@extend_schema_serializer(many=False)
class SelfDrivingTrialStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(help_text="The organization's last confirmed trial rollout decision.")
    flag_confirmed = serializers.BooleanField(help_text="Whether the current rollout check succeeded.")
    policy_version = serializers.IntegerField(help_text="Effective trial policy version.")
    legacy_pr_restricted = serializers.BooleanField(
        help_text="Whether the legacy reports-only trial still prevents implementation for this project."
    )
    billing_ready = serializers.BooleanField(
        help_text="Whether billing supports immutable trial funding and the one-time allocation."
    )
    eligible = serializers.BooleanField(help_text="Whether this project can explicitly claim its lifetime grant.")
    can_activate = serializers.BooleanField(
        help_text="Whether the current user has project-management permission to activate."
    )
    organization_grants_remaining = serializers.IntegerField(
        help_text="Unclaimed lifetime project grants in the organization."
    )
    grant_id = serializers.UUIDField(allow_null=True, help_text="Lifetime project grant, shared with its environments.")
    grant_status = serializers.ChoiceField(
        choices=TrialGrantStatus.choices, help_text="The project's lifetime trial state."
    )
    exhaustion_reason = serializers.CharField(
        allow_blank=True, help_text="Why the trial completed: cost_limit or report_limit."
    )
    reports_delivered = serializers.IntegerField(
        help_text="Consumed report slots, including dismissed or deleted reports."
    )
    reports_reserved = serializers.IntegerField(help_text="Report slots held by admitted work.")
    report_limit = serializers.IntegerField(help_text="Maximum reports delivered by this trial.")
    allowance_microusd = serializers.IntegerField(help_text="One-time allowance in millionths of a US dollar.")
    used_microusd = serializers.IntegerField(help_text="Allowance used, capped at the trial allowance.")
    reserved_microusd = serializers.IntegerField(help_text="Allowance reserved for work with incomplete accounting.")
    enabled_scouts = serializers.IntegerField(help_text="Enabled scouts across this project's environments.")
    scout_limit = serializers.IntegerField(help_text="Maximum enabled scouts during the trial.")
    scouts_to_pause = serializers.IntegerField(
        help_text="On activation, all but the three oldest enabled scouts pause."
    )
    paid_continuation = serializers.ChoiceField(
        choices=TrialContinuation.choices, help_text="What happens to new work after the trial."
    )


class SelfDrivingTrialActivationSerializer(serializers.Serializer):
    pass


class SelfDrivingTrialViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, TeamMemberLightManagementPermission]
    scope_object = "project"
    pagination_class = None
    serializer_class = SelfDrivingTrialStatusSerializer
    http_method_names = ["get", "post", "head", "options"]

    def _status(self, service: TrialService) -> dict[str, object]:
        data = service.status()
        level = self.user_permissions.team(self.team.parent_team or self.team).effective_membership_level
        data["can_activate"] = level is not None and level >= OrganizationMembership.Level.ADMIN
        return data

    @extend_schema(responses=SelfDrivingTrialStatusSerializer)
    def list(self, request: Request, **kwargs: object) -> Response:
        return Response(SelfDrivingTrialStatusSerializer(self._status(TrialService(self.team))).data)

    @extend_schema(request=SelfDrivingTrialActivationSerializer, responses=SelfDrivingTrialStatusSerializer)
    def create(self, request: Request, **kwargs: object) -> Response:
        level = self.user_permissions.team(self.team.parent_team or self.team).effective_membership_level
        if level is None or level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("Project management permission is required to start a trial.")
        serializer = SelfDrivingTrialActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = TrialService(self.team)
        try:
            service.activate(user_id=cast(User, request.user).pk)
        except TrialRefused as error:
            raise ValidationError({"reason": error.reason}) from error
        return Response(SelfDrivingTrialStatusSerializer(self._status(service)).data)
