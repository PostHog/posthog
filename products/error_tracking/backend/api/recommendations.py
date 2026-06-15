from typing import override

from django.utils import timezone

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import RECOMMENDATIONS_BY_TYPE
from products.error_tracking.backend.recommendations.refresh import (
    claim_for_compute,
    refresh_team_recommendations,
    revert_to_ready,
)
from products.error_tracking.backend.tasks import compute_error_tracking_recommendation


class ErrorTrackingRecommendationSerializer(serializers.ModelSerializer):
    meta = serializers.SerializerMethodField(help_text="Recommendation payload, shape depends on type.")
    completed = serializers.SerializerMethodField(
        help_text="Whether the recommendation's recommended action has been satisfied."
    )

    class Meta:
        model = ErrorTrackingRecommendation
        fields = [
            "id",
            "type",
            "meta",
            "completed",
            "status",
            "computed_at",
            "dismissed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "id": {"help_text": "Recommendation UUID."},
            "type": {"help_text": "Recommendation type identifier (e.g. 'alerts')."},
            "status": {"help_text": "'ready' if meta is fresh, 'computing' if a refresh is in progress."},
            "computed_at": {"help_text": "Timestamp meta was last successfully computed."},
            "dismissed_at": {"help_text": "Timestamp the user dismissed this recommendation, if any."},
            "created_at": {"help_text": "Timestamp the recommendation row was first created."},
            "updated_at": {"help_text": "Timestamp the recommendation row was last updated."},
        }

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
        # A recommendation that has never finished computing can't be considered
        # completed, even if its empty default meta would otherwise satisfy
        # is_completed() (e.g. an empty issues list).
        if obj.computed_at is None:
            return False
        rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
        if not rec:
            return False
        return rec.is_completed(self._enriched_meta(obj))


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
        # When the frontend is polling for status updates we skip the kick
        # so each poll is a cheap read of the current state.
        is_poll = request.query_params.get("poll", "false").lower() == "true"
        if not is_poll:
            refresh_team_recommendations(self.team.id)
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        if recommendation.type not in RECOMMENDATIONS_BY_TYPE:
            return Response({"detail": "Unknown recommendation type."}, status=status.HTTP_400_BAD_REQUEST)
        force = request.query_params.get("force", "true").lower() != "false"
        if force and claim_for_compute(recommendation.id, self.team.id, timezone.now()):
            try:
                compute_error_tracking_recommendation.delay(str(recommendation.id), self.team.id)
            except Exception:
                revert_to_ready(recommendation.id, self.team.id)
                raise
            recommendation.refresh_from_db()
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
