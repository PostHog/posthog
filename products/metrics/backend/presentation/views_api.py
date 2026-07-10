from __future__ import annotations

from typing import Any, cast

from django.db.models import QuerySet

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.metrics.backend.models import MetricsView

# The `filters` blob is free-form frontend state, so it is not schema-validated field by field.
# These bounds keep a teammate from persisting a pathologically large or deeply nested payload
# that every other viewer of the shared view then has to parse and render.
MAX_FILTERS_DEPTH = 20
MAX_FILTERS_ARRAY_LENGTH = 1000


def _validate_filters_bounds(value: Any, depth: int = 0) -> None:
    if depth > MAX_FILTERS_DEPTH:
        raise serializers.ValidationError(f"Saved filters nest deeper than the {MAX_FILTERS_DEPTH} level limit.")
    if isinstance(value, dict):
        for item in value.values():
            _validate_filters_bounds(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_FILTERS_ARRAY_LENGTH:
            raise serializers.ValidationError(
                f"Saved filters contain an array longer than the {MAX_FILTERS_ARRAY_LENGTH} entry limit."
            )
        for item in value:
            _validate_filters_bounds(item, depth + 1)


class MetricsViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created the view.")
    filters = serializers.DictField(
        required=False,
        default=dict,
        help_text=(
            "Saved viewer state — the frontend MetricsViewerSavedFilters shape. May contain "
            "metricName, aggregation, filters, groupBy, dateFrom, dateTo, viewMode, and statSummary."
        ),
    )

    def validate_filters(self, value: dict) -> dict:
        _validate_filters_bounds(value)
        return value

    class Meta:
        model = MetricsView
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
        extra_kwargs = {
            "name": {"help_text": "Human-readable name shown in the saved views list."},
            "pinned": {"help_text": "Whether the view is pinned for quick access."},
        }


class MetricsViewViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "metrics"
    serializer_class = MetricsViewSerializer
    lookup_field = "short_id"
    posthog_feature_flag = "metrics"
    permission_classes = [PostHogFeatureFlagPermission]
    # Fail-closed manager raises if `.all()` runs at import; the real per-request
    # scoping happens in safely_get_queryset.
    queryset = MetricsView.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[MetricsView]) -> QuerySet[MetricsView]:
        return MetricsView.objects.for_team(self.team_id).select_related("created_by").order_by("-created_at")

    def _track(self, event: str, instance: MetricsView) -> None:
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

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        instance = serializer.save(team=self.team, created_by=cast(User, self.request.user))
        self._track("metrics view created", instance)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("metrics view updated", serializer.save())

    def perform_destroy(self, instance: MetricsView) -> None:
        self._track("metrics view deleted", instance)
        super().perform_destroy(instance)
