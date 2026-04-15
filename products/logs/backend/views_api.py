from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.permissions import PostHogFeatureFlagPermission

from products.logs.backend.models import LogsView


class LogsViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    filters = serializers.DictField(
        required=False,
        default=dict,
        help_text="Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.",
    )

    class Meta:
        model = LogsView
        fields = [
            "id",
            "short_id",
            "name",
            "filters",
            "pinned",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "short_id",
            "created_at",
            "created_by",
            "updated_at",
        ]

    def create(self, validated_data: dict[str, Any], *args: Any, **kwargs: Any) -> LogsView:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)


@extend_schema(tags=["logs"])
class LogsViewViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "logs"
    queryset = LogsView.objects.all().order_by("-created_at")
    serializer_class = LogsViewSerializer
    lookup_field = "short_id"
    posthog_feature_flag = "logs-saved-views"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: Any) -> Any:
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("created_by")
        return queryset

    def _track(self, event: str, instance: LogsView) -> None:
        report_user_action(
            self.request.user,
            event,
            {
                "id": str(instance.id),
                "short_id": instance.short_id,
                "name": instance.name,
                "pinned": instance.pinned,
                "has_filters": bool(instance.filters),
            },
            team=self.team,
            request=self.request,
        )

    def perform_create(self, serializer) -> None:
        self._track("logs view created", serializer.save())

    def perform_update(self, serializer) -> None:
        self._track("logs view updated", serializer.save())

    def perform_destroy(self, instance: LogsView) -> None:
        self._track("logs view deleted", instance)
        super().perform_destroy(instance)
