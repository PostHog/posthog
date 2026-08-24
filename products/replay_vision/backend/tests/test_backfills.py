import uuid
import datetime as dt

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from rest_framework.exceptions import PermissionDenied
from rest_framework.status import HTTP_429_TOO_MANY_REQUESTS
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.models import Organization, Team
from posthog.redis import get_client
from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import (
    STUCK_SESSION_THRESHOLD,
    _stuck_key,
)

from products.replay_vision.backend.api.backfills import (
    MAX_BACKFILL_WINDOW_DAYS,
    BackfillEnumerationThrottle,
    ReplayScannerBackfillViewSet,
)
from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import (
    SETTLE_INTERVAL,
    ReplayScanner,
    ScannerModel,
    ScannerType,
)
from products.replay_vision.backend.models.replay_scanner_backfill import BackfillStatus, ReplayScannerBackfill
from products.replay_vision.backend.queries import excluded_sessions
from products.replay_vision.backend.queries.scanner_candidate_query import CandidateSession
from products.replay_vision.backend.quota import QuotaState, compute_quota_snapshot, spend_projection
from products.replay_vision.backend.temporal.activities.backfill import (
    advance_backfill_cursor_activity,
    delete_backfill_schedule_activity,
    find_backfill_candidates_activity,
    pause_backfill_schedule_activity,
    prepare_backfill_tick_activity,
)
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.backfill_types import (
    AdvanceBackfillCursorInputs,
    AdvanceBackfillCursorOutput,
    BackfillTickAction,
    BackfillTickInputs,
    FindBackfillCandidatesInputs,
    FindBackfillCandidatesOutput,
    PrepareBackfillTickOutput,
)
from products.replay_vision.backend.temporal.backfill_workflow import BackfillScannerWorkflow
from products.replay_vision.backend.temporal.constants import (
    APPLY_SCANNER_WORKFLOW_NAME,
    MAX_IN_FLIGHT_APPLIES_PER_BACKFILL,
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
    ON_DEMAND_RESERVED_SCANNER_SLOTS,
    ON_DEMAND_RESERVED_TEAM_SLOTS,
    backfill_dispatch_budget,
    build_apply_scanner_workflow_id,
)
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot
from products.replay_vision.backend.temporal.sweep_types import CandidateSessionPayload
from products.replay_vision.backend.temporal.types import CreateObservationInputs
from products.replay_vision.backend.tests.helpers import seed_scanner_spend

_WINDOW_END = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
_WINDOW_START = _WINDOW_END - dt.timedelta(days=30)


