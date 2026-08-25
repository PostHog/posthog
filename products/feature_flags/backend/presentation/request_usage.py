from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.documentation import extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.rate_limit import FeatureFlagRequestUsageBurstRateThrottle, FeatureFlagRequestUsageSustainedRateThrottle

from products.feature_flags.backend.facade.api import FeatureFlagRequestType, get_feature_flag_request_usage

FEATURE_FLAG_REQUEST_USAGE_FLAG = "feature-flag-request-usage"
# The shared "Last 7 days" preset starts at midnight seven days ago and ends now,
# so it can span almost eight elapsed days. Keep this aligned with the frontend limit.
MAX_HOURLY_RANGE_DAYS = 8
MAX_DAILY_RANGE_DAYS = 31


class FeatureFlagRequestUsageQuerySerializer(serializers.Serializer):
    date_from = serializers.DateTimeField(help_text="Inclusive start of the usage period.")
    date_to = serializers.DateTimeField(help_text="Exclusive end of the usage period.")
    time_interval = serializers.ChoiceField(
        choices=["hour", "day"],
        default="day",
        help_text=f"Time bucket used to group request usage. Hourly queries are limited to {MAX_HOURLY_RANGE_DAYS} days.",
    )

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        date_from = cast(datetime, attrs["date_from"])
        date_to = cast(datetime, attrs["date_to"])
        time_interval = cast(str, attrs["time_interval"])
        if date_from >= date_to:
            raise serializers.ValidationError("date_from must be earlier than date_to.")

        # The shared "Last 7 days" preset starts at midnight seven days ago, so it can span almost 8 full days.
        maximum_range = timedelta(days=MAX_HOURLY_RANGE_DAYS if time_interval == "hour" else MAX_DAILY_RANGE_DAYS)
        if date_to - date_from > maximum_range:
            raise serializers.ValidationError(
                f"{time_interval.capitalize()} queries are limited to {maximum_range.days} days."
            )
        return attrs


class FeatureFlagRequestUsageItemSerializer(serializers.Serializer):
    bucket = serializers.DateTimeField(
        help_text="Start of the UTC billing-aggregation bucket. Hourly buckets approximate request time."
    )
    request_type = serializers.ChoiceField(
        choices=list(FeatureFlagRequestType),
        help_text="Remote flag evaluation or local flag-definition request.",
    )
    sdk = serializers.CharField(help_text="SDK family parsed from the request user agent.")
    request_count = serializers.IntegerField(help_text="Number of billable requests in this bucket.")
    billing_units = serializers.IntegerField(
        help_text="Estimated billing units. Local evaluation requests count as 10 units each."
    )


@extend_schema_serializer(many=False)
class FeatureFlagRequestUsageResponseSerializer(serializers.Serializer):
    results = FeatureFlagRequestUsageItemSerializer(many=True, help_text="Feature flag request usage by SDK.")
    generated_at = serializers.DateTimeField(help_text="Time when this response was generated.")


@extend_schema(extensions={"x-product": ProductKey.FEATURE_FLAGS})
class FeatureFlagRequestUsageViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "feature_flag"
    requires_resource_level_access = True
    throttle_classes = [FeatureFlagRequestUsageBurstRateThrottle, FeatureFlagRequestUsageSustainedRateThrottle]

    @validated_request(
        query_serializer=FeatureFlagRequestUsageQuerySerializer,
        responses={200: OpenApiResponse(response=FeatureFlagRequestUsageResponseSerializer)},
    )
    def list(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        user = cast(User, request.user)
        if not feature_enabled_or_false(
            FEATURE_FLAG_REQUEST_USAGE_FLAG,
            user.distinct_id or str(self.team.uuid),
            groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            send_feature_flag_events=False,
        ):
            raise NotFound("Feature flag request usage is not enabled for this project.")

        query = request.validated_query_data
        results = get_feature_flag_request_usage(
            team_id=self.team_id,
            date_from=cast(datetime, query["date_from"]),
            date_to=cast(datetime, query["date_to"]),
            time_interval=cast(Literal["hour", "day"], query["time_interval"]),
        )
        return Response(
            {
                "results": [
                    {
                        "bucket": item.bucket,
                        "request_type": item.request_type.value,
                        "sdk": item.sdk,
                        "request_count": item.request_count,
                        "billing_units": item.billing_units,
                    }
                    for item in results
                ],
                "generated_at": datetime.now(UTC),
            }
        )
