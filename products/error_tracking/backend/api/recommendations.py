from typing import override

from django.db import IntegrityError
from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import RECOMMENDATIONS, RECOMMENDATIONS_BY_TYPE


class ErrorTrackingRecommendationSerializer(serializers.ModelSerializer):
    next_refresh_at = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingRecommendation
        fields = ["id", "type", "meta", "computed_at", "dismissed_at", "next_refresh_at", "created_at", "updated_at"]
        read_only_fields = fields

    def get_next_refresh_at(self, obj: ErrorTrackingRecommendation) -> str | None:
        rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
        if not rec or not obj.computed_at:
            return None
        return (obj.computed_at + rec.refresh_interval).isoformat()


def _compute_if_stale(team_id: int, team) -> None:
    now = timezone.now()
    for rec in RECOMMENDATIONS:
        try:
            obj = ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)
        except ErrorTrackingRecommendation.DoesNotExist:
            try:
                ErrorTrackingRecommendation.objects.create(
                    team_id=team_id,
                    type=rec.type,
                    meta=rec.compute(team),
                    computed_at=now,
                )
            except IntegrityError:
                pass
            continue
        if obj.computed_at is None or now >= obj.computed_at + rec.refresh_interval:
            obj.meta = rec.compute(team)
            obj.computed_at = now
            obj.save(update_fields=["meta", "computed_at", "updated_at"])


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingRecommendationViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    scope_object = "error_tracking"
    scope_object_write_actions = ["refresh", "dismiss", "restore"]
    queryset = ErrorTrackingRecommendation.objects.all().order_by("type")
    serializer_class = ErrorTrackingRecommendationSerializer

    @override
    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    @override
    def list(self, request: Request, *args, **kwargs) -> Response:
        _compute_if_stale(self.team.id, self.team)
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        rec = RECOMMENDATIONS_BY_TYPE.get(recommendation.type)
        if not rec:
            return Response({"detail": "Unknown recommendation type."}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        if recommendation.computed_at is None or now >= recommendation.computed_at + rec.refresh_interval:
            recommendation.meta = rec.compute(self.team)
            recommendation.computed_at = now
            recommendation.save(update_fields=["meta", "computed_at", "updated_at"])
        return Response(ErrorTrackingRecommendationSerializer(recommendation).data, status=status.HTTP_200_OK)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def dismiss(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        recommendation.dismissed_at = timezone.now()
        recommendation.save(update_fields=["dismissed_at", "updated_at"])
        return Response(ErrorTrackingRecommendationSerializer(recommendation).data, status=status.HTTP_200_OK)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def restore(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        recommendation.dismissed_at = None
        recommendation.save(update_fields=["dismissed_at", "updated_at"])
        return Response(ErrorTrackingRecommendationSerializer(recommendation).data, status=status.HTTP_200_OK)