def _make_scanner(**overrides) -> ReplayScanner:
    org = Organization.objects.create(name="backfill-test-org")
    team = Team.objects.create(organization=org, name="backfill-test-team")
    defaults: dict = {
        "team": team,
        "name": "t",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_7_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


def _frozen_snapshot(scanner: ReplayScanner, **overrides) -> dict:
    return {**BackfillScannerSnapshot.from_scanner(scanner).model_dump(mode="json"), **overrides}


def _make_backfill(scanner: ReplayScanner, **overrides) -> ReplayScannerBackfill:
    defaults: dict = {
        "scanner": scanner,
        "team": scanner.team,
        "window_start": _WINDOW_START,
        "window_end": _WINDOW_END,
        "scanner_snapshot": _frozen_snapshot(scanner),
        "credits_per_observation": 5,
        "total_count": 100,
    }
    defaults.update(overrides)
    return ReplayScannerBackfill.objects.for_team(scanner.team_id).create(**defaults)


@pytest.mark.parametrize(
    "scanner_in_flight,team_in_flight,backfill_in_flight,expected",
    [
        # One case per cap that can win, plus the fully-saturated floor. Scheduled dispatch caps
        # exclude the slots reserved for on-demand admission.
        (0, 0, 0, MAX_IN_FLIGHT_APPLIES_PER_BACKFILL),
        (0, 0, MAX_IN_FLIGHT_APPLIES_PER_BACKFILL, 0),
        (MAX_IN_FLIGHT_APPLIES_PER_SCANNER - ON_DEMAND_RESERVED_SCANNER_SLOTS - 10, 0, 0, 10),
        (0, MAX_IN_FLIGHT_APPLIES_PER_TEAM - ON_DEMAND_RESERVED_TEAM_SLOTS - 5, 0, 5),
    ],
)
def test_backfill_dispatch_budget_takes_the_tightest_cap(
    scanner_in_flight: int, team_in_flight: int, backfill_in_flight: int, expected: int
) -> None:
    assert backfill_dispatch_budget(scanner_in_flight, team_in_flight, backfill_in_flight) == expected


@pytest.mark.django_db(transaction=True)
class TestBackfillQuotaCommitment:
    def test_only_active_backfills_contribute_their_remaining_commitment(self) -> None:
        scanner = _make_scanner()
        org_id = scanner.team.organization_id
        _make_backfill(scanner, total_count=100, dispatched_count=40, credits_per_observation=5)
        # Terminal rows and fully-dispatched rows must not inflate the prognosis.
        cancelled_scanner = ReplayScanner.objects.create(
            team=scanner.team,
            name="c",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        _make_backfill(cancelled_scanner, status=BackfillStatus.CANCELLED, total_count=100, credits_per_observation=5)

        assert spend_projection(org_id).backfills_committed_credits == 60 * 5
        assert compute_quota_snapshot(org_id).projected_monthly_credits == 60 * 5

    def test_paused_backfill_still_counts_as_committed(self) -> None:
        scanner = _make_scanner()
        _make_backfill(
            scanner, status=BackfillStatus.PAUSED_QUOTA, total_count=10, dispatched_count=4, credits_per_observation=2
        )
        assert spend_projection(scanner.team.organization_id).backfills_committed_credits == 12


@pytest.mark.django_db(transaction=True)
class TestCreateObservationForBackfill:
    def test_backfill_observation_uses_frozen_snapshot_not_live_scanner(self) -> None:
        scanner = _make_scanner(scanner_config={"prompt": "new prompt"})
        backfill = _make_backfill(
            scanner, scanner_snapshot=_frozen_snapshot(scanner, scanner_config={"prompt": "frozen prompt"})
        )
        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-1",
                backfill_id=backfill.id,
            )
        )
        assert result.was_created
        observation = backfill.observations.get()
        assert observation.scanner_snapshot["scanner_config"] == {"prompt": "frozen prompt"}
        assert observation.triggered_by == ObservationTrigger.BACKFILL

    def test_scanner_limit_prices_the_backfill_observation_from_its_frozen_model(self) -> None:
        # The frozen 15-credit model is what the observation charges; switching the scanner to a
        # 2-credit model must not let it slip under a limit with only 5 credits left.
        scanner = _make_scanner(credit_limit=20)
        backfill = _make_backfill(scanner, scanner_snapshot=_frozen_snapshot(scanner))
        seed_scanner_spend(scanner, 15)
        ReplayScanner.objects.filter(pk=scanner.pk).update(model=ScannerModel.GEMINI_3_5_FLASH_LITE)
        scanner.refresh_from_db()
        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-frozen-price",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-frozen-price",
                backfill_id=backfill.id,
            )
        )
        assert result.observation_id is None
        assert not result.was_created
        assert not backfill.observations.exists()

    def test_capped_retake_counts_as_in_flight_spend_for_the_next_admission(self) -> None:
        # The retake reserves fresh budget under the admission lock, so the next admission's budget
        # read must see it and refuse; missing it would overshoot the cap by the retaken row.
        credits = observation_credits_for_model(ScannerModel.GEMINI_3_7_FLASH.value)
        scanner = _make_scanner(credit_limit=credits)
        backfill = _make_backfill(scanner)
        failed = ReplayObservation.objects.create(
            scanner=scanner,
            team=scanner.team,
            session_id="sess-a",
            status=ObservationStatus.FAILED,
            workflow_id="wf-old",
            scanner_snapshot=_frozen_snapshot(scanner),
            triggered_by=ObservationTrigger.BACKFILL,
            completed_at=timezone.now(),
        )

        retake = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-a",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-retake",
                backfill_id=backfill.id,
            )
        )
        assert retake.was_created is True
        assert retake.observation_id == failed.id
        failed.refresh_from_db()
        assert failed.status == ObservationStatus.PENDING
        assert failed.workflow_id == "wf-retake"

        admission = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-b",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-next",
                backfill_id=backfill.id,
            )
        )
        assert admission.was_created is False
        assert not ReplayObservation.objects.filter(scanner=scanner, session_id="sess-b").exists()

    @pytest.mark.parametrize(
        "seeded_status,expect_retaken",
        [
            # A failed scan emits no $recording_observed event, so the creation-time count quotes that session
            # as work. Leaving the row alone would report progress for a scan that never re-ran.
            (ObservationStatus.FAILED, True),
            # A succeeded session is already billed; retaking it would scan and charge twice.
            (ObservationStatus.SUCCEEDED, False),
        ],
    )
    def test_backfill_retakes_only_a_failed_observation(self, seeded_status: str, expect_retaken: bool) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        existing = ReplayObservation.objects.create(
            scanner=scanner,
            team=scanner.team,
            session_id="sess-1",
            status=seeded_status,
            workflow_id="wf-old",
            scanner_snapshot=_frozen_snapshot(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            completed_at=timezone.now(),
        )
        seeded_at = existing.created_at

        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-new",
                backfill_id=backfill.id,
            )
        )

        assert result.was_created is expect_retaken
        existing.refresh_from_db()
        assert existing.status == (ObservationStatus.PENDING if expect_retaken else seeded_status)
        assert existing.workflow_id == ("wf-new" if expect_retaken else "wf-old")
        if expect_retaken:
            # A pending row must carry no completion time, and the period windows key off created_at,
            # so a retaken row billing into the period its first attempt ran in would escape the cap.
            assert existing.completed_at is None
            assert existing.created_at > seeded_at

    def test_cancelled_backfill_skips_creation(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        result = create_observation_activity(
            CreateObservationInputs(
                scanner_id=scanner.id,
                team_id=scanner.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.BACKFILL,
                triggered_by_user_id=None,
                workflow_id="wf-1",
                backfill_id=backfill.id,
            )
        )
        assert not result.was_created
        assert not backfill.observations.exists()


@pytest.mark.django_db(transaction=True)
class TestBackfillTickActivities:
    @staticmethod
    def _tick_inputs(backfill: ReplayScannerBackfill) -> BackfillTickInputs:
        return BackfillTickInputs(backfill_id=backfill.id, team_id=backfill.team_id, scanner_id=backfill.scanner_id)

    def test_prepare_finishes_on_terminal_row_and_skips_on_disabled_scanner(self) -> None:
        scanner = _make_scanner()
        cancelled = _make_backfill(scanner, status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        assert prepare_backfill_tick_activity(self._tick_inputs(cancelled)).action == BackfillTickAction.FINISHED

        scanner.enabled = False
        scanner.save()
        running = _make_backfill(scanner)
        assert prepare_backfill_tick_activity(self._tick_inputs(running)).action == BackfillTickAction.SKIP

    def test_prepare_repauses_a_quota_paused_row(self) -> None:
        # The reaper can recreate a paused backfill's schedule unpaused; a SKIP here would tick forever.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, status=BackfillStatus.PAUSED_QUOTA)
        assert prepare_backfill_tick_activity(self._tick_inputs(backfill)).action == BackfillTickAction.PAUSE

    def test_prepare_skips_without_org_ai_consent(self) -> None:
        # Children would decline at create while the cursor walks past their sessions.
        scanner = _make_scanner()
        org = scanner.team.organization
        org.is_ai_data_processing_approved = False
        org.save()
        backfill = _make_backfill(scanner)
        assert prepare_backfill_tick_activity(self._tick_inputs(backfill)).action == BackfillTickAction.SKIP

    def test_prepare_clamps_batch_to_remaining_quota(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, credits_per_observation=5)
        # A real state, not a mock: the point of the test is the arithmetic that turns remaining
        # credits into a batch size, and a stubbed collaborator can't fail when that changes.
        headroom = QuotaState(
            credit_limit=7,
            credits_used=0,
            period_start=_WINDOW_START,
            period_end=_WINDOW_END,
        )
        with patch(
            "products.replay_vision.backend.temporal.activities.backfill.quota_state",
            return_value=headroom,
        ):
            result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.DISPATCH
        assert result.dispatch_budget == 1

    def test_prepare_pauses_when_org_quota_exhausted(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        exhausted = MagicMock()
        exhausted.would_exceed.return_value = True
        with patch(
            "products.replay_vision.backend.temporal.activities.backfill.quota_state",
            return_value=exhausted,
        ):
            result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.PAUSE
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.PAUSED_QUOTA

    def test_prepare_dispatches_with_budget_when_headroom_available(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.DISPATCH
        assert result.dispatch_budget > 0

    def test_prepare_holds_the_tick_when_the_scanner_limit_is_reached(self) -> None:
        # Held like the disabled-scanner case: children would decline at create while the cursor walks
        # past their sessions, completing the backfill with zero observations. The hold keeps it
        # RUNNING so it resumes when the period resets or the limit rises.
        scanner = _make_scanner(credit_limit=10)
        backfill = _make_backfill(scanner, credits_per_observation=5)
        seed_scanner_spend(scanner, 10)
        result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.SKIP
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.RUNNING

    def test_prepare_clamps_batch_to_the_scanner_limits_headroom(self) -> None:
        scanner = _make_scanner(credit_limit=22)
        backfill = _make_backfill(scanner, credits_per_observation=5)
        seed_scanner_spend(scanner, 10)
        result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.DISPATCH
        # 12 credits of headroom at 5 apiece fits two children.
        assert result.dispatch_budget == 2

    def test_prepare_ignores_spend_on_an_uncapped_scanner(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, credits_per_observation=5)
        seed_scanner_spend(scanner, 1000)
        result = prepare_backfill_tick_activity(self._tick_inputs(backfill))
        assert result.action == BackfillTickAction.DISPATCH
        assert result.dispatch_budget == MAX_IN_FLIGHT_APPLIES_PER_BACKFILL

    def test_advance_is_idempotent_under_retry(self) -> None:
        # Temporal retries an activity whose result was lost after it committed; a blind second
        # increment would inflate progress and understate the remaining credit commitment.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        advance = AdvanceBackfillCursorInputs(
            backfill_id=backfill.id,
            team_id=backfill.team_id,
            new_cursor_end_time=_WINDOW_END - dt.timedelta(days=1),
            new_cursor_session_id="sess-1",
            dispatched_delta=5,
            exhausted=False,
        )
        advance_backfill_cursor_activity(advance)
        advance_backfill_cursor_activity(advance)
        backfill.refresh_from_db()
        assert backfill.dispatched_count == 5

    def test_skipped_candidates_count_as_done_and_clear_their_commitment(self) -> None:
        # A skipped candidate was quoted and then scanned by the live sweep first, so it is done and the
        # backfill no longer owes its credits.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        ReplayScannerBackfill.objects.for_team(backfill.team_id).filter(pk=backfill.id).update(
            total_count=10, credits_per_observation=5
        )

        advance_backfill_cursor_activity(
            AdvanceBackfillCursorInputs(
                backfill_id=backfill.id,
                team_id=backfill.team_id,
                new_cursor_end_time=_WINDOW_END - dt.timedelta(days=1),
                new_cursor_session_id="sess-10",
                dispatched_delta=6,
                skipped_delta=4,
                exhausted=False,
            )
        )

        backfill.refresh_from_db()
        assert (backfill.dispatched_count, backfill.skipped_count) == (6, 4)
        # All ten accounted for, so nothing is still committed.
        assert spend_projection(scanner.team.organization_id).backfills_committed_credits == 0

    def test_advance_updates_cursor_and_short_batch_completes(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        cursor_time = _WINDOW_END - dt.timedelta(days=2)
        result = advance_backfill_cursor_activity(
            AdvanceBackfillCursorInputs(
                backfill_id=backfill.id,
                team_id=backfill.team_id,
                new_cursor_end_time=cursor_time,
                new_cursor_session_id="sess-9",
                dispatched_delta=2,
                exhausted=False,
            )
        )
        assert not result.finished
        backfill.refresh_from_db()
        assert (backfill.cursor_end_time, backfill.cursor_session_id) == (cursor_time, "sess-9")
        assert backfill.dispatched_count == 2
        assert backfill.status == BackfillStatus.RUNNING

        result = advance_backfill_cursor_activity(
            AdvanceBackfillCursorInputs(
                backfill_id=backfill.id,
                team_id=backfill.team_id,
                expected_cursor_end_time=cursor_time,
                expected_cursor_session_id="sess-9",
                exhausted=True,
            )
        )
        assert result.finished
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.COMPLETED
        assert backfill.finished_at is not None

    def test_drained_window_finishes_instead_of_crashing_the_tick(self) -> None:
        # An empty batch used to index candidates[-1]. The activity runs with maximum_attempts=1, so the
        # tick died, the minute schedule refired forever, and the backfill sat RUNNING until cancelled.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        with patch("products.replay_vision.backend.temporal.activities.backfill.WindowedCandidateQuery") as query_cls:
            query_cls.return_value.run.return_value = []
            result = find_backfill_candidates_activity(
                FindBackfillCandidatesInputs(backfill_id=backfill.id, team_id=backfill.team_id, candidate_limit=50)
            )
        assert result.candidates == []
        # A short batch is what completes the backfill, and the cursor must not move on an empty one.
        assert not result.more_work_below_cursor
        assert result.next_cursor_end_time is None
        assert result.skipped_delta == 0

    def test_unrunnable_exposure_filter_cancels_the_backfill(self) -> None:
        # The candidate query raises PermissionDenied when the launcher was deleted or lost
        # experiment access. Left RUNNING, the backfill would fail every minute forever while its
        # unspent credits kept inflating the spend projection — the tick must cancel it terminally.
        # Also pins the fail-closed manager path: the cancel runs outside request context, where a
        # bare `objects` access raises TeamScopeError instead of cancelling.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        with patch("products.replay_vision.backend.temporal.activities.backfill.WindowedCandidateQuery") as query_cls:
            query_cls.return_value.run.side_effect = PermissionDenied("experiment access lost")
            with pytest.raises(ApplicationError) as raised:
                find_backfill_candidates_activity(
                    FindBackfillCandidatesInputs(backfill_id=backfill.id, team_id=backfill.team_id, candidate_limit=50)
                )
        assert raised.value.non_retryable
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.CANCELLED
        assert backfill.finished_at is not None

    def test_excluded_sessions_are_walked_over_not_dispatched(self) -> None:
        # The cursor must pass an excluded session exactly as it passes an already-succeeded one.
        # Filtering before the walk would leave the cursor short and refetch the same rows forever.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        fetched = [
            CandidateSession(session_id="keep", session_end=timezone.now() - dt.timedelta(hours=2)),
            CandidateSession(session_id="blocked", session_end=timezone.now() - dt.timedelta(hours=1)),
        ]
        with (
            patch("products.replay_vision.backend.temporal.activities.backfill.WindowedCandidateQuery") as query_cls,
            patch.object(excluded_sessions, "excluded_session_ids", return_value={"blocked"}),
        ):
            query_cls.return_value.run.return_value = fetched
            result = find_backfill_candidates_activity(
                FindBackfillCandidatesInputs(backfill_id=backfill.id, team_id=backfill.team_id, candidate_limit=50)
            )

        assert query_cls.call_args.kwargs["skip_negative_blocklists"] is True
        assert [c.session_id for c in result.candidates] == ["keep"]
        # walked past the excluded row, not stopped at the survivor
        assert result.next_cursor_session_id == "blocked"

    def test_stuck_sessions_are_walked_over_not_dispatched(self) -> None:
        # A session quarantined by the rasterizer's stuck counter cannot render; dispatching it from
        # a backfill burns retry envelopes the same way the live sweep's filter prevents.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        fetched = [
            CandidateSession(session_id="keep", session_end=timezone.now() - dt.timedelta(hours=2)),
            CandidateSession(session_id="wedged", session_end=timezone.now() - dt.timedelta(hours=1)),
        ]
        redis_client = get_client()
        for _ in range(STUCK_SESSION_THRESHOLD):
            redis_client.incr(_stuck_key(backfill.team_id, "wedged"))
        with (
            patch("products.replay_vision.backend.temporal.activities.backfill.WindowedCandidateQuery") as query_cls,
            patch.object(excluded_sessions, "excluded_session_ids", return_value=set()),
        ):
            query_cls.return_value.run.return_value = fetched
            result = find_backfill_candidates_activity(
                FindBackfillCandidatesInputs(backfill_id=backfill.id, team_id=backfill.team_id, candidate_limit=50)
            )

        assert [c.session_id for c in result.candidates] == ["keep"]
        assert result.next_cursor_session_id == "wedged"

    def test_exclusion_failure_fails_the_tick_rather_than_dispatching(self) -> None:
        # In-query blocklists are off by this point, so swallowing would dispatch unfiltered.
        scanner = _make_scanner()
        backfill = _make_backfill(scanner)
        with (
            patch("products.replay_vision.backend.temporal.activities.backfill.WindowedCandidateQuery") as query_cls,
            patch.object(excluded_sessions, "excluded_session_ids", side_effect=RuntimeError("clickhouse down")),
        ):
            query_cls.return_value.run.return_value = [
                CandidateSession(session_id="s1", session_end=timezone.now() - dt.timedelta(hours=1))
            ]
            with pytest.raises(RuntimeError):
                find_backfill_candidates_activity(
                    FindBackfillCandidatesInputs(backfill_id=backfill.id, team_id=backfill.team_id, candidate_limit=50)
                )

    def test_advance_loses_to_concurrent_cancel(self) -> None:
        scanner = _make_scanner()
        backfill = _make_backfill(scanner, status=BackfillStatus.CANCELLED, finished_at=timezone.now())
        result = advance_backfill_cursor_activity(
            AdvanceBackfillCursorInputs(backfill_id=backfill.id, team_id=backfill.team_id, exhausted=True)
        )
        assert not result.finished
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.CANCELLED


class TestBackfillsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="backfill-api-scanner",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "p"},
            model=ScannerModel.GEMINI_3_7_FLASH,
        )
        self.base_url = f"/api/projects/{self.team.id}/vision/scanners/{self.scanner.id}/backfills"

    def tearDown(self) -> None:
        super().tearDown()

    def _window_body(self) -> dict:
        now = timezone.now()
        return {
            "window_start": (now - dt.timedelta(days=30)).isoformat(),
            "window_end": (now + dt.timedelta(days=1)).isoformat(),
        }

    @patch("products.replay_vision.backend.temporal.schedule.a_upsert_backfill_schedule", new_callable=AsyncMock)
    @patch("products.replay_vision.backend.api.backfills.WindowedCandidateQuery")
    def test_create_freezes_config_clamps_window_to_settle_horizon_and_rejects_second_active(
        self, mock_query: MagicMock, mock_upsert: AsyncMock
    ) -> None:
        mock_query.return_value.count.return_value = 7
        # Well behind the settle horizon, so the watermark assertion below measures the intended thing
        # rather than the microseconds between scanner creation and this request.
        self.scanner.last_swept_at = timezone.now() - dt.timedelta(days=2)
        self.scanner.save(update_fields=["last_swept_at"])
        response = self.client.post(f"{self.base_url}/", self._window_body(), format="json")
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["total_count"] == 7
        assert body["status"] == "running"

        backfill = ReplayScannerBackfill.objects.for_team(self.team.id).get(pk=body["id"])
        # A window reaching into the future is clamped back to the settle horizon, but is no longer cut
        # at the scanner's sweep watermark: overlap with the live sweep is safe and often the whole point.
        assert backfill.window_end <= timezone.now() - SETTLE_INTERVAL
        assert backfill.window_end > self.scanner.last_swept_at
        assert backfill.scanner_snapshot["scanner_config"] == {"prompt": "p"}
        assert backfill.credits_per_observation > 0
        assert mock_upsert.await_count == 1

        response = self.client.post(f"{self.base_url}/", self._window_body(), format="json")
        assert response.status_code == 400
        assert "active backfill" in response.json()["detail"]

    @patch("products.replay_vision.backend.api.backfills.WindowedCandidateQuery")
    def test_estimate_returns_exact_ceiling_without_creating_rows(self, mock_query: MagicMock) -> None:
        mock_query.return_value.count.return_value = 40
        response = self.client.post(f"{self.base_url}/estimate/", self._window_body(), format="json")
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["total_sessions"] == 40
        assert body["total_credits"] == 40 * body["credits_per_observation"]
        assert not ReplayScannerBackfill.objects.for_team(self.team.id).filter(scanner=self.scanner).exists()

    @patch("products.replay_vision.backend.api.backfills.WindowedCandidateQuery")
    def test_window_stops_at_the_settle_horizon_the_sweep_waits_for(self, mock_query: MagicMock) -> None:
        # A session inside the settle window is still recording or still merging. Scanning it yields a
        # truncated observation, and the unique (scanner, session) constraint means that is the only
        # observation the session ever gets, so the live sweep can never replace it once it finishes.
        mock_query.return_value.count.return_value = 3
        body = {
            "window_start": (timezone.now() - dt.timedelta(days=2)).isoformat(),
            "window_end": (timezone.now() + dt.timedelta(days=1)).isoformat(),
        }

        response = self.client.post(f"{self.base_url}/estimate/", body, format="json")

        assert response.status_code == 200, response.json()
        window_end = dt.datetime.fromisoformat(response.json()["window_end"])
        assert window_end <= timezone.now() - SETTLE_INTERVAL
        # The quote has to describe the window actually walked, or it counts sessions the walk skips.
        assert mock_query.call_args.kwargs["window_end"] == window_end

    def test_window_entirely_inside_the_settle_horizon_is_rejected(self) -> None:
        body = {
            "window_start": (timezone.now() - dt.timedelta(minutes=5)).isoformat(),
            "window_end": timezone.now().isoformat(),
        }
        response = self.client.post(f"{self.base_url}/estimate/", body, format="json")
        assert response.status_code == 400

    def test_estimate_rejects_window_longer_than_the_cap(self) -> None:
        # An unbounded window makes the synchronous enumeration pay for the whole partition range.
        body = {
            "window_start": (timezone.now() - dt.timedelta(days=MAX_BACKFILL_WINDOW_DAYS + 1)).isoformat(),
            "window_end": timezone.now().isoformat(),
        }
        response = self.client.post(f"{self.base_url}/estimate/", body, format="json")
        assert response.status_code == 400
        assert "365 days" in str(response.json())

    @patch("products.replay_vision.backend.api.backfills.WindowedCandidateQuery")
    def test_estimate_rejects_when_every_candidate_is_already_observed(self, mock_query: MagicMock) -> None:
        # Excluded run returns 0 while the unfiltered run finds rows: nothing left for a backfill to do.
        mock_query.return_value.count.side_effect = [0, 5]
        self.scanner.observations.create(
            team=self.team,
            session_id="already-done",
            status=ObservationStatus.SUCCEEDED,
            triggered_by=ObservationTrigger.SCHEDULE,
            scanner_snapshot={},
            completed_at=timezone.now(),
        )
        response = self.client.post(f"{self.base_url}/estimate/", self._window_body(), format="json")
        assert response.status_code == 400
        assert "already been scanned" in str(response.json())

    @patch("products.replay_vision.backend.api.backfills.WindowedCandidateQuery")
    def test_estimate_rejects_when_nothing_matches_the_scanner(self, mock_query: MagicMock) -> None:
        mock_query.return_value.count.return_value = 0
        response = self.client.post(f"{self.base_url}/estimate/", self._window_body(), format="json")
        assert response.status_code == 400
        assert "match this scanner" in str(response.json())

    @patch("products.replay_vision.backend.temporal.schedule.a_delete_backfill_schedule", new_callable=AsyncMock)
    def test_cancel_marks_terminal(self, _mock_delete: AsyncMock) -> None:
        backfill = _make_backfill(self.scanner)
        response = self.client.post(f"{self.base_url}/{backfill.id}/cancel/")
        assert response.status_code == 200, response.json()
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.CANCELLED
        assert backfill.finished_at is not None

    @patch("products.replay_vision.backend.temporal.schedule.a_resume_backfill_schedule", new_callable=AsyncMock)
    def test_resume_only_applies_to_quota_paused_backfills(self, _mock_resume: AsyncMock) -> None:
        backfill = _make_backfill(self.scanner, status=BackfillStatus.PAUSED_QUOTA)
        response = self.client.post(f"{self.base_url}/{backfill.id}/resume/")
        assert response.status_code == 200, response.json()
        backfill.refresh_from_db()
        assert backfill.status == BackfillStatus.RUNNING

        running = backfill
        response = self.client.post(f"{self.base_url}/{running.id}/resume/")
        assert response.status_code == 400

    def test_enumerating_actions_are_throttled_and_cheap_ones_are_not(self) -> None:
        # The global burst/sustained throttles extend PersonalApiKeyRateThrottle, which gates on
        # personal-API-key auth, so a UI session skips them and could resubmit wide windows until the
        # ClickHouse pool is saturated. Denying the throttle and asserting the status proves it is wired
        # into the request path; inspecting get_throttles() alone passes even if DRF never consults it.
        backfill = _make_backfill(self.scanner, status=BackfillStatus.PAUSED_QUOTA)
        with (
            patch.object(BackfillEnumerationThrottle, "allow_request", return_value=False),
            patch.object(BackfillEnumerationThrottle, "wait", return_value=None),
        ):
            estimate = self.client.post(f"{self.base_url}/estimate/", self._window_body(), format="json")
            create = self.client.post(f"{self.base_url}/", self._window_body(), format="json")
            # Cancel and resume don't enumerate, so throttling them would just block recovery.
            resume = self.client.post(f"{self.base_url}/{backfill.id}/resume/")

        assert estimate.status_code == HTTP_429_TOO_MANY_REQUESTS
        assert create.status_code == HTTP_429_TOO_MANY_REQUESTS
        assert resume.status_code != HTTP_429_TOO_MANY_REQUESTS

    def test_enumeration_throttle_keeps_the_global_limits(self) -> None:
        # Appended, not substituted: the personal-API-key limits must survive on the heaviest actions.
        viewset = ReplayScannerBackfillViewSet()
        viewset.action = "estimate"
        assert len(viewset.get_throttles()) > 1
        assert BackfillEnumerationThrottle.rate

    def test_list_includes_observation_progress_counts(self) -> None:
        backfill = _make_backfill(self.scanner, dispatched_count=3)
        for i, status in enumerate([ObservationStatus.SUCCEEDED, ObservationStatus.FAILED, ObservationStatus.PENDING]):
            backfill.observations.create(
                scanner=self.scanner,
                team=self.team,
                session_id=f"sess-{i}",
                status=status,
                triggered_by=ObservationTrigger.BACKFILL,
                scanner_snapshot=backfill.scanner_snapshot,
                completed_at=timezone.now() if status != ObservationStatus.PENDING else None,
            )
        response = self.client.get(f"{self.base_url}/")
        assert response.status_code == 200
        row = response.json()["results"][0]
        assert (row["succeeded_count"], row["failed_count"], row["in_flight_count"]) == (1, 1, 1)


