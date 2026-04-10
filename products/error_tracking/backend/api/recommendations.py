from typing import override

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, viewsets

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingRecommendationRun
from products.error_tracking.backend.recommendations import ALL_RECOMMENDATIONS


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
        # Bootstrap: if the team has never had any recommendations computed
        # (e.g. because no watched team field ever changed), compute them all
        # synchronously on first view so the tab isn't empty.
        self._ensure_bootstrapped()
        return super().list(request, *args, **kwargs)

    def _ensure_bootstrapped(self) -> None:
        existing_types = set(
            ErrorTrackingRecommendationRun.objects.filter(team_id=self.team.id).values_list("type", flat=True)
        )
        missing = [r for r in ALL_RECOMMENDATIONS if r.type not in existing_types]
        if not missing:
            return
        for recommendation in missing:
            meta = recommendation.compute(self.team)
            ErrorTrackingRecommendationRun.objects.update_or_create(
                team_id=self.team.id,
                type=recommendation.type,
                defaults={"meta": meta},
            )
