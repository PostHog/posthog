from typing import Any

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.permissions import PostHogFeatureFlagPermission

from products.logs.backend.models import LogsView


class LogsViewColumnSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text="Client-generated stable identity for list operations (React keys, reorder). Never interpreted by the server.",
    )
    type = serializers.ChoiceField(
        choices=["timestamp", "level", "source", "trace_id", "span_id", "message", "custom"],
        help_text="Column type. Built-in types resolve client-side from log row fields; `custom` columns are computed server-side from `expression`.",
    )
    # Optional keys are omitted (not null) so the stored JSON round-trips the client shape exactly
    name = serializers.CharField(
        required=False,
        help_text="Header label override. Defaults to the built-in type's label, or to the expression for custom columns.",
    )
    expression = serializers.CharField(
        required=False,
        help_text=(
            "Only meaningful for `type: custom`: a source-prefixed shorthand (`attributes.<key>`, "
            "`resource_attributes.<key>`, `body.<json.path>`) or a scalar HogQL expression, sent verbatim "
            "in the logs query's `customColumns`."
        ),
    )
    width = serializers.IntegerField(
        required=False,
        min_value=1,
        # Mirrors MAX_ATTRIBUTE_COLUMN_WIDTH in the frontend resizer so a legitimate drag can't
        # persist a width the API would reject.
        max_value=2000,
        help_text="Column width in pixels (1–2000). Omitted for the default width; ignored for the flex message column.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # A `custom` column is only renderable if it carries an expression to query;
        # without one the table would show a permanently blank column.
        if attrs.get("type") == "custom" and not attrs.get("expression"):
            raise serializers.ValidationError({"expression": "Custom columns require an expression."})
        return attrs


class LogsViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    filters = serializers.DictField(
        required=False,
        default=dict,
        help_text="Filter criteria — subset of LogsViewerFilters. May contain severityLevels, serviceNames, searchTerm, filterGroup, dateRange, and other keys.",
    )
    columns = serializers.ListField(
        child=LogsViewColumnSerializer(),
        required=False,
        allow_null=True,
        help_text=(
            "Ordered column configuration for the logs table (LogsColumnConfig[]). Order is array index. "
            "Null means the view has no column preference and the client renders its default column set. "
            "Omitting the field on update leaves the saved configuration unchanged; send null to clear it."
        ),
    )

    class Meta:
        model = LogsView
        fields = [
            "id",
            "short_id",
            "name",
            "filters",
            "columns",
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
