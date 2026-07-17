from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.quota import compute_quota_snapshot


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


class VisionQuotaViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "replay_scanner"
    # Custom viewsets must declare scopes or personal-API-key callers 403 silently.
    scope_object_read_actions = ["list"]
    permission_classes = [IsAuthenticated, ReplayVisionEnabledPermission]

    @extend_schema(operation_id="environment_vision_quota_retrieve", responses={200: VisionQuotaSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        snapshot = compute_quota_snapshot(organization_id=UUID(self.organization_id))
        return Response(VisionQuotaSerializer(instance=snapshot).data)
