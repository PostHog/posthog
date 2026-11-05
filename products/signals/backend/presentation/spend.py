from dataclasses import asdict
from datetime import UTC, date
from typing import TYPE_CHECKING, cast

from django.utils import timezone

from dateutil.relativedelta import relativedelta
from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import CachedInboxUsageQueryResponse, DateRange, InboxUsageQuery

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.clickhouse.workload import Workload
from posthog.permissions import APIScopePermission

from products.signals.backend.facade.constants import SIGNAL_USAGE_START
from products.signals.backend.facade.spend import InboxUsageQueryRunner, scout_spend_overview, source_spend_overview
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission

if TYPE_CHECKING:
    from posthog.models import User


class SpendAmountSerializer(serializers.Serializer):
    total_spend = serializers.FloatField(
        allow_null=True,
        help_text="Recorded usage in USD cents, before billing exemptions; null when untracked.",
    )
    incomplete = serializers.BooleanField(help_text="Whether usage is still settling or accounting is incomplete.")


class ScoutSpendSerializer(serializers.Serializer):
    skill_name = serializers.CharField(help_text="Name of the scout skill.")
    spend = SpendAmountSerializer(help_text="Accumulated usage for this scout's runs in the period.")
    average_spend = serializers.FloatField(
        allow_null=True,
        help_text="Average recorded usage per tracked scout run in USD cents; null when no runs were tracked.",
    )


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
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "signal_usage"
    pagination_class = None

    @extend_schema(responses=SpendOverviewSerializer, operation_id="signals_spend_overview")
    def list(self, request: Request, **kwargs: object) -> Response:
        return Response(SpendOverviewSerializer(asdict(scout_spend_overview(team=self.team))).data)


class SignalSourceSpendViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = SourceSpendSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "signal_usage"
    pagination_class = None

    @extend_schema(responses=SourceSpendSerializer(many=True), operation_id="signals_source_spend")
    def list(self, request: Request, **kwargs: object) -> Response:
        return Response(SourceSpendSerializer(source_spend_overview(team=self.team), many=True).data)


class MonthlyUsageQuerySerializer(serializers.Serializer):
    month = serializers.RegexField(
        r"^[0-9]{4}-(0[1-9]|1[0-2])$",
        required=False,
        help_text="UTC calendar month in YYYY-MM format, from 2026-10 onward. Defaults to the current month. Usage is grouped by finalization time.",
    )

    def validate_month(self, value: str) -> date:
        try:
            month = date.fromisoformat(f"{value}-01")
        except ValueError:
            raise serializers.ValidationError("Enter a valid month in YYYY-MM format.") from None
        if month.year == 9999:
            raise serializers.ValidationError("The year must be earlier than 9999.")
        if month < SIGNAL_USAGE_START.date():
            raise serializers.ValidationError("Usage is available from October 2026. Choose that month or a later one.")
        return month


class UsageCreditsSerializer(serializers.Serializer):
    total_credits = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Recorded finalized usage in credits, including exempt usage. Decimal string preserving fractional credits.",
    )
    exempt_credits = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Subset of total_credits marked billing-exempt; not an invoice adjustment or grant balance.",
    )
    incomplete = serializers.BooleanField(help_text="Whether accounting is missing, failed, or still settling.")


class MonthlySourceUsageSerializer(UsageCreditsSerializer):
    source_product = serializers.CharField(
        allow_null=True,
        help_text="Product that emitted the signal. Null means attribution is unavailable; usage is retained.",
    )
    source_type = serializers.CharField(allow_null=True, help_text="Signal type within the source product.")
    processing_credits = serializers.DecimalField(
        max_digits=24, decimal_places=4, help_text="Credits for processing this source's signals."
    )
    research_credits = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Research and repository-selection credits attributed to their triggering signals.",
    )
    implementation_credits = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Implementation credits attributed to each report's current triggering signal.",
    )


class MonthlyScoutUsageSerializer(UsageCreditsSerializer):
    scout_config_id = serializers.UUIDField(allow_null=True, help_text="Scout configuration UUID, if it still exists.")
    skill_name = serializers.CharField(help_text="Scout skill name.")
    display_name = serializers.CharField(help_text="Scout display name, falling back to its skill name.")
    run_count = serializers.IntegerField(
        help_text="Number of tracked scout runs whose spend finalized in this month, including runs with no reports."
    )
    reports_produced = serializers.IntegerField(
        help_text="Distinct report IDs emitted by these runs. Reports can be shared across scouts; do not sum this as a project report count."
    )


class UsagePricingSerializer(serializers.Serializer):
    currency = serializers.CharField(help_text="Currency of the recorded usage value: USD.")
    usd_per_credit = serializers.DecimalField(
        max_digits=12,
        decimal_places=8,
        help_text="Multiply credits by this value to get recorded usage in USD, before billing exemptions, grants, discounts, or invoice rounding.",
    )


@extend_schema_serializer(many=False)
class MonthlyUsageSerializer(UsageCreditsSerializer):
    project_id = serializers.IntegerField(
        help_text="Canonical project that owns these spend records. A child environment resolves to its parent, which the caller must also be allowed to read."
    )
    period_start = serializers.DateTimeField(help_text="Inclusive start of the UTC calendar month.")
    period_end = serializers.DateTimeField(help_text="Exclusive end of the UTC calendar month.")
    as_of = serializers.DateTimeField(help_text="Time this summary was computed. The current month is partial.")
    unsettled_credits = serializers.DecimalField(
        max_digits=24,
        decimal_places=4,
        help_text="Recorded credits for unfinalized work created in this month, excluded from total_credits. This is not the full outstanding balance from earlier months.",
    )
    untracked_scout_run_count = serializers.IntegerField(
        help_text="Public scout runs created in this month with no spend record. Their unknown costs are not counted as zero."
    )
    attribution_incomplete = serializers.BooleanField(
        help_text="Whether any source attribution is missing. Unattributed credits remain in sources and total_credits."
    )
    sources = MonthlySourceUsageSerializer(
        many=True,
        help_text="Signal processing, research, and implementation grouped by source. Excludes scout execution costs.",
    )
    scouts = MonthlyScoutUsageSerializer(
        many=True,
        help_text="Scout execution costs, excluding downstream report work, which appears in sources. The sources and scouts totals sum to total_credits.",
    )
    pricing = UsagePricingSerializer(
        help_text="Server-provided denomination for converting recorded credits to USD. This summary is not an invoice."
    )


class SignalMonthlyUsageViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MonthlyUsageSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "signal_usage"
    pagination_class = None

    @validated_request(
        query_serializer=MonthlyUsageQuerySerializer,
        responses={200: MonthlyUsageSerializer},
        operation_id="signals_monthly_usage",
    )
    def list(self, request: ValidatedRequest, **kwargs: object) -> Response:
        month = request.validated_query_data.get("month") or timezone.now().astimezone(UTC).date().replace(day=1)
        user = cast("User", request.user)
        usage = InboxUsageQueryRunner(
            query=InboxUsageQuery(
                dateRange=DateRange(
                    date_from=month.isoformat(),
                    date_to=(month + relativedelta(months=1)).isoformat(),
                    explicitDate=True,
                )
            ),
            team=self.team.parent_team or self.team,
            user=user,
            workload=Workload.ONLINE,
        ).run(user=user)
        assert isinstance(usage, CachedInboxUsageQueryResponse)
        return Response(MonthlyUsageSerializer(usage.results).data)