# BackfillScannerWorkflow (mocked-Temporal)


class _BackfillMocks:
    def __init__(
        self,
        *,
        activity_results: dict | None = None,
        child_errors_for_ids: dict[str, Exception] | None = None,
    ) -> None:
        self.activity_results = activity_results or {}
        self.child_errors_for_ids = child_errors_for_ids or {}
        self.activity_calls: list[tuple] = []
        self.child_calls: list[dict] = []

    async def execute_activity(self, activity_fn, activity_input, **_) -> object:
        self.activity_calls.append((activity_fn, activity_input))
        if activity_fn is advance_backfill_cursor_activity and activity_fn not in self.activity_results:
            return AdvanceBackfillCursorOutput(finished=False)
        return self.activity_results.get(activity_fn)

    async def start_child_workflow(self, *args, **kwargs) -> object:
        wid = kwargs.get("id")
        self.child_calls.append({"id": wid, "inputs": args[1] if len(args) > 1 else None})
        if wid is not None and wid in self.child_errors_for_ids:
            raise self.child_errors_for_ids[wid]
        return MagicMock()


def _backfill_tick_inputs() -> BackfillTickInputs:
    return BackfillTickInputs(backfill_id=uuid.uuid4(), team_id=42, scanner_id=uuid.uuid4())


