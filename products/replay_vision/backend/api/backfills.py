"""API for historical backfills: estimate, create, monitor, cancel, resume."""

import uuid
from datetime import datetime
from typing import Any, cast

from django.db import IntegrityError
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.models.replay_observation import IN_FLIGHT_STATUSES, ObservationStatus
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.models.replay_scanner_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    BackfillStatus,
    ReplayScannerBackfill,
)
from products.replay_vision.backend.queries.scanner_candidate_query import BackfillCandidateQuery
from products.replay_vision.backend.quota import compute_quota_snapshot
from products.replay_vision.backend.scanner_access import scanner_for_reading_observations
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot

logger = structlog.get_logger(__name__)

# The enumeration runs inside the request; a pathological filter must fail the request, not hang it.
ENUMERATION_MAX_EXECUTION_SECONDS = 30


class BackfillWindowSerializer(serializers.Serializer):
    window_start = serializers.DateTimeField(help_text="Inclusive lower bound of the historical window to scan.")
    window_end = serializers.DateTimeField(
        help_text="Exclusive upper bound of the window; clamped server-side to the scanner's sweep watermark."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["window_start"] >= attrs["window_end"]:
            raise ValidationError("window_start must be before window_end.")
        return attrs


class BackfillEstimateResponseSerializer(serializers.Serializer):
    total_sessions = serializers.IntegerField(
        help_text="Exact number of eligible sessions the backfill would dispatch, after sampling and quality filters."
    )
    total_credits = serializers.IntegerField(
        help_text="Exact cost ceiling in credits (1 credit = $0.01): total_sessions x credits_per_observation. "
        "Actual spend can only come in under it (already-scanned, expired, or failed sessions are not billed)."
    )
    credits_per_observation = serializers.IntegerField(
        help_text="Per-observation credit price at the scanner's current model."
    )
    credits_remaining = serializers.IntegerField(
        allow_null=True, help_text="Credits left in the org's monthly quota; null when the org is uncapped."
    )
    projected_monthly_credits = serializers.IntegerField(
        help_text="Projected monthly credit spend from enabled scanners plus active backfills' remaining commitments."
    )
    window_start = serializers.DateTimeField(help_text="The window lower bound the estimate covered.")
    window_end = serializers.DateTimeField(
        help_text="The window upper bound after clamping to the scanner's sweep watermark."
    )


class ReplayScannerBackfillSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    succeeded_count = serializers.IntegerField(
        read_only=True, help_text="Observations from this backfill that succeeded."
    )
    failed_count = serializers.IntegerField(read_only=True, help_text="Observations from this backfill that failed.")
    ineligible_count = serializers.IntegerField(
        read_only=True, help_text="Sessions that turned out ineligible (too short, expired recording, ...)."
    )
    in_flight_count = serializers.IntegerField(
        read_only=True, help_text="Observations from this backfill still pending or running."
    )

    class Meta:
        model = ReplayScannerBackfill
        fields = [
            "id",
            "status",
            "window_start",
            "window_end",
            "total_count",
            "dispatched_count",
            "credits_per_observation",
            "succeeded_count",
            "failed_count",
            "ineligible_count",
            "in_flight_count",
            "created_by",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields


class ReplayScannerBackfillViewSet(
    TeamAndOrgViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Historical backfills of a scanner over a closed time window (nested under a scanner)."""

    scope_object = "replay_scanner"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "estimate", "cancel", "resume"]
    permission_classes = [ReplayVisionEnabledPermission]
    serializer_class = ReplayScannerBackfillSerializer
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team and scanner.
    queryset = ReplayScannerBackfill.objects.unscoped()

    _WRITE_ACTIONS = frozenset(scope_object_write_actions)

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Same authorization as /observe/: a backfill dispatches scans, which exposes recording contents.
        if self.action in self._WRITE_ACTIONS:
            return ["replay_scanner:write", "session_recording:read"]
        return ["replay_scanner:read", "session_recording:read"]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if self.action in self._WRITE_ACTIONS and not self.user_access_control.check_access_level_for_resource(
            "session_recording", required_level="viewer"
        ):
            raise PermissionDenied("Starting a Replay Vision backfill requires session_recording read access.")

    def _scanner_for_url(self) -> ReplayScanner:
        cached = getattr(self, "_scanner_for_url_cache", None)
        if cached is not None:
            return cached
        try:
            scanner_id = uuid.UUID(self.kwargs["parent_lookup_scanner_id"])
        except (KeyError, ValueError):
            raise NotFound()
        scanner = scanner_for_reading_observations(self.team_id, scanner_id)
        if scanner is None:
            raise NotFound()
        self._scanner_for_url_cache = scanner
        return scanner

    def safely_get_queryset(self, queryset: QuerySet[ReplayScannerBackfill]) -> QuerySet[ReplayScannerBackfill]:
        return (
            queryset.filter(team_id=self.team_id, scanner=self._scanner_for_url())
            .select_related("created_by")
            .annotate(
                succeeded_count=Count("observations", filter=Q(observations__status=ObservationStatus.SUCCEEDED)),
                failed_count=Count("observations", filter=Q(observations__status=ObservationStatus.FAILED)),
                ineligible_count=Count("observations", filter=Q(observations__status=ObservationStatus.INELIGIBLE)),
                in_flight_count=Count("observations", filter=Q(observations__status__in=IN_FLIGHT_STATUSES)),
            )
            .order_by("-created_at")
        )

    def _clamped_window(self, scanner: ReplayScanner, data: dict[str, Any]) -> tuple[datetime, datetime]:
        """The requested window bounded above by the sweep watermark, so live and backfill never contest a session."""
        window_end = min(data["window_end"], scanner.last_swept_at)
        window_start = data["window_start"]
        if window_start >= window_end:
            raise ValidationError("The requested window is entirely covered by the scanner's live sweep.")
        return window_start, window_end

    def _enumerate(self, scanner: ReplayScanner, window_start: datetime, window_end: datetime) -> int:
        snapshot = BackfillScannerSnapshot.from_scanner(scanner)
        return BackfillCandidateQuery(
            team=scanner.team,
            query=scanner.recordings_query(),
            window_start=window_start,
            window_end=window_end,
            sampling_rate=snapshot.sampling_rate,
            sampling_salt=str(scanner.id),
            sampling_mode=snapshot.sampling_mode,
            max_execution_time_seconds=ENUMERATION_MAX_EXECUTION_SECONDS,
        ).count()

    @extend_schema(request=BackfillWindowSerializer, responses={200: BackfillEstimateResponseSerializer})
    @action(detail=False, methods=["post"], pagination_class=None)
    def estimate(self, request: Request, **kwargs: Any) -> Response:
        """Exactly enumerate what a backfill over the given window would dispatch and cost."""
        scanner = self._scanner_for_url()
        window = BackfillWindowSerializer(data=request.data)
        window.is_valid(raise_exception=True)
        window_start, window_end = self._clamped_window(scanner, window.validated_data)
        total = self._enumerate(scanner, window_start, window_end)
        price = observation_credits_for_model(scanner.model)
        quota = compute_quota_snapshot(scanner.team.organization_id)
        response = BackfillEstimateResponseSerializer(
            {
                "total_sessions": total,
                "total_credits": total * price,
                "credits_per_observation": price,
                "credits_remaining": quota.remaining,
                "projected_monthly_credits": quota.projected_monthly_credits,
                "window_start": window_start,
                "window_end": window_end,
            }
        )
        return Response(response.data)

    @extend_schema(request=BackfillWindowSerializer, responses={201: ReplayScannerBackfillSerializer})
    def create(self, request: Request, **kwargs: Any) -> Response:
        """Create a backfill: freeze the scanner config, enumerate the exact candidate set, start the tick schedule."""
        scanner = self._scanner_for_url()
        window = BackfillWindowSerializer(data=request.data)
        window.is_valid(raise_exception=True)
        window_start, window_end = self._clamped_window(scanner, window.validated_data)
        if ReplayScannerBackfill.objects.filter(scanner=scanner, status__in=ACTIVE_BACKFILL_STATUSES).exists():
            raise ValidationError("This scanner already has an active backfill.")

        snapshot = BackfillScannerSnapshot.from_scanner(scanner)
        total = self._enumerate(scanner, window_start, window_end)
        try:
            backfill = ReplayScannerBackfill.objects.create(
                scanner=scanner,
                team=scanner.team,
                window_start=window_start,
                window_end=window_end,
                scanner_snapshot=snapshot.model_dump(mode="json"),
                credits_per_observation=observation_credits_for_model(snapshot.model),
                total_count=total,
                created_by=cast(Any, request.user),
            )
        except IntegrityError:
            # Concurrent create lost the one-active-per-scanner race.
            raise ValidationError("This scanner already has an active backfill.")

        # noqa below: keeps the temporalio client stack off the API module-load path.
        from products.replay_vision.backend.temporal.schedule import a_upsert_backfill_schedule  # noqa: PLC0415

        try:
            async_to_sync(a_upsert_backfill_schedule)(backfill.id, scanner.team_id, scanner.id)
        except Exception:
            # The reconciler recreates missing schedules for running backfills, so don't fail the request.
            logger.exception("replay_vision.backfill_schedule_create_failed", backfill_id=str(backfill.id))

        # A just-created backfill has no observations; skip the aggregate re-query.
        for count_attr in ("succeeded_count", "failed_count", "ineligible_count", "in_flight_count"):
            setattr(backfill, count_attr, 0)
        return Response(self.get_serializer(backfill).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: ReplayScannerBackfillSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def cancel(self, request: Request, **kwargs: Any) -> Response:
        """Stop an active backfill; already-dispatched observations finish, nothing new dispatches."""
        backfill = self.get_object()
        updated = ReplayScannerBackfill.objects.filter(pk=backfill.pk, status__in=ACTIVE_BACKFILL_STATUSES).update(
            status=BackfillStatus.CANCELLED, finished_at=timezone.now()
        )
        if updated:
            from products.replay_vision.backend.temporal.schedule import a_delete_backfill_schedule  # noqa: PLC0415

            try:
                async_to_sync(a_delete_backfill_schedule)(backfill.pk)
            except Exception:
                # The tick workflow and the reconciler both delete schedules of terminal rows.
                logger.exception("replay_vision.backfill_schedule_delete_failed", backfill_id=str(backfill.pk))
            backfill.status = BackfillStatus.CANCELLED
            backfill.finished_at = timezone.now()
        return Response(self.get_serializer(backfill).data)

    @extend_schema(responses={200: ReplayScannerBackfillSerializer})
    @action(detail=True, methods=["post"], pagination_class=None)
    def resume(self, request: Request, **kwargs: Any) -> Response:
        """Restart a backfill that paused when the monthly quota ran out."""
        backfill = self.get_object()
        updated = ReplayScannerBackfill.objects.filter(pk=backfill.pk, status=BackfillStatus.PAUSED_QUOTA).update(
            status=BackfillStatus.RUNNING
        )
        if not updated:
            raise ValidationError("Only a backfill paused on quota can be resumed.")
        from products.replay_vision.backend.temporal.schedule import a_resume_backfill_schedule  # noqa: PLC0415

        try:
            async_to_sync(a_resume_backfill_schedule)(backfill.pk)
        except Exception:
            logger.exception("replay_vision.backfill_schedule_resume_failed", backfill_id=str(backfill.pk))
        backfill.status = BackfillStatus.RUNNING
        return Response(self.get_serializer(backfill).data)
