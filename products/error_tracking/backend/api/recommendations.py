from datetime import datetime, timedelta
from typing import override

from django.db import IntegrityError
from django.db.models import Count, Q
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

from products.error_tracking.backend.models import (
    ErrorTrackingRecommendation,
    ErrorTrackingStackFrame,
    ErrorTrackingSymbolSet,
)
from products.error_tracking.backend.recommendations import RECOMMENDATIONS, RECOMMENDATIONS_BY_TYPE
from products.error_tracking.backend.recommendations.base import Recommendation
from products.error_tracking.backend.tasks import compute_error_tracking_recommendation

logger = structlog.get_logger(__name__)

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
        # A recommendation that has never finished computing can't be considered
        # completed, even if its empty default meta would otherwise satisfy
        # is_completed() (e.g. an empty issues list).
        if obj.computed_at is None:
            return False
        rec = RECOMMENDATIONS_BY_TYPE.get(obj.type)
        if not rec:
            return False
        return rec.is_completed(self._enriched_meta(obj))


class SourceMapsSetupCheckQuerySerializer(serializers.Serializer):
    since_minutes = serializers.IntegerField(
        required=False,
        default=15,
        min_value=1,
        max_value=60 * 24,
        help_text="How many minutes back to look for uploads and frame activity. Defaults to 15.",
    )


class _SourceMapsSetupCheckSymbolSetSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Symbol set ID.")
    ref = serializers.CharField(help_text="Symbol set reference (chunk ID).")
    created_at = serializers.DateTimeField(help_text="When the symbol set row was created.")
    has_uploaded_file = serializers.BooleanField(
        help_text="Whether the symbol set actually has bytes uploaded to storage."
    )


class _SourceMapsSetupCheckFramesSerializer(serializers.Serializer):
    total = serializers.IntegerField(help_text="JavaScript frames created in the window.")
    resolved = serializers.IntegerField(help_text="Of those, how many resolved via a symbol set.")
    unresolved = serializers.IntegerField(help_text="Of those, how many are still unresolved.")


class SourceMapsSetupCheckSerializer(serializers.Serializer):
    since_minutes = serializers.IntegerField(help_text="The window the response describes.")
    symbol_sets = _SourceMapsSetupCheckSymbolSetSerializer(many=True, help_text="Symbol sets created in the window.")
    frames = _SourceMapsSetupCheckFramesSerializer(help_text="JS frame resolution stats over the window.")


def _is_stale(rec: Recommendation, obj: ErrorTrackingRecommendation, now: datetime) -> bool:
    if obj.computed_at is None:
        return True
    if rec.refresh_interval is None:
        return True
    return now >= obj.computed_at + rec.refresh_interval


def _claim_for_compute(obj_id, team_id: int, now: datetime) -> bool:
    """Atomically transition this recommendation into the 'computing' state.

    Returns True if we claimed the row (caller should kick a task), False if
    another worker already owns it and is still within the stuck threshold.
    """
    stuck_threshold = now - COMPUTING_STUCK_AFTER
    return (
        ErrorTrackingRecommendation.objects.filter(id=obj_id, team_id=team_id)
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


def _revert_to_ready(obj_id, team_id: int) -> None:
    ErrorTrackingRecommendation.objects.filter(
        id=obj_id,
        team_id=team_id,
        status=ErrorTrackingRecommendation.Status.COMPUTING,
    ).update(
        status=ErrorTrackingRecommendation.Status.READY,
        status_changed_at=timezone.now(),
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


def _kick_off_stale_computations(team_id: int) -> None:
    """Kick a celery task for every stale recommendation that we can claim."""
    now = timezone.now()
    for rec in RECOMMENDATIONS:
        try:
            obj = _ensure_recommendation_row(rec, team_id)
            if not _is_stale(rec, obj, now):
                continue
            if not _claim_for_compute(obj.id, team_id, now):
                continue
            try:
                compute_error_tracking_recommendation.delay(str(obj.id), team_id)
            except Exception:
                _revert_to_ready(obj.id, team_id)
                raise
        except Exception as e:
            capture_exception(e)
            logger.warning(
                "error_tracking_recommendation_kick_failed",
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
        # When the frontend is polling for status updates we skip the kick
        # so each poll is a cheap read of the current state.
        is_poll = request.query_params.get("poll", "false").lower() == "true"
        if not is_poll:
            _kick_off_stale_computations(self.team.id)
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses=ErrorTrackingRecommendationSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request: Request, *args, **kwargs) -> Response:
        recommendation = self.get_object()
        if recommendation.type not in RECOMMENDATIONS_BY_TYPE:
            return Response({"detail": "Unknown recommendation type."}, status=status.HTTP_400_BAD_REQUEST)
        force = request.query_params.get("force", "true").lower() != "false"
        if force and _claim_for_compute(recommendation.id, self.team.id, timezone.now()):
            try:
                compute_error_tracking_recommendation.delay(str(recommendation.id), self.team.id)
            except Exception:
                _revert_to_ready(recommendation.id, self.team.id)
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

    @extend_schema(
        request=None,
        responses=SourceMapsSetupCheckSerializer,
        parameters=[SourceMapsSetupCheckQuerySerializer],
    )
    @action(detail=False, methods=["get"], url_path="source_maps_setup_check")
    def source_maps_setup_check(self, request: Request, *args, **kwargs) -> Response:
        """Live read of symbol-set uploads and JavaScript frame resolution over the last N minutes.
        Used by the source maps setup wizard to confirm a build pipeline is producing uploads."""
        params = SourceMapsSetupCheckQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        minutes = params.validated_data["since_minutes"]
        since = timezone.now() - timedelta(minutes=minutes)

        symbol_sets = list(
            ErrorTrackingSymbolSet.objects.filter(team=self.team, created_at__gte=since).order_by("-created_at")[:20]
        )

        frame_counts = ErrorTrackingStackFrame.objects.filter(
            team=self.team,
            created_at__gte=since,
            contents__lang="javascript",
        ).aggregate(
            total=Count("id"),
            resolved=Count("id", filter=Q(resolved=True)),
        )
        total = frame_counts["total"] or 0
        resolved = frame_counts["resolved"] or 0

        payload = {
            "since_minutes": minutes,
            "symbol_sets": [
                {
                    "id": str(ss.id),
                    "ref": ss.ref,
                    "created_at": ss.created_at,
                    "has_uploaded_file": bool(ss.storage_ptr),
                }
                for ss in symbol_sets
            ],
            "frames": {
                "total": total,
                "resolved": resolved,
                "unresolved": total - resolved,
            },
        }
        return Response(SourceMapsSetupCheckSerializer(payload).data, status=status.HTTP_200_OK)