async def _run_backfill_tick(mocks: _BackfillMocks, inputs: BackfillTickInputs | None = None) -> None:
    # `workflow.logger` reaches into the workflow runtime, which isn't set up here.
    fake_logger = type(
        "Logger",
        (),
        {
            "info": staticmethod(lambda *_a, **_kw: None),
            "warning": staticmethod(lambda *_a, **_kw: None),
            "exception": staticmethod(lambda *_a, **_kw: None),
        },
    )()
    with (
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.start_child_workflow", side_effect=mocks.start_child_workflow),
        patch("temporalio.workflow.logger", fake_logger),
    ):
        await BackfillScannerWorkflow().run(inputs or _backfill_tick_inputs())


def _called(mocks: _BackfillMocks) -> list:
    return [fn for fn, _ in mocks.activity_calls]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,follow_up",
    [
        # A terminal row tears its own schedule down; without this the minute schedule outlives the backfill.
        (BackfillTickAction.FINISHED, delete_backfill_schedule_activity),
        (BackfillTickAction.PAUSE, pause_backfill_schedule_activity),
    ],
)
async def test_gate_actions_run_their_schedule_op_and_nothing_else(action, follow_up) -> None:
    mocks = _BackfillMocks(activity_results={prepare_backfill_tick_activity: PrepareBackfillTickOutput(action=action)})

    await _run_backfill_tick(mocks)

    assert _called(mocks) == [prepare_backfill_tick_activity, follow_up]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prep",
    [
        PrepareBackfillTickOutput(action=BackfillTickAction.SKIP),
        # A dispatch with no budget must not run the tick's most expensive query.
        PrepareBackfillTickOutput(action=BackfillTickAction.DISPATCH, dispatch_budget=0),
    ],
)
async def test_held_tick_never_enumerates(prep) -> None:
    mocks = _BackfillMocks(activity_results={prepare_backfill_tick_activity: prep})

    await _run_backfill_tick(mocks)

    assert _called(mocks) == [prepare_backfill_tick_activity]
    assert mocks.child_calls == []


