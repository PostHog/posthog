from dataclasses import asdict

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission

from products.signals.backend.spend_reporting import SpendReporting


class SpendAmountSerializer(serializers.Serializer):
    total_spend = serializers.FloatField(
        allow_null=True,
        help_text="Recorded usage in USD cents, before billing exemptions; null when untracked.",
    )
    incomplete = serializers.BooleanField(help_text="Whether usage is still settling or accounting is incomplete.")


class ScoutSpendSerializer(serializers.Serializer):
    skill_name = serializers.CharField(help_text="Name of the scout skill.")
    spend = SpendAmountSerializer(help_text="Accumulated usage for this scout's runs in the period.")


@extend_schema_serializer(many=False)
class SpendOverviewSerializer(serializers.Serializer):
    period_start = serializers.DateTimeField(help_text="Inclusive start of the rolling 30-day run window.")
    period_end = serializers.DateTimeField(help_text="Exclusive end of the rolling 30-day run window.")
    scouts = ScoutSpendSerializer(many=True, help_text="Usage for each scout with runs in the period.")
    scout_spend = SpendAmountSerializer(help_text="Total scout run usage in the period.")


class SourceSpendSerializer(serializers.Serializer):
    source_product = serializers.CharField(help_text="Product that emitted the signals.")
    source_type = serializers.CharField(help_text="Type of signals emitted by the source.")
    signal_count = serializers.IntegerField(help_text="Number of signals received in the last 30 days.")
    spend = SpendAmountSerializer(
        help_text="Accumulated processing usage on these signals, including later processing."
    )


class ReportSpendSerializer(serializers.Serializer):
    generation = SpendAmountSerializer(
        help_text="Usage for the report's backing signals, research and repository selection."
    )
    implementation = SpendAmountSerializer(help_text="Usage for implementation tasks owned by the report.")
    shared_scout_runs = SpendAmountSerializer(
        help_text="Full usage of scout runs that authored this report. Shared with all other output of those runs."
    )


class SignalSpendViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = SpendOverviewSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_scout"
    pagination_class = None

    @extend_schema(responses=SpendOverviewSerializer, operation_id="signals_spend_overview")
    def list(self, request: Request, **kwargs: object) -> Response:
        return Response(SpendOverviewSerializer(asdict(SpendReporting(self.team).scouts())).data)


class SignalSourceSpendViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = SourceSpendSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    pagination_class = None

    @extend_schema(responses=SourceSpendSerializer(many=True), operation_id="signals_source_spend")
    def list(self, request: Request, **kwargs: object) -> Response:
        return Response(SourceSpendSerializer(SpendReporting(self.team).sources(), many=True).data)
