import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal, TypedDict, cast

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.documentation import extend_schema
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.property.util import get_property_string_expr
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false
from posthog.rate_limit import FeatureFlagRequestUsageBurstRateThrottle, FeatureFlagRequestUsageSustainedRateThrottle
from posthog.utils import get_instance_region

LOCAL_BILLING_ANALYTICS_TOKEN = "local-development"
FEATURE_FLAG_REQUEST_USAGE_FLAG = "feature-flag-request-usage"
MAX_HOURLY_RANGE_DAYS = 8
MAX_DAILY_RANGE_DAYS = 31
REQUEST_USAGE_QUERY_SETTINGS = {
    "max_execution_time": 30,
    "max_bytes_to_read": 100 * 1024 * 1024 * 1024,
    "max_memory_usage": 2 * 1024 * 1024 * 1024,
    "max_threads": 4,
}


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
        choices=["remote_evaluation", "local_evaluation"],
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


class FeatureFlagRequestUsageItem(TypedDict):
    bucket: datetime
    request_type: Literal["remote_evaluation", "local_evaluation"]
    sdk: str
    request_count: int
    billing_units: int


FeatureFlagRequestUsageRow = tuple[datetime, Literal["remote_evaluation", "local_evaluation"], int, str]


def aggregate_feature_flag_request_usage(
    rows: Iterable[FeatureFlagRequestUsageRow],
) -> list[FeatureFlagRequestUsageItem]:
    counts: defaultdict[tuple[datetime, str, str], int] = defaultdict(int)
    for bucket, request_type, total_count, raw_sdk_breakdown in rows:
        try:
            parsed_breakdown = json.loads(raw_sdk_breakdown) if raw_sdk_breakdown else {}
        except json.JSONDecodeError:
            parsed_breakdown = {}
        sdk_breakdown = (
            {sdk: count for sdk, count in parsed_breakdown.items() if isinstance(sdk, str) and isinstance(count, int)}
            if isinstance(parsed_breakdown, dict)
            else {}
        )
        for sdk, count in sdk_breakdown.items():
            counts[(bucket, request_type, sdk)] += count
        counts[(bucket, request_type, "other")] += max(total_count - sum(sdk_breakdown.values()), 0)

    return [
        {
            "bucket": bucket,
            "request_type": cast(Literal["remote_evaluation", "local_evaluation"], request_type),
            "sdk": sdk,
            "request_count": request_count,
            "billing_units": request_count * (10 if request_type == "local_evaluation" else 1),
        }
        for (bucket, request_type, sdk), request_count in sorted(counts.items())
        if request_count > 0
    ]


def get_feature_flag_request_usage(
    *, team_id: int, date_from: datetime, date_to: datetime, time_interval: Literal["hour", "day"]
) -> list[FeatureFlagRequestUsageItem]:
    internal_team_id = 1 if get_instance_region() == "EU" else 2
    validity_token = settings.DECIDE_BILLING_ANALYTICS_TOKEN
    if settings.DEBUG and not validity_token:
        validity_token = LOCAL_BILLING_ANALYTICS_TOKEN
    use_new = use_new_events_schema(None)
    sdk_breakdown_expr, _ = get_property_string_expr(
        "events", "sdk_breakdown", "'sdk_breakdown'", "properties", use_new_events_schema=use_new
    )
    count_expr, _ = get_property_string_expr("events", "count", "'count'", "properties", use_new_events_schema=use_new)
    token_expr, _ = get_property_string_expr("events", "token", "'token'", "properties", use_new_events_schema=use_new)
    bucket_function = "toStartOfHour" if time_interval == "hour" else "toStartOfDay"

    with tags_context(product=Product.FEATURE_FLAGS, feature=Feature.QUERY, team_id=team_id):
        # nosemgrep: clickhouse-fstring-param-audit - bucket function and table expressions are internal allowlisted fragments
        rows = sync_execute(
            f"""
            SELECT
                {bucket_function}(timestamp) AS bucket,
                if(event = 'decide usage', 'remote_evaluation', 'local_evaluation') AS request_type,
                toInt64OrZero({count_expr}) AS total_count,
                {sdk_breakdown_expr} AS sdk_breakdown
            FROM {events_read_table(use_new)}
            WHERE team_id = %(internal_team_id)s
              AND distinct_id = toString(%(team_id)s)
              AND event IN ('decide usage', 'local evaluation usage')
              AND timestamp >= %(date_from)s AND timestamp < %(date_to)s
              AND has([%(validity_token)s], {token_expr})
            ORDER BY bucket, request_type
            """,
            {
                "internal_team_id": internal_team_id,
                "team_id": team_id,
                "date_from": date_from,
                "date_to": date_to,
                "validity_token": validity_token,
            },
            workload=Workload.ONLINE,
            team_id=team_id,
            settings=REQUEST_USAGE_QUERY_SETTINGS,
            ch_user=ClickHouseUser.BILLING,
        )

    return aggregate_feature_flag_request_usage(rows)


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
        return Response({"results": results, "generated_at": datetime.now(UTC)})