@pytest.mark.asyncio
async def test_dispatch_starts_a_child_per_candidate_and_threads_the_walk_into_the_advance() -> None:
    cursor = dt.datetime(2026, 4, 30, tzinfo=dt.UTC)
    inputs = _backfill_tick_inputs()
    mocks = _BackfillMocks(
        activity_results={
            prepare_backfill_tick_activity: PrepareBackfillTickOutput(
                action=BackfillTickAction.DISPATCH, dispatch_budget=2
            ),
            find_backfill_candidates_activity: FindBackfillCandidatesOutput(
                candidates=[
                    CandidateSessionPayload(session_id="sess-a", session_end=cursor),
                    CandidateSessionPayload(session_id="sess-b", session_end=cursor),
                ],
                skipped_delta=3,
                next_cursor_end_time=cursor,
                next_cursor_session_id="sess-b",
                started_from_cursor_end_time=None,
                started_from_cursor_session_id="",
                more_work_below_cursor=True,
            ),
        }
    )

    await _run_backfill_tick(mocks, inputs)

    assert [c["id"] for c in mocks.child_calls] == [
        build_apply_scanner_workflow_id(inputs.scanner_id, "sess-a"),
        build_apply_scanner_workflow_id(inputs.scanner_id, "sess-b"),
    ]
    advance = next(call for fn, call in mocks.activity_calls if fn is advance_backfill_cursor_activity)
    # The activity owns how far the walk got; the workflow must not recompute it from the batch.
    assert (advance.new_cursor_end_time, advance.new_cursor_session_id) == (cursor, "sess-b")
    assert (advance.dispatched_delta, advance.skipped_delta) == (2, 3)
    # More work below the cursor must not read as a drained window.
    assert not advance.exhausted


