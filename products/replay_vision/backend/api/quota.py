from uuid import UUID

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.replay_vision.backend.quota import compute_quota_snapshot, daily_spend_series


# `many=False` stops drf-spectacular wrapping the response as `VisionQuotaApi[]` for the `list` action.
@extend_schema_serializer(many=False)
class VisionQuotaSerializer(serializers.Serializer):
    credit_limit = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Credits the organization may spend per billing period (1 credit = $0.01). "
            "0 is a hard block: no observation can start. Null when billing has synced the product with no spend limit: uncapped."
        ),
    )
    credits_used = serializers.IntegerField(
        read_only=True,
        help_text=(
            "`credits_settled` plus `credits_reserved`: the organization's total draw on `credit_limit` this period, "
            "across every project."
        ),
    )
    credits_settled = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Credits posted to the receipt ledger by succeeded observations and finished prompt-test sessions this period, "
            "across every project in the organization. Deleting an observation never refunds these."
        ),
    )
    credits_reserved = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Credits held by in-flight observations and running prompt tests across every project in the organization. "
            "Released without charge when the work fails, settled into `credits_settled` when it succeeds."
        ),
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
            "`scanners_monthly_credits` plus `backfills_committed_credits`. Kept as the single headline number; "
            "prefer the two components when pro-rating, since only the scanner half is a monthly rate."
        ),
    )
    scanners_monthly_credits = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Credit-weighted sum of enabled scanners' projected observations/month across the organization. "
            "A capped scanner contributes at most what its own credit limit has left this period, folded back into a 30-day rate. "
            "A monthly rate: only the part falling in the days left of the period lands this period. "
            "Scanners without a computed estimate contribute 0."
        ),
    )
    backfills_committed_credits = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Committed-but-unspent credits of the organization's active backfills. A one-off charge rather than "
            "a rate, so it lands in full regardless of how much of the period is left."
        ),
    )
    free_monthly_credits = serializers.IntegerField(
        read_only=True,
        help_text=(
            "Credits per period included for free. Already counted inside `credit_limit`; "
            "only credits beyond this number are billed."
        ),
    )


class VisionSpendDaySerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True, help_text="UTC calendar day.")
    credits = serializers.IntegerField(
        read_only=True,
        help_text="Credits settled by observations created on this day across every project in the organization; 0 when none.",
    )


@extend_schema_serializer(many=False)
class VisionSpendSeriesSerializer(serializers.Serializer):
    period_start = serializers.DateTimeField(
        read_only=True,
        help_text="First moment of the current quota period (UTC).",
    )
    period_end = serializers.DateTimeField(
        read_only=True,
        help_text="First moment of the next quota period (UTC); the current period's exclusive upper bound.",
    )
    days = VisionSpendDaySerializer(
        many=True,
        read_only=True,
        help_text="One entry per UTC day from `period_start` through today, in order, zero-filled for days without spend.",
    )


class VisionQuotaViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "replay_scanner"
    # Custom viewsets must declare scopes or personal-API-key callers 403 silently.
    scope_object_read_actions = ["list", "spend_series"]
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="environment_vision_quota_retrieve", responses={200: VisionQuotaSerializer})
    def list(self, request: Request, *args, **kwargs) -> Response:
        snapshot = compute_quota_snapshot(organization_id=UUID(self.organization_id))
        return Response(VisionQuotaSerializer(instance=snapshot).data)

    @extend_schema(
        operation_id="environment_vision_quota_spend_series_retrieve", responses={200: VisionSpendSeriesSerializer}
    )
    @action(detail=False, methods=["get"])
    def spend_series(self, request: Request, *args, **kwargs) -> Response:
        series = daily_spend_series(organization_id=UUID(self.organization_id))
        return Response(VisionSpendSeriesSerializer(instance=series).data)
