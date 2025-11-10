import logging
from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from rest_framework import filters, serializers, viewsets

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import Team
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.synthetic_monitoring.backend.models import VALID_REGIONS, SyntheticMonitor

logger = logging.getLogger(__name__)


def fetch_sparkline_data_bulk(team_id: int, monitor_ids: list[str]) -> dict:
    """
    Fetch sparkline data for multiple monitors in a single query.
    Returns dict with monitor_id -> {failures: list[int], response_times: list[float]}
    """
    if not monitor_ids:
        return {}

    team = Team.objects.get(id=team_id)
    regions = list(VALID_REGIONS)

    # Single query for all failure data
    failure_query = parse_select(
        """
        SELECT
            outer.monitor_id AS monitor_id,
            outer.hour AS hour,
            outer.region AS region,
            coalesce(inner.failures, 0) AS failures
        FROM (
            SELECT
                arrayJoin({monitor_ids}) AS monitor_id,
                arrayJoin({regions}) AS region,
                arrayJoin(arrayMap(n -> toStartOfHour(now()) - INTERVAL 24 HOUR + INTERVAL n HOUR, range(24))) AS hour
        ) AS outer
        LEFT JOIN (
            SELECT
                properties.monitor_id as monitor_id,
                properties.region as region,
                toStartOfHour(timestamp) as hour,
                countIf(`properties`.`$synthetic_success` = false) as failures
            FROM events
            WHERE
                event = '$synthetic_http_check'
                AND properties.monitor_id IN {monitor_ids}
                AND timestamp >= toStartOfHour(now()) - INTERVAL 25 HOUR -- 25 hours to ensure we get the minutes before the current minute from the first hour
            GROUP BY monitor_id, region, hour
        ) AS inner
        ON outer.monitor_id = inner.monitor_id AND outer.hour = inner.hour AND outer.region = inner.region
        ORDER BY monitor_id, region ASC, hour ASC
        LIMIT {limit}
        """,
        placeholders={
            "monitor_ids": monitor_ids,
            "regions": regions,
            "limit": len(monitor_ids) * len(regions) * 24 + 100,
        },
    )

    # Single query for all response time data
    response_time_query = parse_select(
        """
        SELECT
            outer.monitor_id AS monitor_id,
            outer.hour AS hour,
            outer.region AS region,
            coalesce(inner.avg_time_ms, 0) AS avg_time_ms
        FROM (
            SELECT
                arrayJoin({monitor_ids}) AS monitor_id,
                arrayJoin({regions}) AS region,
                arrayJoin(arrayMap(n -> toStartOfHour(now()) - INTERVAL 24 HOUR + INTERVAL n HOUR, range(24))) AS hour
        ) AS outer
        LEFT JOIN (
            SELECT
                properties.monitor_id as monitor_id,
                properties.region as region,
                toStartOfHour(timestamp) as hour,
                avg(toInt(`properties`.`$synthetic_response_time_ms`)) as avg_time_ms
            FROM events
            WHERE
                event = '$synthetic_http_check'
                AND properties.monitor_id IN {monitor_ids}
                AND timestamp >= toStartOfHour(now()) - INTERVAL 25 HOUR -- 25 hours to ensure we get the minutes before the current minute from the first hour
            GROUP BY monitor_id, region, hour
        ) AS inner
        ON outer.monitor_id = inner.monitor_id AND outer.hour = inner.hour AND outer.region = inner.region
        ORDER BY monitor_id, region ASC, hour ASC
        LIMIT {limit}
        """,
        placeholders={
            "monitor_ids": monitor_ids,
            "regions": regions,
            "limit": len(monitor_ids) * len(regions) * 24 + 100,
        },
    )

    failure_response = execute_hogql_query(
        query_type="SyntheticMonitorFailureSparkline",
        query=failure_query,
        team=team,
    )

    response_time_response = execute_hogql_query(
        query_type="SyntheticMonitorResponseTimeSparkline",
        query=response_time_query,
        team=team,
    )

    # Build data structure: monitor_id -> region -> hour -> value
    failure_data = {monitor_id: {region: {} for region in regions} for monitor_id in monitor_ids}
    for monitor_id, hour, region, failures in failure_response.results:
        failure_data[monitor_id][region][hour] = int(failures)

    response_time_data = {monitor_id: {region: {} for region in regions} for monitor_id in monitor_ids}
    for monitor_id, hour, region, avg_time in response_time_response.results:
        response_time_data[monitor_id][region][hour] = int(avg_time)

    # Generate full 24-hour arrays for each monitor
    result = {}
    base_hour = min(list(failure_data[monitor_ids[0]][regions[0]].keys()))

    for monitor_id in monitor_ids:
        failures = {region: [] for region in regions}
        response_times = {region: [] for region in regions}

        for region in regions:
            current = base_hour

            for _ in range(24):
                failures[region].append(failure_data[monitor_id][region].get(current, 0))
                response_times[region].append(response_time_data[monitor_id][region].get(current, 0.0))
                current += timedelta(hours=1)

        result[monitor_id] = {
            region: {"failures": failures[region], "response_times": response_times[region]} for region in regions
        }

    return result


class SyntheticMonitorSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    """
    Serializer for Synthetic Monitor API endpoints.

    Synthetic monitors track HTTP endpoint uptime and latency from multiple AWS regions.
    All check results are stored as `synthetic_http_check` events in ClickHouse.
    Monitor state (last checked, consecutive failures, etc.) is computed from ClickHouse events on-demand.
    """

    created_by = UserBasicSerializer(read_only=True)
    name = serializers.CharField(
        help_text="Display name for the monitor (e.g., 'API Health Check')",
        max_length=400,
    )
    url = serializers.URLField(
        help_text="The HTTP endpoint URL to monitor (must start with http:// or https://)",
    )
    frequency_minutes = serializers.IntegerField(
        help_text="How often to check the endpoint (1, 5, 15, 30, or 60 minutes)",
    )
    regions = serializers.JSONField(
        help_text="List of AWS regions to run checks from (e.g., ['us-east-1', 'eu-west-1']). Valid regions: us-east-1, us-west-2, eu-west-1, eu-central-1, ap-southeast-1, ap-northeast-1",
    )
    method = serializers.ChoiceField(
        help_text="HTTP method to use for the check",
        choices=SyntheticMonitor.Method.choices,
        default=SyntheticMonitor.Method.GET,
    )
    headers = serializers.JSONField(
        help_text="Custom HTTP headers as JSON object (e.g., {'Authorization': 'Bearer token'})",
        required=False,
        allow_null=True,
    )
    body = serializers.CharField(
        help_text="Request body for POST/PUT requests (optional)",
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    expected_status_code = serializers.IntegerField(
        help_text="Expected HTTP status code (default: 200). Check fails if response status doesn't match. Must be between 100-599.",
        default=200,
    )
    timeout_seconds = serializers.IntegerField(
        help_text="Request timeout in seconds (default: 30, max: 300)",
        default=30,
        min_value=1,
        max_value=300,
    )
    enabled = serializers.BooleanField(
        help_text="Whether the monitor is active. Disabled monitors won't be checked.",
        default=True,
    )
    failure_sparkline = serializers.SerializerMethodField(read_only=True)
    response_time_sparkline = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = SyntheticMonitor
        fields = [
            "id",
            "name",
            "url",
            "frequency_minutes",
            "regions",
            "method",
            "headers",
            "body",
            "expected_status_code",
            "timeout_seconds",
            "enabled",
            "created_by",
            "created_at",
            "updated_at",
            "failure_sparkline",
            "response_time_sparkline",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "failure_sparkline",
            "response_time_sparkline",
        ]

    def create(self, validated_data: dict) -> SyntheticMonitor:
        try:
            request = self.context["request"]
            validated_data["team_id"] = self.context["team_id"]
            validated_data["created_by"] = request.user

            monitor = SyntheticMonitor(**validated_data)

            with transaction.atomic():
                monitor.full_clean()  # Run model validators
                monitor.save()

            report_user_action(
                request.user,
                "synthetic monitor created",
                {
                    "monitor_id": str(monitor.id),
                    "frequency_minutes": monitor.frequency_minutes,
                },
            )

            return monitor
        except DjangoValidationError as e:
            # Convert Django ValidationError to DRF ValidationError
            if hasattr(e, "message_dict"):
                raise serializers.ValidationError(e.message_dict)
            else:
                raise serializers.ValidationError({"non_field_errors": e.messages})

    def update(self, instance: SyntheticMonitor, validated_data: dict) -> SyntheticMonitor:
        request = self.context["request"]

        # Track if enabled status is changing
        enabled_changed = "enabled" in validated_data and validated_data["enabled"] != instance.enabled

        for key, value in validated_data.items():
            setattr(instance, key, value)

        # No state changes needed - state is computed from ClickHouse events

        try:
            instance.full_clean()  # Run model validators
            instance.save()
        except DjangoValidationError as e:
            # Convert Django ValidationError to DRF ValidationError
            if hasattr(e, "message_dict"):
                raise serializers.ValidationError(e.message_dict)
            else:
                raise serializers.ValidationError({"non_field_errors": e.messages})

        action = (
            "synthetic monitor resumed"
            if enabled_changed and instance.enabled
            else (
                "synthetic monitor paused" if enabled_changed and not instance.enabled else "synthetic monitor updated"
            )
        )
        report_user_action(
            request.user,
            action,
            {"monitor_id": str(instance.id)},
        )

        return instance

    def get_failure_sparkline(self, obj: SyntheticMonitor) -> dict[str, list[int]]:
        """Get hourly failure counts for the last 24 hours"""
        sparkline_data = self.context.get("sparkline_data", {})
        monitor_data = sparkline_data.get(str(obj.id), {})
        return {region: monitor_data.get(region, {}).get("failures", []) for region in obj.regions}

    def get_response_time_sparkline(self, obj: SyntheticMonitor) -> dict[str, list[int]]:
        """Get hourly average response times for the last 24 hours"""
        sparkline_data = self.context.get("sparkline_data", {})
        monitor_data = sparkline_data.get(str(obj.id), {})
        return {region: monitor_data.get(region, {}).get("response_times", []) for region in obj.regions}


class SyntheticMonitorViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "synthetic_monitoring"
    queryset = SyntheticMonitor.objects.select_related("created_by")
    serializer_class = SyntheticMonitorSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "url"]
    access_control_level_filters = {}

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team_id)

        # Optionally filter by enabled status
        enabled = self.request.query_params.get("enabled")
        if enabled is not None:
            queryset = queryset.filter(enabled=enabled.lower() == "true")

        # Optionally filter by type
        monitor_type = self.request.query_params.get("type")
        if monitor_type:
            queryset = queryset.filter(type=monitor_type)

        return queryset.order_by("-created_at")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # Fetch sparkline data for list/retrieve operations
        if self.action in ["list", "retrieve"]:
            if self.action == "retrieve" and "pk" in self.kwargs:
                monitor_ids = [str(self.kwargs["pk"])]
            else:
                queryset = self.filter_queryset(self.get_queryset())
                monitor_ids = [str(id) for id in queryset.values_list("id", flat=True)]
            if monitor_ids:
                context["sparkline_data"] = fetch_sparkline_data_bulk(self.team_id, monitor_ids)
        return context

    def perform_destroy(self, instance: SyntheticMonitor):
        report_user_action(
            self.request.user,
            "synthetic monitor deleted",
            {
                "monitor_id": str(instance.id),
                "monitor_name": instance.name,
            },
        )
        instance.delete()
