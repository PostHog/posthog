import uuid
import datetime as dt

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import sync_to_async
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal.cleanup_sweep import activities as sweep_activities
from products.replay_vision.backend.temporal.cleanup_sweep.activities import (
    _reap_observations,
    prune_old_observations_activity,
    reap_stranded_observations_activity,
)
from products.replay_vision.backend.temporal.cleanup_sweep.constants import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_STRANDED_HOURS,
    REAP_ERROR_REASON,
)
from products.replay_vision.backend.temporal.cleanup_sweep.types import CleanupSweepInputs
from products.replay_vision.backend.tests.helpers import (
    counter_value,
    snapshot_for as _snapshot_for,
)


def _make_scanner() -> ReplayScanner:
    org = Organization.objects.create(name="cleanup-sweep-test-org")
    team = Team.objects.create(organization=org, name="cleanup-sweep-test-team")
    return ReplayScanner.objects.create(
        team=team,
        name="cleanup-sweep-scanner",
        scanner_type=ScannerType.MONITOR,
        scanner_config={"prompt": "p"},
        model=ScannerModel.GEMINI_3_FLASH,
    )


def _make_observation(
    scanner: ReplayScanner,
    *,
    status: ObservationStatus = ObservationStatus.PENDING,
    workflow_id: str = "",
    session_id: str | None = None,
    created_at: dt.datetime | None = None,
    completed_at: dt.datetime | None = None,
    started_at: dt.datetime | None = None,
) -> ReplayObservation:
    obs = ReplayObservation.objects.create(
        scanner=scanner,
        team=scanner.team,
        session_id=session_id or f"sess-{uuid.uuid4().hex[:8]}",
        status=status,
        workflow_id=workflow_id,
        scanner_snapshot=_snapshot_for(scanner),
        triggered_by=ObservationTrigger.SCHEDULE,
        started_at=started_at,
        completed_at=completed_at,
    )
    # `created_at` is auto_now_add — patch via UPDATE so we can simulate aged rows.
    if created_at is not None:
        ReplayObservation.objects.filter(pk=obs.id).update(created_at=created_at)
        obs.refresh_from_db()
    return obs


