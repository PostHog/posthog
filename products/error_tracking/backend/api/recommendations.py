import time
from datetime import datetime, timedelta
from typing import override

from django.db import IntegrityError
from django.db.models import Q
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

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import RECOMMENDATIONS, RECOMMENDATIONS_BY_TYPE
from products.error_tracking.backend.recommendations.base import Recommendation
from products.error_tracking.backend.tasks import compute_error_tracking_recommendation

logger = structlog.get_logger(__name__)

LIST_WAIT_SECONDS = 1.0
LIST_WAIT_POLL_INTERVAL = 0.1
# How long a recommendation can stay in "computing" before we consider the worker
# to have died and re-kick the task on the next list() request.
COMPUTING_STUCK_AFTER = timedelta(minutes=5)


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


def _claim_for_compute(obj_id, now: datetime) -> bool:
    """Atomically transition this recommendation into the 'computing' state.

    Returns True if we claimed the row (caller should kick a task), False if
    another worker already owns it and is still within the stuck threshold.
    """
    stuck_threshold = now - COMPUTING_STUCK_AFTER
    return (
        ErrorTrackingRecommendation.objects.filter(id=obj_id)
        .filter(
            Q(status=ErrorTrackingRecommendation.Status.READY)
            | Q(
                status=ErrorTrackingRecommendation.Status.COMPUTING,
                status_changed_at__lt=stuck_threshold,
            )
        )
        .update(
            status=ErrorTrackingRecommendation.Status.COMPUTING,
            status_changed_at=now,
        )
        == 1
    )


def _ensure_recommendation_row(rec: Recommendation, team_id: int) -> ErrorTrackingRecommendation:
    try:
        return ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)
    except ErrorTrackingRecommendation.DoesNotExist:
        try:
            return ErrorTrackingRecommendation.objects.create(
                team_id=team_id,
                type=rec.type,
                status=ErrorTrackingRecommendation.Status.READY,
            )
        except IntegrityError:
            return ErrorTrackingRecommendation.objects.get(team_id=team_id, type=rec.type)


def _wait_for_pending_computations(team_id: int) -> None:
    """Briefly wait for any in-flight computations to finish.

    Returns as soon as no recommendation for this team is in 'computing' state,
    or after LIST_WAIT_SECONDS, whichever comes first. This makes the common
    case (fast computations or eager-mode tests) feel snappy without giving
    slow computations an unbounded blocking window.
    """
    deadline = time.monotonic() + LIST_WAIT_SECONDS
    while True:
        still_computing = ErrorTrackingRecommendation.objects.filter(
            team_id=team_id,
            status=ErrorTrackingRecommendation.Status.COMPUTING,
        ).exists()
        if not still_computing or time.monotonic() >= deadline:
            return
        time.sleep(LIST_WAIT_POLL_INTERVAL)


def _kick_off_stale_computations(team_id: int) -> bool:
    """Kick a celery task for every stale recommendation that we can claim.

    Returns True if at least one task was kicked.
    """
    now = timezone.now()
    kicked = False
    for rec in RECOMMENDATIONS:
        try:
            obj = _ensure_recommendation_row(rec, team_id)
            if not _is_stale(rec, obj, now):
                continue
            if _claim_for_compute(obj.id, now):
                compute_error_tracking_recommendation.delay(str(obj.id))
                kicked = True
        except Exception as e:
            capture_exception(e)
            logger.warning(
                "error_tracking_recommendation_kick_failed",
                team_id=team_id,
                recommendation_type=rec.type,
                exc_info=True,
            )
    return kicked


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

    @extend_schema(responses=ErrorTrackingRecommendationSerializer(many=True))
    @override
    def list(self, request: Request, *args, **kwargs) -> Response:
        # When the frontend is polling for status updates we skip the kick + wait
        # so each poll is a cheap read of the current state.
        is_poll = request.query_params.get("poll", "false").lower() == "true"
        if not is_poll and _kick_off_stale_computations(self.team.id):
            _wait_for_pending_computations(self.team.id)
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        if recommendation.type not in RECOMMENDATIONS_BY_TYPE:
            return Response({"detail": "Unknown recommendation type."}, status=status.HTTP_400_BAD_REQUEST)
        force = request.query_params.get("force", "true").lower() != "false"
        if force and _claim_for_compute(recommendation.id, timezone.now()):
            compute_error_tracking_recommendation.delay(str(recommendation.id))
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
