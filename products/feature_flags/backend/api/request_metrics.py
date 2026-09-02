from django.db import models

from drf_spectacular.utils import OpenApiResponse
from rest_framework import request, response, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from posthog.api.app_metrics2 import fetch_app_metrics_trends
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.constants import FLAG_REQUEST_BILLING_WEIGHTS
from posthog.utils import relative_date_parse_with_delta_mapping

from products.feature_flags.backend.request_metrics import APP_SOURCE


class FlagRequestMetricsInterval(models.TextChoices):
    HOUR = "hour", "Hour"
    DAY = "day", "Day"
    WEEK = "week", "Week"


class FlagRequestMetricsBreakdown(models.TextChoices):
    REQUEST_TYPE = "request_type", "Request type"
    LIBRARY = "library", "Library"


class FlagRequestMetricsQuerySerializer(serializers.Serializer):
    after = serializers.CharField(
        required=False,
        default="-7d",
        help_text="Start of the time range. Accepts a relative value such as '-7d' or '-24h', or an ISO 8601 timestamp.",
    )
    before = serializers.CharField(
        required=False,
        default="-0d",
        help_text="End of the time range, in the same format as 'after'. Defaults to now.",
    )
    interval = serializers.ChoiceField(
        choices=FlagRequestMetricsInterval.choices,
        required=False,
        default=FlagRequestMetricsInterval.DAY,
        help_text="Size of each time bucket in the returned series.",
    )
    breakdown = serializers.ChoiceField(
        choices=FlagRequestMetricsBreakdown.choices,
        required=False,
        default=FlagRequestMetricsBreakdown.REQUEST_TYPE,
        help_text="Split the series by flag request type, or by the SDK that sent the requests.",
    )


class FlagRequestMetricsSeriesSerializer(serializers.Serializer):
    name = serializers.CharField(
        help_text=(
            "The request type or SDK this series counts, depending on 'breakdown'. Requests that the flags "
            "service could not attribute to an SDK are counted under 'unattributed'."
        )
    )
    values = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="Request count per bucket. One entry for each entry in 'labels'.",
    )


class FlagRequestMetricsResponseSerializer(serializers.Serializer):
    labels = serializers.ListField(
        child=serializers.CharField(),
        help_text="Start of each time bucket, formatted for the requested interval.",
    )
    series = FlagRequestMetricsSeriesSerializer(
        many=True,
        help_text="One series per request type or per SDK, depending on 'breakdown'.",
    )
    billing_weights = serializers.DictField(
        child=serializers.IntegerField(),
        help_text=(
            "How many billable requests one request of each type counts as. A local evaluation request is "
            "weighted because one poll returns the definitions of every flag in the project."
        ),
    )


class FlagRequestMetricsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    Counts of the flag requests this project's SDKs made, split by request type and by SDK.

    The counts come from the same per-team counters the billing pipeline reads, so the totals here
    reconcile with billed flag request volume once the billing weights are applied. Requests made
    before this project started recording the breakdown are not included, because the counters
    cannot be rebuilt after the fact.
    """

    permission_classes = [IsAuthenticated]
    scope_object = "feature_flag"

    @validated_request(
        query_serializer=FlagRequestMetricsQuerySerializer,
        responses={200: OpenApiResponse(response=FlagRequestMetricsResponseSerializer)},
        summary="Get flag request volume",
    )
    @action(methods=["GET"], detail=False)
    def volume(self, request: request.Request, **kwargs) -> response.Response:
        params = request.validated_query_data

        after, _, _ = relative_date_parse_with_delta_mapping(params["after"], self.team.timezone_info)
        before, _, _ = relative_date_parse_with_delta_mapping(params["before"], self.team.timezone_info)

        trends = fetch_app_metrics_trends(
            team_id=self.team_id,
            app_source=APP_SOURCE,
            # Flag requests are recorded against the whole project, so there is no sub-object to key
            # on. The recorded rows use the same empty id, and this filter matches exactly.
            app_source_id="",
            after=after,
            before=before,
            interval=params["interval"],
            breakdown_by="kind" if params["breakdown"] == FlagRequestMetricsBreakdown.REQUEST_TYPE else "name",
        )

        return response.Response(
            {
                "labels": trends.labels,
                "series": [{"name": series.name, "values": series.values} for series in trends.series],
                "billing_weights": {
                    str(request_type): weight for request_type, weight in FLAG_REQUEST_BILLING_WEIGHTS.items()
                },
            }
        )
