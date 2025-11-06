from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from rest_framework import filters, serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin

from products.synthetic_monitoring.backend.models import SyntheticMonitor


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
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
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


class SyntheticMonitorViewSet(
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    viewsets.ModelViewSet,
):
    scope_object = "INTERNAL"
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

        # Note: State filtering would require querying ClickHouse events
        # For MVP, we skip state filtering in the queryset

        # Optionally filter by type
        monitor_type = self.request.query_params.get("type")
        if monitor_type:
            queryset = queryset.filter(type=monitor_type)

        return queryset.order_by("-created_at")

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
