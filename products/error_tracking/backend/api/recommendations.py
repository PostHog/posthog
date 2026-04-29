from datetime import datetime
from typing import override

from django.db import IntegrityError
from django.utils import timezone

import structlog
from drf_spectacular.utils import extend_schema
from posthoganalytics import capture_exception
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.team import Team

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import RECOMMENDATIONS, RECOMMENDATIONS_BY_TYPE
from products.error_tracking.backend.recommendations.base import Recommendation

logger = structlog.get_logger(__name__)


class ErrorTrackingRecommendationSerializer(serializers.ModelSerializer):
    meta = serializers.SerializerMethodField()
    completed = serializers.SerializerMethodField()

    class Meta:
        model = ErrorTrackingRecommendation
        fields = [
            "id",
            "type",
            "meta",
            "completed",
            "computed_at",
            "dismissed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _enriched_meta(self, obj: ErrorTrackingRecommendation) -> dict:
        rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
        if not rec:
            return obj.meta
        cached = self.context.setdefault("_enriched_meta", {})
        if obj.id not in cached:
            cached[obj.id] = rec.enrich(obj.team, obj.meta)
        return cached[obj.id]

    def get_meta(self, obj: ErrorTrackingRecommendation) -> dict:
        return self._enriched_meta(obj)

    def get_completed(self, obj: ErrorTrackingRecommendation) -> bool:
        rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
        if not rec:
            return False
        return rec.is_completed(self._enriched_meta(obj))


def _is_stale(rec: Recommendation, obj: ErrorTrackingRecommendation, now: datetime) -> bool:
    if obj.computed_at is None:
        return True
    if rec.refresh_interval is None:
        return True
    return now >= obj.computed_at + rec.refresh_interval


def _get_or_refresh(rec: Recommendation, team_id: int, team: Team, now: datetime) -> ErrorTrackingRecommendation:
    try:
        obj = ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)
    except ErrorTrackingRecommendation.DoesNotExist:
        try:
            return ErrorTrackingRecommendation.objects.create(
                team_id=team_id,
                type=rec.type,
                meta=rec.compute(team),
                computed_at=now,
            )
        except IntegrityError:
            obj = ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)

    if _is_stale(rec, obj, now):
        obj.meta = rec.compute(team)
        obj.computed_at = now
        obj.save(update_fields=["meta", "computed_at", "updated_at"])
    return obj


def _compute_if_stale(team_id: int, team: Team) -> None:
    now = timezone.now()
    for rec in RECOMMENDATIONS:
        try:
            _get_or_refresh(rec, team_id, team, now)
        except Exception as e:
            capture_exception(e)
            logger.warning(
                "error_tracking_recommendation_compute_failed",
                team_id=team_id,
                recommendation_type=rec.type,
                exc_info=True,
            )


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
        force = request.query_params.get("force", "true").lower() != "false"
        if force:
            recommendation.meta = rec.compute(self.team)
            recommendation.computed_at = timezone.now()
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
