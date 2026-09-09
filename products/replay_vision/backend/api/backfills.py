"""API for historical backfills: estimate, create, monitor, cancel, resume."""

import uuid
import datetime as dt
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
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import IN_FLIGHT_STATUSES, ObservationStatus
from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL, ReplayScanner
from products.replay_vision.backend.models.replay_scanner_backfill import (
    ACTIVE_BACKFILL_STATUSES,
    BackfillStatus,
    ReplayScannerBackfill,
)
from products.replay_vision.backend.queries.scanner_candidate_query import (
    BACKFILL_CANDIDATE_QUERY_TYPE,
    BACKFILL_COUNT_QUERY_TYPE,
    WindowedCandidateQuery,
)
from products.replay_vision.backend.quota import quota_state
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot

logger = structlog.get_logger(__name__)

# The enumeration runs inside the request; a pathological filter must fail the request, not hang it.
ENUMERATION_MAX_EXECUTION_SECONDS = 30

# Beyond a year a backfill is asking for recordings almost every team has already aged out, while the
# enumeration pays for the whole partition range. Bounds the per-request ClickHouse cost.
MAX_BACKFILL_WINDOW_DAYS = 365


class BackfillEnumerationThrottle(PersonalApiKeyOrUserRateThrottle):
    """Covers session-authenticated callers, which the global burst/sustained throttles skip.

    `estimate` and `create` each run a synchronous ClickHouse enumeration, so an ordinary UI session
    could otherwise saturate the Replay Vision query pool by resubmitting wide windows.
    """

    scope = "replay_vision_backfill_enumeration"
    rate = "20/minute"


class BackfillWindowSerializer(serializers.Serializer):
    window_start = serializers.DateTimeField(help_text="Inclusive lower bound of the historical window to scan.")
    window_end = serializers.DateTimeField(help_text="Exclusive upper bound of the window; clamped server-side to now.")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["window_start"] >= attrs["window_end"]:
            raise ValidationError("window_start must be before window_end.")
        if attrs["window_end"] - attrs["window_start"] > dt.timedelta(days=MAX_BACKFILL_WINDOW_DAYS):
            raise ValidationError(
                f"Backfill windows are limited to {MAX_BACKFILL_WINDOW_DAYS} days. Pick a shorter range."
            )
        return attrs


class BackfillEstimateResponseSerializer(serializers.Serializer):
    total_sessions = serializers.IntegerField(
        help_text="Upper bound on the sessions the backfill would scan, after sampling and quality "
        "filters and excluding sessions this scanner already reported an observation for."
    )
    total_credits = serializers.IntegerField(
        help_text="Cost ceiling in credits (1 credit = $0.01): total_sessions x credits_per_observation. "
        "Actual spend lands under it: sessions already tried, expired recordings, and failures are not billed."
    )
    credits_per_observation = serializers.IntegerField(
        help_text="Per-observation credit price at the scanner's current model."
    )
    credits_remaining = serializers.IntegerField(
        allow_null=True, help_text="Credits left in the org's monthly quota; null when the org is uncapped."
    )
    window_start = serializers.DateTimeField(help_text="The window lower bound the estimate covered.")
    window_end = serializers.DateTimeField(help_text="The window upper bound after clamping to now.")


class ReplayScannerBackfillSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
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
            "skipped_count",
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
    serializer_class = ReplayScannerBackfillSerializer
    # `objects` is fail-closed; `safely_get_queryset` re-scopes to the request team and scanner.
    queryset = ReplayScannerBackfill.objects.unscoped()

    def get_throttles(self) -> list[Any]:
        # Append, never replace: returning only this throttle would drop the global burst and
        # sustained limits from the two actions that run the heaviest query.
        if self.action in ("estimate", "create"):
            return [*super().get_throttles(), BackfillEnumerationThrottle()]
        return super().get_throttles()

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Same authorization as /observe/: a backfill dispatches scans, which exposes recording contents.
        if self.action in self.scope_object_write_actions:
            return ["replay_scanner:write", "session_recording:read"]
        return ["replay_scanner:read", "session_recording:read"]

    def _scanner_for_url(self) -> ReplayScanner:
        cached = getattr(self, "_scanner_for_url_cache", None)
        if cached is not None:
            return cached
        try:
            scanner_id = uuid.UUID(self.kwargs["parent_lookup_scanner_id"])
        except (KeyError, ValueError):
            raise NotFound()
        # `objects` is configured-only: an inline scan is a throwaway keyed to one question, so it has
        # no schedule to backfill and must not be addressable here (unlike the observation read paths,
        # which opt into `all_origins` to show inline results).
        scanner = ReplayScanner.objects.filter(team_id=self.team_id, pk=scanner_id).first()
        if scanner is None:
            raise NotFound()
        # Backfills expose and dispatch recording-derived scans, so they inherit the scanner's RBAC
        # and also require session_recording read (mirrors ReplayObservationViewSet._scanner_for_url).
        self.check_object_permissions(self.request, scanner)
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Replay Vision backfills require session_recording read access.")
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

    def _clamped_window(self, data: dict[str, Any]) -> tuple[datetime, datetime]:
        """The requested window, bounded above by the settle horizon the live sweep also waits for.

        Not `now`: a session inside the settle window is still recording or still merging, so scanning it
        yields a truncated observation, and the unique (scanner, session) constraint makes that the only
        observation the session will ever get. The live sweep could never replace it once the recording
        finished. Clamping here rather than in the query keeps the quoted count and the walk in agreement,
        so nobody is quoted for sessions the walk will skip.

        Deliberately not clamped to the scanner's sweep watermark. Overlapping the live sweep is safe:
        both paths mint the same deterministic workflow id and the unique (scanner, session) constraint
        means a session can only ever produce one observation, so nothing is scanned or billed twice.
        Whether a backfill is worth running is decided by how many *unobserved* recordings it would
        find, which `_enumerate` answers directly.
        """
        window_end = min(data["window_end"], timezone.now() - SETTLE_INTERVAL)
        window_start = data["window_start"]
        if window_start >= window_end:
            raise ValidationError("The end of the range must be in the past. Pick an earlier range.")
        return window_start, window_end

    def _enumerate(
        self,
        scanner: ReplayScanner,
        window_start: datetime,
        window_end: datetime,
        exclude_observed: bool = False,
    ) -> int:
        snapshot = BackfillScannerSnapshot.from_scanner(scanner)
        return WindowedCandidateQuery(
            team=self.team,
            query=scanner.targeted_recordings_query(),
            # The exposure filter runs as the requesting user, so previewing or launching a
            # backfill of an experiment scanner requires the same experiment access as viewing it.
            user=cast(Any, self.request.user),
            window_start=window_start,
            window_end=window_end,
            query_type=BACKFILL_CANDIDATE_QUERY_TYPE,
            sampling_rate=snapshot.sampling_rate,
            sampling_salt=str(scanner.id),
            scanner_id=str(scanner.id),
            sampling_mode=snapshot.sampling_mode,
            exclude_observed_by_scanner=str(scanner.id) if exclude_observed else None,
            max_execution_time_seconds=ENUMERATION_MAX_EXECUTION_SECONDS,
        ).count(query_type=BACKFILL_COUNT_QUERY_TYPE)

    def _unobserved_count(self, scanner: ReplayScanner, window_start: datetime, window_end: datetime) -> int:
        """Upper bound on what a backfill over this window would scan, rejecting when it is zero.

        An upper bound rather than exact: the exclusion reads `$recording_observed`, which only exists
        for observations that succeeded and managed to publish, so sessions already tried and found
        ineligible or failed still count here. They cannot produce a second observation, so the real
        spend lands under the quote.

        Distinguishes "nothing here matches the scanner" from "everything here is already done"; the
        second count only runs on the rejection path, so the happy path stays at one ClickHouse query.
        """
        unobserved = self._enumerate(scanner, window_start, window_end, exclude_observed=True)
        if unobserved > 0:
            return unobserved
        if self._enumerate(scanner, window_start, window_end) > 0:
            raise ValidationError("All recordings in this range have already been scanned. Pick a different range.")
        # Naming sampling matters: a heavily sampled scanner finds nothing in a short range even
        # though its filters match plenty, and "filters" alone sends people to edit the wrong setting.
        if scanner.sampling_rate < 1:
            raise ValidationError(
                f"No recordings in this range match this scanner. It samples {scanner.sampling_rate:.1%} of "
                "sessions, so try a wider range."
            )
        raise ValidationError("No recordings in this range match this scanner's filters. Try a wider range.")

    @extend_schema(request=BackfillWindowSerializer, responses={200: BackfillEstimateResponseSerializer})
    @action(detail=False, methods=["post"], pagination_class=None)
    def estimate(self, request: Request, **kwargs: Any) -> Response:
        """Exactly enumerate what a backfill over the given window would dispatch and cost."""
        scanner = self._scanner_for_url()
        window = BackfillWindowSerializer(data=request.data)
        window.is_valid(raise_exception=True)
        window_start, window_end = self._clamped_window(window.validated_data)
        total = self._unobserved_count(scanner, window_start, window_end)
        price = observation_credits_for_model(scanner.model)
        quota = quota_state(self.team.organization_id)
        response = BackfillEstimateResponseSerializer(
            {
                "total_sessions": total,
                "total_credits": total * price,
                "credits_per_observation": price,
                "credits_remaining": quota.remaining,
                "window_start": window_start,
                "window_end": window_end,
            }
        )
        return Response(response.data)

    @extend_schema(request=BackfillWindowSerializer, responses={201: ReplayScannerBackfillSerializer})
    def create(self, request: Request, **kwargs: Any) -> Response:
        """Create a backfill: freeze the scanner config, enumerate the exact candidate set, start the tick schedule.

        The enumeration reruns here rather than trusting the client-confirmed estimate: the count is
        billing-relevant, so the authoritative value is computed server-side at creation time. New
        settled sessions between estimate and confirm can nudge total_count slightly.
        """
        scanner = self._scanner_for_url()
        window = BackfillWindowSerializer(data=request.data)
        window.is_valid(raise_exception=True)
        window_start, window_end = self._clamped_window(window.validated_data)
        if ReplayScannerBackfill.objects.filter(scanner=scanner, status__in=ACTIVE_BACKFILL_STATUSES).exists():
            raise ValidationError("This scanner already has an active backfill.")

        snapshot = BackfillScannerSnapshot.from_scanner(scanner)
        total = self._unobserved_count(scanner, window_start, window_end)
        try:
            backfill = ReplayScannerBackfill.objects.create(
                scanner=scanner,
                team=self.team,
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
            async_to_sync(a_resume_backfill_schedule)(backfill.pk, backfill.team_id, backfill.scanner_id)
        except Exception:
            # A RUNNING row with a paused schedule would never tick again and nothing repairs it,
            # so roll the status back and surface the failure for a retry.
            logger.exception("replay_vision.backfill_schedule_resume_failed", backfill_id=str(backfill.pk))
            ReplayScannerBackfill.objects.filter(pk=backfill.pk, status=BackfillStatus.RUNNING).update(
                status=BackfillStatus.PAUSED_QUOTA
            )
            raise APIException("Couldn't resume the backfill. Try again.")
        backfill.status = BackfillStatus.RUNNING
        return Response(self.get_serializer(backfill).data)