@pytest.mark.django_db(transaction=True)
class TestPruneOldObservationsActivity:
    @pytest.mark.asyncio
    async def test_deletes_terminal_rows_older_than_retention(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        cutoff = timezone.now() - dt.timedelta(days=DEFAULT_RETENTION_DAYS + 1)
        old = await sync_to_async(_make_observation)(scanner, status=ObservationStatus.SUCCEEDED, completed_at=cutoff)
        recent = await sync_to_async(_make_observation)(
            scanner,
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now() - dt.timedelta(days=DEFAULT_RETENTION_DAYS - 1),
        )

        result = await prune_old_observations_activity(CleanupSweepInputs())

        assert result.rows_deleted == 1
        assert result.batches_run == 1
        assert not result.hit_cap
        assert not await sync_to_async(ReplayObservation.objects.filter(pk=old.id).exists)()
        assert await sync_to_async(ReplayObservation.objects.filter(pk=recent.id).exists)()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        [ObservationStatus.PENDING, ObservationStatus.RUNNING],
    )
    async def test_never_deletes_in_flight_rows(self, status: ObservationStatus) -> None:
        # In-flight rows have `completed_at IS NULL` (CheckConstraint) so the prune filter excludes them by design.
        scanner = await sync_to_async(_make_scanner)()
        ancient_creation = timezone.now() - dt.timedelta(days=365)
        ancient = await sync_to_async(_make_observation)(scanner, status=status, created_at=ancient_creation)

        result = await prune_old_observations_activity(CleanupSweepInputs())

        assert result.rows_deleted == 0
        assert await sync_to_async(ReplayObservation.objects.filter(pk=ancient.id).exists)()

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_to_prune(self) -> None:
        await sync_to_async(_make_scanner)()  # ensures the DB has tables but no expired rows

        result = await prune_old_observations_activity(CleanupSweepInputs())

        assert result.rows_deleted == 0
        assert result.batches_run == 0
        assert not result.hit_cap

    @pytest.mark.asyncio
    async def test_increments_pruned_counter(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        for _ in range(3):
            await sync_to_async(_make_observation)(
                scanner,
                status=ObservationStatus.FAILED,
                completed_at=timezone.now() - dt.timedelta(days=DEFAULT_RETENTION_DAYS + 1),
            )
        before = counter_value("replay_vision_cleanup_sweep_rows_total", action="pruned")

        await prune_old_observations_activity(CleanupSweepInputs())

        assert counter_value("replay_vision_cleanup_sweep_rows_total", action="pruned") == before + 3

    @pytest.mark.asyncio
    async def test_respects_custom_retention_days(self) -> None:
        scanner = await sync_to_async(_make_scanner)()
        thirty_days_ago = timezone.now() - dt.timedelta(days=30)
        target = await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.FAILED, completed_at=thirty_days_ago
        )

        # retention_days=7 means anything completed >7d ago is in scope.
        result = await prune_old_observations_activity(CleanupSweepInputs(retention_days=7))

        assert result.rows_deleted == 1
        assert not await sync_to_async(ReplayObservation.objects.filter(pk=target.id).exists)()

    @pytest.mark.asyncio
    async def test_hits_cap_when_more_than_max_batches_of_rows_match(self) -> None:
        # Shrink the per-sweep budget so the test doesn't have to insert thousands of rows.
        scanner = await sync_to_async(_make_scanner)()
        cutoff = timezone.now() - dt.timedelta(days=DEFAULT_RETENTION_DAYS + 1)
        for _ in range(5):
            await sync_to_async(_make_observation)(scanner, status=ObservationStatus.SUCCEEDED, completed_at=cutoff)
        before_hit_cap = counter_value("replay_vision_cleanup_sweep_hit_cap_total", stage="prune")

        with (
            patch.object(sweep_activities, "PRUNE_BATCH_SIZE", 1),
            patch.object(sweep_activities, "PRUNE_MAX_BATCHES", 2),
        ):
            result = await prune_old_observations_activity(CleanupSweepInputs())

        assert result.rows_deleted == 2
        assert result.batches_run == 2
        assert result.hit_cap is True
        assert counter_value("replay_vision_cleanup_sweep_hit_cap_total", stage="prune") == before_hit_cap + 1

    @pytest.mark.asyncio
    async def test_does_not_report_hit_cap_when_last_batch_is_short(self) -> None:
        # When the scope is exactly MAX_BATCHES * BATCH_SIZE rows, the previous `==` check false-reported
        # hit_cap. The new `len(ids) < PRUNE_BATCH_SIZE → break` guard avoids that.
        scanner = await sync_to_async(_make_scanner)()
        cutoff = timezone.now() - dt.timedelta(days=DEFAULT_RETENTION_DAYS + 1)
        for _ in range(2):
            await sync_to_async(_make_observation)(scanner, status=ObservationStatus.SUCCEEDED, completed_at=cutoff)
        before_hit_cap = counter_value("replay_vision_cleanup_sweep_hit_cap_total", stage="prune")

        with (
            patch.object(sweep_activities, "PRUNE_BATCH_SIZE", 2),
            patch.object(sweep_activities, "PRUNE_MAX_BATCHES", 1),
        ):
            result = await prune_old_observations_activity(CleanupSweepInputs())

        assert result.rows_deleted == 2
        assert result.hit_cap is False
        assert counter_value("replay_vision_cleanup_sweep_hit_cap_total", stage="prune") == before_hit_cap


