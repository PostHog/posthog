from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import report_user_action
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.quota import (
    SelfServeRaiseUnavailable,
    compute_quota_snapshot,
    raise_self_serve_credit_limit,
)


# `many=False` stops drf-spectacular wrapping the response as `VisionQuotaApi[]` for the `list` action.
@extend_schema_serializer(many=False)
class VisionQuotaSerializer(serializers.Serializer):
    credit_limit = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Credits the org may spend per billing period (1 credit = $0.01). Null when billing has synced the product with no spend limit: uncapped.",
    )
    credits_used = serializers.IntegerField(
        read_only=True,
        help_text="Credits spent this period: succeeded observations from the receipt ledger plus reserved in-flight observations.",
    )
    remaining = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="`credit_limit - credits_used`, floored at 0. Null when uncapped.",
    )
    exhausted = serializers.BooleanField(
        read_only=True,
        help_text="True when `credits_used >= credit_limit`; further observations are skipped until next period. Always false when uncapped.",
    )
    period_start = serializers.DateTimeField(
        read_only=True,
        help_text="First moment of the current quota period (UTC).",
    )
    period_end = serializers.DateTimeField(
        read_only=True,
        help_text="First moment of the next quota period (UTC); the current period's exclusive upper bound.",
    )
    projected_monthly_credits = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Credit-weighted sum of enabled scanners' projected observations/month across the organization. "
            "Scanners without a computed estimate contribute 0."
        ),
    )
    billing_managed = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True when billing manages this organization's Replay vision spend limit. False means the limit is "
            "the fallback runaway-spend cap, which the organization is not billed against."
        ),
    )
    self_serve_credit_ceiling = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Highest credit limit an organization admin can set for themselves without staff help. "
            "Null when billing manages the limit."
        ),
    )
    can_raise_credit_limit = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True when `raise_limit` would lift this organization's cap — the limit is not billing-managed and "
            "is still below `self_serve_credit_ceiling`. Admin membership is checked separately, on the request."
        ),
    )


class VisionQuotaViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "replay_scanner"
    # Custom viewsets must declare scopes or personal-API-key callers 403 silently.
    scope_object_read_actions = ["list"]
    scope_object_write_actions = ["raise_limit"]
    permission_classes = [IsAuthenticated, ReplayVisionEnabledPermission]

    @extend_schema(operation_id="environment_vision_quota_retrieve", responses={200: VisionQuotaSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        snapshot = compute_quota_snapshot(organization_id=UUID(self.organization_id))
        return Response(VisionQuotaSerializer(instance=snapshot).data)

    @extend_schema(
        operation_id="environment_vision_quota_raise_limit",
        request=None,
        responses={200: VisionQuotaSerializer},
    )
    @action(detail=False, methods=["post"], url_path="raise_limit")
    def raise_limit(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Lift the organization's Replay vision credit limit by one step, up to the self-serve ceiling.

        Only for organizations whose limit is the fallback cap — those are not billed for the product, so
        the cap is a runaway-spend guard admins should be able to move without a staff-issued grant.
        """
        organization_id = UUID(self.organization_id)
        membership = OrganizationMembership.objects.filter(
            user=cast(User, request.user), organization_id=organization_id
        ).first()
        if membership is None or membership.level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("Only organization admins can raise the Replay vision credit limit.")

        before = compute_quota_snapshot(organization_id=organization_id)
        try:
            snapshot = raise_self_serve_credit_limit(organization_id, granted_by_id=request.user.pk)
        except SelfServeRaiseUnavailable as exc:
            raise ValidationError(str(exc))

        report_user_action(
            cast(User, request.user),
            "replay_vision_quota_limit_raised",
            {
                "previous_credit_limit": before.credit_limit,
                "credit_limit": snapshot.credit_limit,
                "credits_used": snapshot.credits_used,
                "was_exhausted": before.exhausted,
            },
            team=self.team,
            request=request,
        )
        return Response(VisionQuotaSerializer(instance=snapshot).data, status=status.HTTP_200_OK)
