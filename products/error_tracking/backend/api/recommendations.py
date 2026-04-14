from typing import override

from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import REGISTRY


class ErrorTrackingRecommendationSerializer(serializers.ModelSerializer):
    next_refresh_at = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingRecommendation
        fields = ["id", "type", "meta", "computed_at", "dismissed_at", "next_refresh_at", "created_at", "updated_at"]
        read_only_fields = fields

    def get_next_refresh_at(self, obj: ErrorTrackingRecommendation) -> str | None:
        module = REGISTRY.get(obj.type)
        if not module or not obj.computed_at:
            return None
        return (obj.computed_at + module.REFRESH_INTERVAL).isoformat()


def _compute_if_stale(team_id: int, team) -> None:
    now = timezone.now()
    for rec_type, module in REGISTRY.items():
        rec, created = ErrorTrackingRecommendation.objects.get_or_create(
            team_id=team_id,
            type=rec_type,
            defaults={"meta": module.compute(team), "computed_at": now},
        )
        if not created and (rec.computed_at is None or now >= rec.computed_at + module.REFRESH_INTERVAL):
            rec.meta = module.compute(team)
            rec.computed_at = now
            rec.save(update_fields=["meta", "computed_at", "updated_at"])


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingRecommendationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "error_tracking"
    queryset = ErrorTrackingRecommendation.objects.all().order_by("type")
    serializer_class = ErrorTrackingRecommendationSerializer

    @override
    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    @override
    def list(self, request: Request, *args, **kwargs) -> Response:
        _compute_if_stale(self.team.id, self.team)
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        module = REGISTRY.get(recommendation.type)
        if not module:
            return Response({"detail": "Unknown recommendation type."}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        recommendation.meta = module.compute(self.team)
        recommendation.computed_at = now
        recommendation.save(update_fields=["meta", "computed_at", "updated_at"])
        return Response(ErrorTrackingRecommendationSerializer(recommendation).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def dismiss(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        recommendation.dismissed_at = timezone.now()
        recommendation.save(update_fields=["dismissed_at", "updated_at"])
        return Response(ErrorTrackingRecommendationSerializer(recommendation).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def restore(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        recommendation.dismissed_at = None
        recommendation.save(update_fields=["dismissed_at", "updated_at"])
        return Response(ErrorTrackingRecommendationSerializer(recommendation).data, status=status.HTTP_200_OK)
