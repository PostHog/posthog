from __future__ import annotations

from typing import cast

from django.db.models import QuerySet

from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.event_usage import report_user_action
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission

from products.tracing.backend.models import TracingView


class TracingViewSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created the view.")
    filters = serializers.DictField(
        required=False,
        default=dict,
        help_text=(
            "Saved tracing filters — a subset of the frontend TracingFilters shape. May contain "
            "dateRange, serviceNames, filterGroup, orderBy, orderDirection, and viewMode."
        ),
    )

    class Meta:
        model = TracingView
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


class TracingViewViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "tracing"
    serializer_class = TracingViewSerializer
    lookup_field = "short_id"
    posthog_feature_flag = "tracing-saved-views"
    permission_classes = [PostHogFeatureFlagPermission]
    # Fail-closed manager raises if `.all()` runs at import; the real per-request
    # scoping happens in safely_get_queryset.
    queryset = TracingView.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet[TracingView]) -> QuerySet[TracingView]:
        return TracingView.objects.for_team(self.team_id).select_related("created_by").order_by("-created_at")

    def _track(self, event: str, instance: TracingView) -> None:
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
        self._track("tracing view created", instance)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        self._track("tracing view updated", serializer.save())

    def perform_destroy(self, instance: TracingView) -> None:
        self._track("tracing view deleted", instance)
        super().perform_destroy(instance)