@pytest.mark.django_db(transaction=True)
class TestReapStrandedObservationsActivity:
    @pytest.fixture
    def aged(self) -> dt.datetime:
        # Older than the stranded threshold.
        return timezone.now() - dt.timedelta(hours=DEFAULT_STRANDED_HOURS + 1)

    @pytest.fixture
    def fresh(self) -> dt.datetime:
        return timezone.now() - dt.timedelta(hours=DEFAULT_STRANDED_HOURS - 1)

    def _patched_temporal(self, *, classifier_for) -> AsyncMock:
        """Build an AsyncMock for the Temporal client whose `describe()` routes per workflow_id."""
        temporal = MagicMock()

        def make_handle(workflow_id: str) -> MagicMock:
            handle = MagicMock()
            handle.describe = AsyncMock(side_effect=lambda: classifier_for(workflow_id))
            return handle

        temporal.get_workflow_handle.side_effect = make_handle
        return temporal

    @pytest.mark.asyncio
    async def test_reaps_rows_whose_workflow_completed(self, aged: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        stranded = await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.RUNNING, workflow_id="wf-completed", created_at=aged
        )

        completed = MagicMock()
        completed.status = WorkflowExecutionStatus.COMPLETED
        temporal = self._patched_temporal(classifier_for=lambda wf_id: completed)

        before_obs = counter_value("replay_vision_observations_total", status="failed", scanner_type="monitor")
        before_kind = counter_value("replay_vision_failure_kinds_total", kind="internal_error", scanner_type="monitor")

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.scanned == 1
        assert result.reaped == 1
        assert result.skipped_running == 0
        assert result.skipped_temporal_error == 0
        await sync_to_async(stranded.refresh_from_db)()
        assert stranded.status == ObservationStatus.FAILED
        assert stranded.error_reason == REAP_ERROR_REASON
        # Per-scanner counters mirror what mark_observation_failed_activity would have emitted.
        assert (
            counter_value("replay_vision_observations_total", status="failed", scanner_type="monitor") == before_obs + 1
        )
        assert (
            counter_value("replay_vision_failure_kinds_total", kind="internal_error", scanner_type="monitor")
            == before_kind + 1
        )

    @pytest.mark.asyncio
    async def test_skips_rows_whose_workflow_is_still_running(self, aged: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        live = await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.RUNNING, workflow_id="wf-still-going", created_at=aged
        )

        running = MagicMock()
        running.status = WorkflowExecutionStatus.RUNNING
        temporal = self._patched_temporal(classifier_for=lambda wf_id: running)

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.scanned == 1
        assert result.reaped == 0
        assert result.skipped_running == 1
        await sync_to_async(live.refresh_from_db)()
        assert live.status == ObservationStatus.RUNNING

    @pytest.mark.asyncio
    async def test_reaps_rows_whose_workflow_history_is_gone(self, aged: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.PENDING, workflow_id="wf-purged", created_at=aged
        )

        not_found = RPCError("not found", RPCStatusCode.NOT_FOUND, b"")

        def classify(wf_id: str) -> MagicMock:
            raise not_found

        temporal = self._patched_temporal(classifier_for=classify)

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.reaped == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "rpc_status",
        [RPCStatusCode.UNAVAILABLE, RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.INTERNAL],
    )
    async def test_skips_rows_when_typed_rpc_error_is_not_not_found(
        self, rpc_status: RPCStatusCode, aged: dt.datetime
    ) -> None:
        scanner = await sync_to_async(_make_scanner)()
        await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.RUNNING, workflow_id="wf-rpc-error", created_at=aged
        )

        def classify(wf_id: str) -> MagicMock:
            raise RPCError("rpc failed", rpc_status, b"")

        temporal = self._patched_temporal(classifier_for=classify)

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.reaped == 0
        assert result.skipped_temporal_error == 1

    @pytest.mark.asyncio
    async def test_skips_rows_when_temporal_describe_errors_unexpectedly(self, aged: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.RUNNING, workflow_id="wf-error", created_at=aged
        )

        def classify(wf_id: str) -> MagicMock:
            raise RuntimeError("temporal unreachable")

        temporal = self._patched_temporal(classifier_for=classify)

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.reaped == 0
        assert result.skipped_temporal_error == 1

    @pytest.mark.asyncio
    async def test_reaps_rows_with_empty_workflow_id_without_calling_temporal(self, aged: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.PENDING, workflow_id="", created_at=aged
        )

        temporal = MagicMock()
        temporal.get_workflow_handle = MagicMock(side_effect=AssertionError("temporal must not be called"))

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.reaped == 1

    @pytest.mark.asyncio
    async def test_does_not_consider_fresh_rows(self, fresh: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        recent = await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.RUNNING, workflow_id="wf-recent", created_at=fresh
        )

        # Temporal is never reached because there are no candidates.
        temporal = MagicMock()
        temporal.get_workflow_handle = MagicMock(side_effect=AssertionError("temporal must not be called"))

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.scanned == 0
        assert result.reaped == 0
        await sync_to_async(recent.refresh_from_db)()
        assert recent.status == ObservationStatus.RUNNING

    @pytest.mark.asyncio
    async def test_does_not_consider_terminal_rows(self, aged: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        terminal = await sync_to_async(_make_observation)(
            scanner,
            status=ObservationStatus.SUCCEEDED,
            workflow_id="wf-done",
            created_at=aged,
            completed_at=aged + dt.timedelta(hours=1),
        )

        temporal = MagicMock()
        temporal.get_workflow_handle = MagicMock(side_effect=AssertionError("temporal must not be called"))

        with patch(
            "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.scanned == 0
        await sync_to_async(terminal.refresh_from_db)()
        assert terminal.status == ObservationStatus.SUCCEEDED

    def test_reap_helper_skips_rows_that_already_left_in_flight_states(self) -> None:
        # If a workflow completes between candidate selection and the reap UPDATE,
        # the status filter in _reap_observations leaves the now-terminal row alone.

        scanner = _make_scanner()
        already_succeeded = _make_observation(scanner, status=ObservationStatus.SUCCEEDED, completed_at=timezone.now())

        count = _reap_observations([already_succeeded.id])

        assert count == 0
        already_succeeded.refresh_from_db()
        assert already_succeeded.status == ObservationStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_end_to_end_race_completion_between_classify_and_reap_update(self, aged: dt.datetime) -> None:
        # The full reap path: row is candidate, classify returns 'reap', but the row legitimately
        # completed in the meantime. The filtered UPDATE should leave it alone and report reaped=0.
        scanner = await sync_to_async(_make_scanner)()
        racing = await sync_to_async(_make_observation)(
            scanner, status=ObservationStatus.RUNNING, workflow_id="wf-racy", created_at=aged
        )

        # Classify returns NOT_FOUND (→ "reap"); the test then mutates the row before _reap_observations runs.
        not_found = RPCError("not found", RPCStatusCode.NOT_FOUND, b"")

        def classify(wf_id: str) -> MagicMock:
            raise not_found

        temporal = self._patched_temporal(classifier_for=classify)

        # Wrap _reap_observations so the row flips terminal *after* classify but *before* the UPDATE.
        original_reap = sweep_activities._reap_observations

        def flipping_reap(ids: list) -> int:
            ReplayObservation.objects.filter(pk=racing.id).update(
                status=ObservationStatus.SUCCEEDED, completed_at=timezone.now()
            )
            return original_reap(ids)

        with (
            patch(
                "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
                new=AsyncMock(return_value=temporal),
            ),
            patch.object(sweep_activities, "_reap_observations", flipping_reap),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        # Classify said reap, but the filtered UPDATE found 0 rows to flip.
        assert result.scanned == 1
        assert result.reaped == 0
        await sync_to_async(racing.refresh_from_db)()
        assert racing.status == ObservationStatus.SUCCEEDED

    @pytest.mark.asyncio
    async def test_hits_cap_when_candidate_count_equals_max(self, aged: dt.datetime) -> None:
        scanner = await sync_to_async(_make_scanner)()
        for _ in range(3):
            await sync_to_async(_make_observation)(
                scanner, status=ObservationStatus.PENDING, workflow_id="", created_at=aged
            )
        before_hit_cap = counter_value("replay_vision_cleanup_sweep_hit_cap_total", stage="reap")

        # async_connect runs unconditionally once candidates are non-empty (before any per-row
        # short-circuit), so we have to patch it even though every row has workflow_id="".
        temporal = MagicMock()
        with (
            patch.object(sweep_activities, "REAP_MAX_CANDIDATES", 2),
            patch(
                "products.replay_vision.backend.temporal.cleanup_sweep.activities.async_connect",
                new=AsyncMock(return_value=temporal),
            ),
        ):
            result = await reap_stranded_observations_activity(CleanupSweepInputs())

        assert result.scanned == 2
        assert result.hit_cap is True
        assert counter_value("replay_vision_cleanup_sweep_hit_cap_total", stage="reap") == before_hit_cap + 1