@pytest.mark.asyncio
async def test_drained_window_advances_then_deletes_its_own_schedule() -> None:
    mocks = _BackfillMocks(
        activity_results={
            prepare_backfill_tick_activity: PrepareBackfillTickOutput(
                action=BackfillTickAction.DISPATCH, dispatch_budget=5
            ),
            find_backfill_candidates_activity: FindBackfillCandidatesOutput(
                candidates=[], more_work_below_cursor=False
            ),
            advance_backfill_cursor_activity: AdvanceBackfillCursorOutput(finished=True),
        }
    )

    await _run_backfill_tick(mocks)

    assert mocks.child_calls == []
    assert _called(mocks) == [
        prepare_backfill_tick_activity,
        find_backfill_candidates_activity,
        advance_backfill_cursor_activity,
        delete_backfill_schedule_activity,
    ]
    advance = next(call for fn, call in mocks.activity_calls if fn is advance_backfill_cursor_activity)
    assert advance.exhausted


@pytest.mark.asyncio
async def test_child_already_started_by_the_live_sweep_does_not_fail_the_tick() -> None:
    cursor = dt.datetime(2026, 4, 30, tzinfo=dt.UTC)
    inputs = _backfill_tick_inputs()
    collided = build_apply_scanner_workflow_id(inputs.scanner_id, "sess-a")
    mocks = _BackfillMocks(
        activity_results={
            prepare_backfill_tick_activity: PrepareBackfillTickOutput(
                action=BackfillTickAction.DISPATCH, dispatch_budget=2
            ),
            find_backfill_candidates_activity: FindBackfillCandidatesOutput(
                candidates=[
                    CandidateSessionPayload(session_id="sess-a", session_end=cursor),
                    CandidateSessionPayload(session_id="sess-b", session_end=cursor),
                ],
                next_cursor_end_time=cursor,
                next_cursor_session_id="sess-b",
                more_work_below_cursor=True,
            ),
        },
        # Deterministic ids mean a session the live sweep is already applying collides here by design.
        child_errors_for_ids={collided: WorkflowAlreadyStartedError(collided, APPLY_SCANNER_WORKFLOW_NAME)},
    )

    await _run_backfill_tick(mocks, inputs)

    assert advance_backfill_cursor_activity in _called(mocks)
