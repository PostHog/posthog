from typing import override

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingRecommendationRun, ErrorTrackingRecommendationSettings
from products.error_tracking.backend.recommendations import cross_sell


class ErrorTrackingRecommendationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingRecommendationRun
        fields = ["id", "type", "meta", "created_at", "updated_at"]
        read_only_fields = fields


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingRecommendationRunViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "error_tracking"
    queryset = ErrorTrackingRecommendationRun.objects.all().order_by("type")
    serializer_class = ErrorTrackingRecommendationRunSerializer

    @override
    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    @override
    def list(self, request, *args, **kwargs):
        self._ensure_bootstrapped()
        return super().list(request, *args, **kwargs)

    @action(methods=["POST"], detail=False)
    def refresh(self, request: Request, *args, **kwargs) -> Response:
        """Recompute the cross-sell recommendation synchronously and return the updated list."""
        self._recompute()
        return super().list(request, *args, **kwargs)

    def _ensure_bootstrapped(self) -> None:
        exists = ErrorTrackingRecommendationRun.objects.filter(
            team_id=self.team.id, type=cross_sell.RECOMMENDATION_TYPE
        ).exists()
        if not exists:
            self._recompute()

    def _recompute(self) -> None:
        meta = cross_sell.compute(self.team)
        ErrorTrackingRecommendationRun.objects.update_or_create(
            team_id=self.team.id,
            type=cross_sell.RECOMMENDATION_TYPE,
            defaults={"meta": meta},
        )


class ErrorTrackingRecommendationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorTrackingRecommendationSettings
        fields = ["id", "enabled", "ignored_recommendation_types"]
        read_only_fields = ["id"]


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingRecommendationSettingsViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    def _get_or_create_settings(self) -> ErrorTrackingRecommendationSettings:
        settings, _ = ErrorTrackingRecommendationSettings.objects.get_or_create(team_id=self.team.id)
        return settings

    def list(self, request, *args, **kwargs):
        instance = self._get_or_create_settings()
        serializer = ErrorTrackingRecommendationSettingsSerializer(instance)
        return Response(serializer.data)

    @action(detail=False, methods=["patch"])
    def update_settings(self, request, *args, **kwargs):
        instance = self._get_or_create_settings()
        serializer = ErrorTrackingRecommendationSettingsSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
