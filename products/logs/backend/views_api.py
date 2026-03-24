from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

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

    def safely_get_queryset(self, queryset: Any) -> Any:
        queryset = queryset.filter(team_id=self.team_id)
        queryset = queryset.select_related("created_by")
        return queryset
