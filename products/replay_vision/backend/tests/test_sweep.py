import uuid
import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.models import Organization, Team
from posthog.redis import get_client
from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import (
    STUCK_SESSION_THRESHOLD,
    _stuck_key,
)

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.models.replay_scanner_backfill import ReplayScannerBackfill
from products.replay_vision.backend.queries import excluded_sessions
from products.replay_vision.backend.queries.scanner_candidate_query import (
    DEFAULT_CANDIDATE_LIMIT,
    SWEEP_EVENTS_LOOKBACK,
    CandidateBatch,
    CandidateSession,
    build_candidate_batch,
)
from products.replay_vision.backend.temporal import SweepScannerWorkflow
from products.replay_vision.backend.temporal.activities.advance_scanner_watermark import (
    advance_scanner_watermark_activity,
)
from products.replay_vision.backend.temporal.activities.check_scanner_budget import check_scanner_budget_activity
from products.replay_vision.backend.temporal.activities.count_in_flight_applies import (
    count_in_flight_applies_activity,
    count_in_flight_by_team_activity,
)
from products.replay_vision.backend.temporal.activities.find_scanner_candidates import find_scanner_candidates_activity
from products.replay_vision.backend.temporal.activities.refresh_prompt_suggestion import (
    refresh_prompt_suggestion_activity,
)
from products.replay_vision.backend.temporal.constants import (
    DEEP_SPEND_WINDOW_DAYS,
    DEEP_SWEEP_INTERVAL,
    DEEP_SWEEP_MAX_WINDOW,
    DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY,
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
    ON_DEMAND_RESERVED_SCANNER_SLOTS,
    ON_DEMAND_RESERVED_TEAM_SLOTS,
    PRIMING_LOOKBACK,
    PRIMING_SCAN_SESSIONS,
    SWEEP_READ_BUDGET_BYTES_24H,
    build_process_vision_action_workflow_id,
)
from products.replay_vision.backend.temporal.snapshots import BackfillScannerSnapshot
from products.replay_vision.backend.temporal.sweep_types import (
    AdvanceScannerWatermarkInputs,
    CandidateSessionPayload,
    CheckScannerBudgetInputs,
    CheckScannerBudgetOutput,
    FindScannerCandidatesInputs,
    FindScannerCandidatesOutput,
    InFlightApplyCounts,
    SweepScannerInputs,
)
from products.replay_vision.backend.temporal.vision_actions.activities import evaluate_due_vision_actions_activity
from products.replay_vision.backend.temporal.vision_actions.types import DueVisionAction
from products.replay_vision.backend.tests.helpers import seed_scanner_spend, snapshot_for

# Every scanner built below runs on this model, so its price sets what one observation draws.
_OBSERVATION_CREDITS = observation_credits_for_model(ScannerModel.GEMINI_3_7_FLASH)


_ACTIVITY = "products.replay_vision.backend.temporal.activities.find_scanner_candidates"


def _wire_batch(mock_query: MagicMock) -> None:
    """Let tests keep expressing the fetched batch as `run.return_value`.

    The activity asks for a `CandidateBatch` now; building it from the same list keeps the old
    meaning (keyset at the last fetched row, saturated when the batch filled).
    """

    def run_batch(dispatch_limit: int, **_: object) -> CandidateBatch:
        fetched = mock_query.return_value.run() or []
        return build_candidate_batch(fetched, fetched, dispatch_limit, dispatch_limit)

    mock_query.return_value.run_batch.side_effect = run_batch


@contextmanager
def _patched_queries() -> Iterator[tuple[MagicMock, MagicMock]]:
    """Patch both candidate queries at the activity's import site, with an empty fast batch by default."""
    with (
        patch(f"{_ACTIVITY}.ScannerCandidateQuery") as MockQuery,
        patch(f"{_ACTIVITY}.WindowedCandidateQuery") as MockDeep,
    ):
        MockQuery.return_value.run.return_value = []
        MockQuery.return_value.matches_on_events.return_value = True
        MockDeep.return_value.run.return_value = []
        _wire_batch(MockQuery)
        yield MockQuery, MockDeep


_PAST_DEEP_INTERVAL = DEEP_SWEEP_INTERVAL + dt.timedelta(hours=1)
_WITHIN_DEEP_INTERVAL = DEEP_SWEEP_INTERVAL - dt.timedelta(hours=1)


def _make_scanner(**overrides) -> ReplayScanner:
    org = Organization.objects.create(name="vision-sweep-test-org")
    team = Team.objects.create(organization=org, name="vision-sweep-test-team")
    defaults: dict[str, Any] = {
        "team": team,
        "name": "sweep-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_7_FLASH,
        # Primed by default so only the priming-specific tests exercise the one-off pass.
        "primed_at": timezone.now(),
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


def _settle_edit_clock(scanner: ReplayScanner) -> None:
    """Make the scanner read as unedited since its last deep pass.

    Records an attempt one interval ago and backdates `updated_at` behind it, because the edit check
    compares those two. Queryset update, since `auto_now` would stamp `updated_at` back to now.
    """
    if scanner.deep_swept_through is None:
        return
    # The last pass ran when it last made progress, so a scanner far behind is still due at any factor.
    attempted = scanner.deep_swept_through
    ReplayScanner.objects.filter(pk=scanner.pk).update(
        deep_attempted_at=attempted,
        updated_at=attempted - dt.timedelta(minutes=1),
    )
    scanner.refresh_from_db()


def _seed_in_flight_observations(scanner: ReplayScanner, *, count: int) -> None:
    # Pending rows reserve credits live from their snapshot model. They settle no receipt until success.
    snapshot = snapshot_for(scanner)
    ReplayObservation.objects.bulk_create(
        ReplayObservation(
            scanner=scanner,
            team=scanner.team,
            session_id=f"in-flight-{i}",
            status=ObservationStatus.PENDING,
            scanner_snapshot=snapshot,
            triggered_by=ObservationTrigger.SCHEDULE,
        )
        for i in range(count)
    )


# find_scanner_candidates_activity


@pytest.mark.django_db(transaction=True)
class TestFindScannerCandidatesActivity:
    def test_returns_empty_when_scanner_missing(self) -> None:
        result = find_scanner_candidates_activity(FindScannerCandidatesInputs(scanner_id=uuid.uuid4(), team_id=999))
        assert result == FindScannerCandidatesOutput(candidates=[], saturated=False)

    def test_returns_empty_when_scanner_belongs_to_other_team(self) -> None:
        scanner = _make_scanner()
        result = find_scanner_candidates_activity(
            FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id + 1)
        )
        assert result == FindScannerCandidatesOutput(candidates=[], saturated=False)

    def test_returns_empty_when_scanner_is_disabled(self) -> None:
        scanner = _make_scanner(enabled=False)
        result = find_scanner_candidates_activity(
            FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
        )
        assert result == FindScannerCandidatesOutput(candidates=[], saturated=False)

    def test_returns_empty_when_creator_lost_session_recording_access(self) -> None:
        from posthog.models import User

        creator = User.objects.create_user(email="demoted@example.com", password="x", first_name="d")
        scanner = _make_scanner(created_by=creator)
        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.UserAccessControl.check_access_level_for_resource",
            return_value=False,
        ):
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )
        assert result == FindScannerCandidatesOutput(candidates=[], saturated=False)

    def test_targeted_scanner_with_no_creator_skips_instead_of_failing(self) -> None:
        # The exposure filter refuses userless principals, so a deleted creator would otherwise
        # raise out of the activity and fail every scheduled tick forever. The skip also keeps the
        # watermark still, so access restored later resumes from where scanning stopped.
        scanner = _make_scanner(created_by=None, experiment_targeting={"experiment_id": 12345})
        result = find_scanner_candidates_activity(
            FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
        )
        assert result == FindScannerCandidatesOutput(candidates=[], saturated=False)

    def test_proceeds_when_created_by_is_null(self) -> None:
        scanner = _make_scanner(created_by=None)
        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = []
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )
        assert result.saturated is False
        MockQuery.return_value.run.assert_called_once()

    def test_runs_candidate_query_and_returns_results(self) -> None:
        scanner = _make_scanner()
        watermark_arg = scanner.last_swept_at
        candidate_a = CandidateSession(
            session_id="sess-a", session_end=dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC)
        )
        candidate_b = CandidateSession(
            session_id="sess-b", session_end=dt.datetime(2026, 5, 1, 10, 5, 0, tzinfo=dt.UTC)
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = [candidate_a, candidate_b]
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert result.saturated is False
        assert [(c.session_id, c.session_end) for c in result.candidates] == [
            ("sess-a", candidate_a.session_end),
            ("sess-b", candidate_b.session_end),
        ]
        _, query_kwargs = MockQuery.call_args
        assert query_kwargs["last_swept_at"] == watermark_arg
        assert query_kwargs["last_seen_session_id"] is None
        assert query_kwargs["sampling_rate"] == scanner.sampling_rate
        assert query_kwargs["events_lookback"] == SWEEP_EVENTS_LOOKBACK

    def test_skips_sessions_quarantined_by_the_stuck_counter(self) -> None:
        # A session past the stuck threshold has burned two whole rasterizer retry envelopes;
        # dispatching it again wastes up to an hour of shared render capacity per sweep tick.
        scanner = _make_scanner()
        candidate_ok = CandidateSession(
            session_id="sess-ok", session_end=dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC)
        )
        candidate_stuck = CandidateSession(
            session_id="sess-stuck", session_end=dt.datetime(2026, 5, 1, 10, 5, 0, tzinfo=dt.UTC)
        )

        redis_client = get_client()
        for _ in range(STUCK_SESSION_THRESHOLD):
            redis_client.incr(_stuck_key(scanner.team_id, "sess-stuck"))

        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = [candidate_ok, candidate_stuck]
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert [c.session_id for c in result.candidates] == ["sess-ok"]

    def test_threads_last_seen_session_id_when_set(self) -> None:
        scanner = _make_scanner(last_seen_session_id="prev-id")

        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = []
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        _, query_kwargs = MockQuery.call_args
        assert query_kwargs["last_seen_session_id"] == "prev-id"

    def test_marks_saturated_when_at_candidate_limit(self) -> None:
        scanner = _make_scanner()
        candidates = [
            CandidateSession(
                session_id=f"sess-{i:04d}",
                session_end=dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC) + dt.timedelta(seconds=i),
            )
            for i in range(DEFAULT_CANDIDATE_LIMIT)
        ]

        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = candidates
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert result.saturated is True
        assert len(result.candidates) == DEFAULT_CANDIDATE_LIMIT

    @parameterized.expand(
        [
            # Nothing swept yet, so there is no range behind the watermark to catch up on.
            ("first_sweep", None, True),
            # Nothing the narrow events window could have cost this scanner, so nothing to catch up on.
            ("no_events_filters", _PAST_DEEP_INTERVAL, False),
        ]
    )
    def test_deep_pass_skipped_but_watermark_still_advances(
        self, _name: str, deep_watermark_age: dt.timedelta | None, matches_on_events: bool
    ) -> None:
        scanner = _make_scanner(
            deep_swept_through=None if deep_watermark_age is None else dt.datetime.now(dt.UTC) - deep_watermark_age
        )
        _settle_edit_clock(scanner)

        with _patched_queries() as (MockQuery, MockDeep):
            MockQuery.return_value.matches_on_events.return_value = matches_on_events
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        MockDeep.assert_not_called()
        assert result.deep_candidates == []
        # Parking the watermark instead would hand a later tick an arbitrarily wide catch-up window.
        assert result.deep_swept_through == scanner.last_swept_at

    @parameterized.expand(
        [
            # Spend on the deep pass stretches its interval, so 7h since the last pass is not yet due.
            ("deep_spend_stretches_interval", True, False),
            # The same spend attributed to the frequent sweep must not: reading the wrong bucket here
            # would throttle the deep pass on the fast pass's bill, and vice versa.
            ("fast_spend_does_not", False, True),
        ]
    )
    def test_deep_interval_stretches_on_deep_spend_only(
        self, _name: str, spend_is_deep: bool, expect_run: bool
    ) -> None:
        # Deep spend is priced as a daily rate over DEEP_SPEND_WINDOW_DAYS, so one bucket carries the
        # whole window: 32 budgets here is 4 budgets a day, capped to DEEP_SWEEP_MAX_FACTOR.
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        spend = {hour: DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY * 4 * DEEP_SPEND_WINDOW_DAYS}
        scanner = _make_scanner(
            deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL,
            deep_read_bytes_by_hour=spend if spend_is_deep else None,
            fast_read_bytes_by_hour=None if spend_is_deep else spend,
        )
        _settle_edit_clock(scanner)

        with (
            _patched_queries() as (MockQuery, MockDeep),
            # The frequent sweep's own throttle would otherwise skip the tick before the deep pass runs.
            patch(f"{_ACTIVITY}._throttled", return_value=False),
        ):
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert MockDeep.called is expect_run

    @parameterized.expand(
        [
            # Neither path finishes its window. Cadence used to be measured from the progress
            # watermark, so a pass that ended early cleared the gate again on the next tick with
            # headroom and skipped the stretch entirely, for exactly the scanners it exists to slow.
            ("saturated_batch", "saturate"),
            ("failed_query", "raise"),
        ]
    )
    def test_a_cut_short_pass_still_waits_out_the_interval(self, _name: str, mode: str) -> None:
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        # Spend stretches the interval to its cap, and the watermark starts further back than that so the
        # first tick is genuinely due.
        scanner = _make_scanner(
            deep_swept_through=dt.datetime.now(dt.UTC) - dt.timedelta(hours=72),
            deep_read_bytes_by_hour={hour: DEEP_SWEEP_READ_BUDGET_BYTES_PER_DAY * 4 * DEEP_SPEND_WINDOW_DAYS},
        )
        _settle_edit_clock(scanner)

        def run_tick() -> bool:
            with (
                _patched_queries() as (MockQuery, MockDeep),
                patch(f"{_ACTIVITY}._throttled", return_value=False),
            ):
                if mode == "raise":
                    MockDeep.return_value.run.side_effect = Exception("clickhouse timeout")
                else:
                    MockDeep.return_value.run.return_value = [
                        CandidateSession(session_id=f"deep-{i}", session_end=dt.datetime(2026, 5, 1, tzinfo=dt.UTC))
                        for i in range(DEFAULT_CANDIDATE_LIMIT)
                    ]
                find_scanner_candidates_activity(
                    FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
                )
                return bool(MockDeep.called)

        assert run_tick() is True
        scanner.refresh_from_db()
        # Stamped even when the query never returned, or a failing pass would retry every tick.
        assert scanner.deep_attempted_at is not None
        assert run_tick() is False

    def test_a_full_batch_resumes_instead_of_rewalking(self) -> None:
        # The walk is oldest-first, so everything below the last row is covered and the watermark can
        # move there. Re-walking from the window start instead would spend the whole next pass
        # re-finding rows it already dispatched, and a scanner that always fills up would never finish.
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL)
        _settle_edit_clock(scanner)
        stopped_at = dt.datetime(2026, 5, 1, 6, 0, tzinfo=dt.UTC)
        batch = [
            CandidateSession(session_id=f"deep-{i}", session_end=stopped_at) for i in range(DEFAULT_CANDIDATE_LIMIT)
        ]

        with _patched_queries() as (MockQuery, MockDeep):
            MockDeep.return_value.run.return_value = batch
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert result.deep_swept_through == stopped_at
        assert result.deep_keyset_session_id == batch[-1].session_id

    def test_one_pass_covers_at_most_the_window_cap(self) -> None:
        # A scanner far behind would otherwise open a window as wide as its backlog, which is both
        # slow and unbounded in cost, and a pass that cannot finish advances nothing at all.
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - dt.timedelta(days=30))
        _settle_edit_clock(scanner)

        with _patched_queries() as (MockQuery, MockDeep):
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        kwargs = MockDeep.call_args.kwargs
        assert kwargs["window_end"] == kwargs["window_start"] + DEEP_SWEEP_MAX_WINDOW
        assert kwargs["window_end"] < scanner.last_swept_at
        # Advanced by one cap, so the backlog drains over successive passes rather than in one query.
        assert result.deep_swept_through == kwargs["window_end"]

    def test_throttle_falls_back_to_the_total_bucket_before_the_meter_splits_it(self) -> None:
        # Every existing scanner has no fast bucket until the meter first runs. Reading only the new
        # field would show zero spend on deploy and un-throttle every throttled scanner for an hour.
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
        scanner = _make_scanner(
            sweep_read_bytes_by_hour={hour.isoformat(): 100 * SWEEP_READ_BUDGET_BYTES_24H},
            fast_read_bytes_by_hour=None,
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
            _wire_batch(MockQuery)
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        MockQuery.return_value.run.assert_not_called()

    def test_editing_the_scanner_drops_the_deep_cursor(self) -> None:
        # A cursor points partway into a window walked under the old filters. Reusing it after an edit
        # leaves everything below it in that window unvisited by the new ones.
        scanner = _make_scanner(
            deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL,
            deep_seen_session_id="stopped-here",
            deep_attempted_at=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL,
        )
        assert scanner.deep_attempted_at is not None and scanner.updated_at > scanner.deep_attempted_at

        with _patched_queries() as (MockQuery, MockDeep):
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert MockDeep.call_args.kwargs["cursor_session_id"] is None
        assert MockDeep.call_args.kwargs["cursor_end_time"] is None

    def test_no_deep_query_when_the_activity_has_no_time_left(self) -> None:
        # A sliver of budget buys a query certain to time out, and the cadence stamp goes with it,
        # which at a stretched factor costs a week of catch-up for nothing.
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL)
        _settle_edit_clock(scanner)
        before = scanner.deep_attempted_at

        with (
            _patched_queries() as (MockQuery, MockDeep),
            patch(f"{_ACTIVITY}._seconds_left", return_value=60.0),
        ):
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        MockDeep.assert_not_called()
        scanner.refresh_from_db()
        # Unmoved: a skipped pass must not spend the cadence, which at a stretched factor is a week.
        assert scanner.deep_attempted_at == before

    def test_an_unedited_scanner_keeps_its_cursor(self) -> None:
        # The mirror of dropping it. Comparing the edit time against the swept position instead of the
        # attempt time drops the cursor on every scanner whose watermark lags, which is all of them.
        # Past the interval, so the pass is actually due, with the edit older still.
        attempted = dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL
        scanner = _make_scanner(
            deep_swept_through=dt.datetime.now(dt.UTC) - dt.timedelta(days=20),
            deep_seen_session_id="stopped-here",
            deep_attempted_at=attempted,
        )
        ReplayScanner.objects.filter(pk=scanner.pk).update(updated_at=attempted - dt.timedelta(hours=1))

        with _patched_queries() as (MockQuery, MockDeep):
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert MockDeep.call_args.kwargs["cursor_session_id"] == "stopped-here"

    def test_deep_pass_failure_does_not_discard_the_fast_batch(self) -> None:
        # The fast pass has already paid for its reads by this point. Letting a catch-up failure fail
        # the activity throws those candidates away and Temporal re-runs the whole tick, reads included.
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL)
        _settle_edit_clock(scanner)
        fast = [CandidateSession(session_id="fast-1", session_end=dt.datetime(2026, 5, 1, 6, 0, tzinfo=dt.UTC))]

        with _patched_queries() as (MockQuery, MockDeep):
            MockQuery.return_value.run.return_value = fast
            MockDeep.return_value.run.side_effect = Exception("clickhouse timeout")
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert [c.session_id for c in result.candidates] == ["fast-1"]
        assert result.deep_candidates == []
        # Not advanced: the range behind the watermark still has not been walked.
        assert result.deep_swept_through is None

    def test_deep_pass_runs_once_more_after_the_query_loses_its_event_filters(self) -> None:
        # The range behind the watermark was swept under the old filters, with the fast pass's narrow
        # events window costing it candidates. Skipping on the new filters would strand them there:
        # the fast pass never looks back, so this is the only pass that revisits that range.
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL)
        assert scanner.deep_swept_through is not None

        with _patched_queries() as (MockQuery, MockDeep):
            MockQuery.return_value.matches_on_events.return_value = False
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        MockDeep.assert_called_once()

    def test_stale_deep_watermark_runs_full_width_catchup(self) -> None:
        deep_watermark = dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL
        scanner = _make_scanner(deep_swept_through=deep_watermark)
        straggler = CandidateSession(
            session_id="deep-sess", session_end=dt.datetime(2026, 5, 1, 6, 0, 0, tzinfo=dt.UTC)
        )

        with _patched_queries() as (MockQuery, MockDeep):
            MockDeep.return_value.run.return_value = [straggler]
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        _, deep_kwargs = MockDeep.call_args
        assert deep_kwargs["window_start"] == deep_watermark
        assert deep_kwargs["window_end"] == scanner.last_swept_at
        assert deep_kwargs["exclude_session_ids"] == []
        assert [c.session_id for c in result.deep_candidates] == ["deep-sess"]
        assert result.deep_swept_through == scanner.last_swept_at

    @parameterized.expand(
        [
            ("fresh_watermark_skips", _WITHIN_DEEP_INTERVAL, False),
            ("stale_watermark_runs", _PAST_DEEP_INTERVAL, True),
        ]
    )
    def test_deep_pass_gated_on_watermark_age(self, _name: str, watermark_age: dt.timedelta, expect_run: bool) -> None:
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - watermark_age)
        straggler = CandidateSession(session_id="deep-a", session_end=dt.datetime(2026, 5, 1, 6, 0, tzinfo=dt.UTC))

        with _patched_queries() as (MockQuery, MockDeep):
            MockDeep.return_value.run.return_value = [straggler]
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id, candidate_limit=5)
            )

        assert MockDeep.called is expect_run
        if not expect_run:
            assert result.deep_candidates == []
            assert result.deep_swept_through is None
            return
        assert [c.session_id for c in result.deep_candidates] == ["deep-a"]
        assert result.deep_swept_through == scanner.last_swept_at

    def test_deep_watermark_seeds_even_when_fast_batch_takes_all_headroom(self) -> None:
        scanner = _make_scanner()
        assert scanner.deep_swept_through is None
        fast = [
            CandidateSession(session_id=f"sess-{i}", session_end=dt.datetime(2026, 5, 1, 10, 0, i, tzinfo=dt.UTC))
            for i in range(2)
        ]

        with _patched_queries() as (MockQuery, MockDeep):
            MockQuery.return_value.run.return_value = fast
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id, candidate_limit=2)
            )

        MockDeep.assert_not_called()
        # Without this the fast watermark keeps advancing while the deep clock stays unset, and the
        # range in between never gets a full-width pass.
        assert result.deep_swept_through == scanner.last_swept_at

    @parameterized.expand(
        [
            ("headroom_left_over", 3, 5, 2),
            ("fast_batch_took_it_all", 5, 5, None),
        ]
    )
    def test_deep_pass_limited_to_headroom_left_by_fast_pass(
        self, _name: str, fast_count: int, limit: int, expected_deep_limit: int | None
    ) -> None:
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL)
        fast = [
            CandidateSession(session_id=f"sess-{i}", session_end=dt.datetime(2026, 5, 1, 10, 0, i, tzinfo=dt.UTC))
            for i in range(fast_count)
        ]

        with _patched_queries() as (MockQuery, MockDeep):
            MockQuery.return_value.run.return_value = fast
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id, candidate_limit=limit)
            )

        if expected_deep_limit is None:
            MockDeep.assert_not_called()
            return
        # Both lists dispatch together, so exceeding this would put the tick over the in-flight caps.
        assert MockDeep.call_args.kwargs["candidate_limit"] == expected_deep_limit

    def test_deep_pass_excludes_sessions_with_terminal_observations(self) -> None:
        # The $recording_observed event only lands on success, so excluding on it would hand these
        # sessions back on every tick and the walk would never move past them.
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL)
        for session_id, status in (("failed-sess", ObservationStatus.FAILED), ("ok-sess", ObservationStatus.SUCCEEDED)):
            ReplayObservation.objects.create(
                scanner=scanner,
                team=scanner.team,
                session_id=session_id,
                status=status,
                scanner_snapshot={"model": scanner.model},
                triggered_by=ObservationTrigger.SCHEDULE,
                completed_at=dt.datetime.now(dt.UTC),
            )

        with _patched_queries() as (MockQuery, MockDeep):
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id, candidate_limit=5)
            )

        excluded = MockDeep.call_args.kwargs["exclude_session_ids"]
        assert sorted(excluded) == ["failed-sess", "ok-sess"]
        # The ingested event is no longer consulted, so it cannot suppress a candidate either.
        assert "exclude_observed_by_scanner" not in MockDeep.call_args.kwargs

    def test_truncated_exclusions_do_not_redispatch_observed_sessions(self) -> None:
        # Past the exclusion cap the in-query blocklist is incomplete, so observed sessions come back
        # from the walk; dispatching them again would burn shared headroom on rows the unique
        # constraint then rejects.
        scanner = _make_scanner(deep_swept_through=dt.datetime.now(dt.UTC) - _PAST_DEEP_INTERVAL)
        _settle_edit_clock(scanner)
        for session_id in ("seen-1", "seen-2"):
            ReplayObservation.objects.create(
                scanner=scanner,
                team=scanner.team,
                session_id=session_id,
                status=ObservationStatus.SUCCEEDED,
                scanner_snapshot={"model": scanner.model},
                triggered_by=ObservationTrigger.SCHEDULE,
                completed_at=dt.datetime.now(dt.UTC),
            )
        batch = [
            CandidateSession(session_id="seen-2", session_end=dt.datetime(2026, 5, 1, 6, 0, tzinfo=dt.UTC)),
            CandidateSession(session_id="fresh", session_end=dt.datetime(2026, 5, 1, 7, 0, tzinfo=dt.UTC)),
        ]

        with _patched_queries() as (MockQuery, MockDeep):
            MockDeep.return_value.run.return_value = batch
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert [c.session_id for c in result.deep_candidates] == ["fresh"]
        # The filtered rows still count as covered ground, so the walk moves past them.
        assert result.deep_swept_through is not None

    @parameterized.expand(
        [
            # Default watermark sits one settle-interval back, i.e. the last sweep just ran.
            ("over_budget_recent_sweep_skips", None, dt.timedelta(0), False),
            # Enough watermark lag accumulated (>= 12 x 5 min at the factor cap): the sweep runs and batches it.
            ("over_budget_stale_watermark_runs", None, dt.timedelta(minutes=61), True),
            ("override_disables_throttle", 1, dt.timedelta(0), True),
        ]
    )
    def test_read_budget_throttle(
        self, _name: str, override: int | None, extra_watermark_lag: dt.timedelta, expect_query: bool
    ) -> None:
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
        scanner = _make_scanner(
            fast_read_bytes_by_hour={hour.isoformat(): 100 * SWEEP_READ_BUDGET_BYTES_24H},
            sweep_throttle_factor_override=override,
        )
        if extra_watermark_lag:
            scanner.last_swept_at = scanner.last_swept_at - extra_watermark_lag
            scanner.save(update_fields=["last_swept_at"])

        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = []
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert MockQuery.called is expect_query
        if not expect_query:
            # No horizon means the workflow can't advance the watermark, so the skipped range stays covered.
            assert result.swept_through is None
            assert result.candidates == []

    _NEGATIVE_QUERY = {
        "kind": "RecordingsQuery",
        "properties": [{"key": "$host", "value": ["internal.example.com"], "operator": "is_not", "type": "event"}],
    }

    def test_fully_excluded_batch_still_advances_the_keyset(self) -> None:
        # Falling back to the last surviving candidate would leave the keyset where it was and refetch
        # the same excluded rows forever.
        scanner = _make_scanner(query=self._NEGATIVE_QUERY)
        fetched = [CandidateSession(session_id="blocked", session_end=dt.datetime(2026, 5, 1, 10, 0, tzinfo=dt.UTC))]

        with (
            patch(f"{_ACTIVITY}.ScannerCandidateQuery") as MockQuery,
            patch.object(excluded_sessions, "excluded_session_ids", return_value={"blocked"}),
        ):
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = fetched
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert MockQuery.call_args.kwargs["skip_negative_blocklists"] is True
        assert result.candidates == []
        assert result.keyset_session_id == "blocked"
        assert result.keyset_end == fetched[0].session_end

    def test_exclusion_failure_fails_the_tick_rather_than_dispatching(self) -> None:
        # The in-query blocklists are off by this point, so swallowing this would dispatch unfiltered.
        scanner = _make_scanner(query=self._NEGATIVE_QUERY)

        with (
            patch(f"{_ACTIVITY}.ScannerCandidateQuery") as MockQuery,
            patch.object(excluded_sessions, "excluded_session_ids", side_effect=RuntimeError("clickhouse down")),
        ):
            _wire_batch(MockQuery)
            MockQuery.return_value.run.return_value = [
                CandidateSession(session_id="sess-a", session_end=dt.datetime(2026, 5, 1, 10, 0, tzinfo=dt.UTC))
            ]
            with pytest.raises(RuntimeError):
                find_scanner_candidates_activity(
                    FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
                )

    def test_raises_non_retryable_on_malformed_query(self) -> None:
        scanner = _make_scanner()
        scanner.query = {"kind": "TrendsQuery"}
        scanner.save(update_fields=["query"])

        with pytest.raises(ApplicationError) as exc_info:
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )
        assert exc_info.value.non_retryable is True

    def test_priming_pass_runs_once_for_a_never_swept_scanner(self) -> None:
        scanner = _make_scanner(primed_at=None)
        primed = [
            CandidateSession(session_id="prime-a", session_end=dt.datetime(2026, 5, 1, 9, 0, tzinfo=dt.UTC)),
            CandidateSession(session_id="prime-b", session_end=dt.datetime(2026, 5, 1, 8, 0, tzinfo=dt.UTC)),
        ]
        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockFast,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.WindowedCandidateQuery"
            ) as MockWindowed,
        ):
            _wire_batch(MockFast)
            MockFast.return_value.run.return_value = []
            MockWindowed.return_value.run.return_value = primed
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert [c.session_id for c in result.priming_candidates] == ["prime-a", "prime-b"]
        windowed_kwargs = MockWindowed.call_args.kwargs
        # Priming ignores the scanner's sampling rate (examples now) and stays behind the fast walk.
        assert windowed_kwargs["sampling_rate"] == 1.0
        assert windowed_kwargs["candidate_limit"] == PRIMING_SCAN_SESSIONS
        assert windowed_kwargs["window_end"] == scanner.last_swept_at
        scanner.refresh_from_db()
        assert scanner.primed_at is not None

        # One-shot: the next tick must not prime again.
        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockFast,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.WindowedCandidateQuery"
            ) as MockWindowed,
        ):
            _wire_batch(MockFast)
            MockFast.return_value.run.return_value = []
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )
        assert result.priming_candidates == []
        MockWindowed.assert_not_called()

    def test_priming_defers_when_the_fast_batch_spends_the_whole_headroom(self) -> None:
        # Priming shares the tick's in-flight budget; without headroom it must wait for a later tick
        # (and stay armed), never dispatch past the caps.
        scanner = _make_scanner(primed_at=None)
        fast = [
            CandidateSession(session_id=f"sess-{i}", session_end=dt.datetime(2026, 5, 1, 10, i, tzinfo=dt.UTC))
            for i in range(2)
        ]
        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockFast,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.WindowedCandidateQuery"
            ) as MockWindowed,
        ):
            _wire_batch(MockFast)
            MockFast.return_value.run.return_value = fast
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id, candidate_limit=2)
            )
        assert result.priming_candidates == []
        MockWindowed.assert_not_called()
        scanner.refresh_from_db()
        assert scanner.primed_at is None

    def test_priming_skipped_but_marked_when_watermark_covers_the_window(self) -> None:
        # A scanner that sat unswept for over the priming lookback has nothing behind the fast walk to
        # prime from; the pass must still be marked done so it never re-arms.
        scanner = _make_scanner(primed_at=None, last_swept_at=timezone.now() - PRIMING_LOOKBACK * 2)
        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockFast,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.WindowedCandidateQuery"
            ) as MockWindowed,
        ):
            _wire_batch(MockFast)
            MockFast.return_value.run.return_value = []
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )
        assert result.priming_candidates == []
        MockWindowed.assert_not_called()
        scanner.refresh_from_db()
        assert scanner.primed_at is not None


# advance_scanner_watermark_activity


@pytest.mark.django_db(transaction=True)
class TestAdvanceScannerWatermarkActivity:
    def test_updates_watermark_and_last_seen(self) -> None:
        scanner = _make_scanner()
        new_watermark = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=new_watermark,
                new_last_seen_session_id="last-id",
            )
        )

        scanner.refresh_from_db()
        assert scanner.last_swept_at == new_watermark
        assert scanner.last_seen_session_id == "last-id"

    def test_a_full_save_does_not_clobber_metered_spend(self) -> None:
        # The API saves the whole row on edit. A PATCH landing while the meter writes would restore
        # stale buckets, and the scanner would run its expensive queries at a lower throttle factor.
        hour = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0).isoformat()
        scanner = _make_scanner()
        metered = {hour: SWEEP_READ_BUDGET_BYTES_24H * 9}
        ReplayScanner.objects.filter(pk=scanner.pk).update(
            fast_read_bytes_by_hour=metered, deep_read_bytes_by_hour=metered, sweep_read_bytes_by_hour=metered
        )

        stale = ReplayScanner.objects.get(pk=scanner.pk)
        stale.fast_read_bytes_by_hour = None
        stale.deep_read_bytes_by_hour = None
        stale.sweep_read_bytes_by_hour = None
        stale.name = "renamed"
        stale.save()

        reloaded = ReplayScanner.objects.get(pk=scanner.pk)
        assert reloaded.fast_read_bytes_by_hour == metered
        assert reloaded.deep_read_bytes_by_hour == metered
        assert reloaded.sweep_read_bytes_by_hour == metered

    def test_progress_write_keeps_the_attempt_stamp(self) -> None:
        # The stamp and the progress are written at different points in one tick. A whole-object write
        # by the second drops the first, and cadence goes back to being measured from progress.
        now = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)
        stamped = now - dt.timedelta(minutes=3)
        scanner = _make_scanner(deep_swept_through=now - dt.timedelta(days=1))
        ReplayScanner.objects.filter(pk=scanner.pk).update(deep_attempted_at=stamped)

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=now,
                new_last_seen_session_id="",
                new_last_deep_swept_at=now,
                new_last_deep_seen_session_id="resume-here",
            )
        )

        scanner.refresh_from_db()
        assert scanner.deep_swept_through == now
        assert scanner.deep_seen_session_id == "resume-here"
        assert scanner.deep_attempted_at == stamped

    def test_clears_last_seen_with_empty_string(self) -> None:
        scanner = _make_scanner(last_seen_session_id="stale-id")
        new_watermark = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=new_watermark,
                new_last_seen_session_id="",
            )
        )

        scanner.refresh_from_db()
        assert scanner.last_seen_session_id == ""

    def test_advances_deep_watermark_only_when_provided(self) -> None:
        existing_deep = dt.datetime(2026, 5, 1, 6, 0, 0, tzinfo=dt.UTC)
        scanner = _make_scanner(deep_swept_through=existing_deep)
        new_deep = dt.datetime(2026, 5, 1, 11, 0, 0, tzinfo=dt.UTC)

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC),
                new_last_seen_session_id="",
            )
        )
        scanner.refresh_from_db()
        assert scanner.deep_swept_through == existing_deep

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=dt.datetime(2026, 5, 1, 12, 5, 0, tzinfo=dt.UTC),
                new_last_seen_session_id="",
                new_last_deep_swept_at=new_deep,
            )
        )
        scanner.refresh_from_db()
        assert scanner.deep_swept_through == new_deep

    def test_no_op_when_scanner_deleted(self) -> None:
        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=uuid.uuid4(),
                new_last_swept_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
                new_last_seen_session_id="",
            )
        )

    def test_does_not_bump_scanner_version(self) -> None:
        scanner = _make_scanner()
        original_version = scanner.scanner_version

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC),
                new_last_seen_session_id="x",
            )
        )

        scanner.refresh_from_db()
        assert scanner.scanner_version == original_version


# check_scanner_budget_activity


@pytest.mark.parametrize(
    "limit, spent_observations, expect_capped",
    [
        (None, 0, False),
        # No limit set, and heavy spend: never capped, watermark never touched.
        (None, 100, False),
        (20 * _OBSERVATION_CREDITS, 0, False),
        (20 * _OBSERVATION_CREDITS, 10, False),
        # Exactly one observation's worth of room left.
        (20 * _OBSERVATION_CREDITS, 19, False),
        # Credits left, but not enough for one more observation.
        (20 * _OBSERVATION_CREDITS - 1, 19, True),
        (20 * _OBSERVATION_CREDITS, 20, True),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_check_scanner_budget_activity_caps_and_advances_the_watermark(
    limit: int | None, spent_observations: int, expect_capped: bool
) -> None:
    scanner = _make_scanner(credit_limit=limit)
    stale = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    ReplayScanner.objects.filter(pk=scanner.pk).update(
        last_swept_at=stale,
        last_seen_session_id="sess-old",
        deep_swept_through=stale,
    )
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=spent_observations)

    output = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    scanner.refresh_from_db()
    assert output.capped is expect_capped
    if expect_capped:
        # Skip the capped window rather than backfilling (and billing) it when the limit frees up.
        assert scanner.last_swept_at > stale
        assert scanner.last_seen_session_id == ""
        # The deep pass walks from its own watermark up to the fast one, so a stale value would hand the
        # first uncapped deep sweep exactly the window this reset skips.
        assert scanner.deep_swept_through == scanner.last_swept_at
    else:
        assert scanner.last_swept_at == stale
        assert scanner.last_seen_session_id == "sess-old"
        assert scanner.deep_swept_through == stale


@pytest.mark.django_db(transaction=True)
def test_check_scanner_budget_activity_capped_by_in_flight_alone_does_not_advance_the_watermark() -> None:
    # Only adding in-flight reservations pushes this over the limit: a transient spike must skip
    # the tick without burning the permanent watermark advance.
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    stale = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    ReplayScanner.objects.filter(pk=scanner.pk).update(
        last_swept_at=stale,
        last_seen_session_id="sess-old",
        deep_swept_through=stale,
    )
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=10)
    _seed_in_flight_observations(scanner, count=10)

    output = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    scanner.refresh_from_db()
    assert output.capped is True
    assert scanner.last_swept_at == stale
    assert scanner.last_seen_session_id == "sess-old"
    assert scanner.deep_swept_through == stale


@pytest.mark.django_db(transaction=True)
def test_check_scanner_budget_activity_capped_by_in_flight_alone_does_not_notify() -> None:
    # A transient in-flight-only cap may clear itself within minutes as reservations release;
    # notifying there could tell a user their scanner stopped when it's about to resume on its own.
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=10)
    _seed_in_flight_observations(scanner, count=10)

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        output = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    assert output.capped is True
    mock_notify.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_check_scanner_budget_activity_notifies_once_per_period_on_settled_exhaustion() -> None:
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        first = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))
        second = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    # The pause is not conditional on the notification: both calls still report capped.
    assert first.capped is True
    assert second.capped is True
    mock_notify.assert_called_once()
    scanner.refresh_from_db()
    assert scanner.limit_notified_period_start is not None


@pytest.mark.parametrize("has_running_backfill", [True, False])
@pytest.mark.django_db(transaction=True)
def test_limit_notification_mentions_a_running_backfill_only_when_there_is_one(has_running_backfill: bool) -> None:
    # The cap holds a running backfill without changing its status, so the notification is the one
    # place that can say why the backfill stalled; scanners without one must not get that line.
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)
    if has_running_backfill:
        ReplayScannerBackfill.objects.for_team(scanner.team_id).create(
            scanner=scanner,
            team=scanner.team,
            window_start=dt.datetime(2026, 4, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
            scanner_snapshot=BackfillScannerSnapshot.from_scanner(scanner).model_dump(mode="json"),
            credits_per_observation=_OBSERVATION_CREDITS,
            total_count=10,
        )

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    mock_notify.assert_called_once()
    body = mock_notify.call_args[0][0].body
    assert ("backfill is on hold" in body) is has_running_backfill


@pytest.mark.django_db(transaction=True)
def test_scanner_capped_last_period_is_uncapped_after_the_period_resets() -> None:
    # The cap is per billing period: a scanner that went dark last period resumes on the first
    # tick of the new one, still collecting into the same scanner.
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)
    last_period = dt.datetime.now(dt.UTC) - dt.timedelta(days=40)
    ReplayObservation.objects.filter(scanner=scanner).update(created_at=last_period)
    ReplayObservationUsage.objects.filter(scanner_id=scanner.id).update(observation_created_at=last_period)

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        output = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    assert output.capped is False
    mock_notify.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_check_scanner_budget_activity_notifies_again_after_period_rolls_over() -> None:
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)
    prior_period = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    ReplayScanner.objects.filter(pk=scanner.pk).update(limit_notified_period_start=prior_period)

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        output = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    assert output.capped is True
    mock_notify.assert_called_once()
    scanner.refresh_from_db()
    assert scanner.limit_notified_period_start is not None
    assert scanner.limit_notified_period_start > prior_period


@pytest.mark.django_db(transaction=True)
def test_limit_notification_excludes_users_denied_on_the_scanner() -> None:
    from posthog.constants import AvailableFeature
    from posthog.models import OrganizationMembership, User

    from products.notifications.backend.facade.enums import TargetType

    from ee.models.rbac.access_control import AccessControl

    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)
    organization = scanner.team.organization
    organization.available_product_features = [
        {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
    ]
    organization.save()
    allowed = User.objects.create_and_join(organization, "allowed@posthog.com", "testtest")
    denied = User.objects.create_and_join(organization, "denied@posthog.com", "testtest")
    AccessControl.objects.create(
        team=scanner.team,
        resource="replay_scanner",
        resource_id=str(scanner.id),
        access_level="none",
        organization_member=OrganizationMembership.objects.get(user=denied, organization=organization),
    )

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    mock_notify.assert_called_once()
    data = mock_notify.call_args[0][0]
    assert data.resource_type == "replay_scanner"
    assert data.resource_id == str(scanner.id)
    recipients = data.resolver.resolve(TargetType.TEAM, str(scanner.team_id), scanner.team_id)
    assert allowed.id in recipients
    assert denied.id not in recipients


@pytest.mark.django_db(transaction=True)
def test_limit_notification_is_delivered_end_to_end() -> None:
    # Everything real except the remote feature flag and Kafka: mock-only coverage let the
    # whole delivery path regress invisibly.
    from posthog.models import User

    from products.notifications.backend.models import NotificationEvent

    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)
    member = User.objects.create_and_join(scanner.team.organization, "member@posthog.com", "testtest")

    with (
        patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True),
        patch("products.notifications.backend.logic._publish_to_kafka"),
    ):
        output = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    assert output.capped is True
    event = NotificationEvent.objects.get(resource_type="replay_scanner", resource_id=str(scanner.id))
    assert member.id in event.resolved_user_ids
    assert event.source_url == f"/project/{scanner.team.project_id}/replay-vision/{scanner.id}"
    assert scanner.name in event.title


@pytest.mark.django_db(transaction=True)
def test_failed_send_returns_the_notification_to_the_next_tick() -> None:
    # A transient pipeline outage must delay the period's one notification, not consume it.
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)

    with patch(
        "products.notifications.backend.facade.api.create_notification", side_effect=RuntimeError("pipeline down")
    ):
        check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    scanner.refresh_from_db()
    assert scanner.limit_notified_period_start is None

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    mock_notify.assert_called_once()
    scanner.refresh_from_db()
    assert scanner.limit_notified_period_start is not None


@pytest.mark.django_db(transaction=True)
def test_raising_the_limit_rearms_the_notification_for_the_same_period() -> None:
    # Editing the limit clears the stamp (see the serializer), so hitting the raised limit later in
    # the same period notifies again instead of staying silent until the next period.
    limit = 20 * _OBSERVATION_CREDITS
    scanner = _make_scanner(credit_limit=limit)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))
    mock_notify.assert_called_once()

    # The user raises the limit; the serializer clears the stamp alongside.
    ReplayScanner.objects.filter(pk=scanner.pk).update(credit_limit=2 * limit, limit_notified_period_start=None)
    seed_scanner_spend(scanner, _OBSERVATION_CREDITS, observations=20)

    with patch("products.notifications.backend.facade.api.create_notification") as mock_notify:
        output = check_scanner_budget_activity(CheckScannerBudgetInputs(scanner_id=scanner.id, team_id=scanner.team_id))

    assert output.capped is True
    mock_notify.assert_called_once()


# SweepScannerWorkflow (mocked-Temporal)


class _SweepMocks:
    def __init__(
        self,
        *,
        activity_results: dict[Any, Any] | None = None,
        child_errors_for_ids: dict[str, Exception] | None = None,
    ) -> None:
        self.activity_results = activity_results or {}
        self.child_errors_for_ids = child_errors_for_ids or {}
        self.activity_calls: list[tuple[Any, Any]] = []
        self.child_calls: list[dict[str, Any]] = []

    async def execute_activity(self, activity_fn: Any, activity_input: Any, **_: Any) -> Any:
        self.activity_calls.append((activity_fn, activity_input))
        # Default to 0 in-flight (full headroom) unless a test overrides it.
        if activity_fn is count_in_flight_by_team_activity and activity_fn not in self.activity_results:
            return InFlightApplyCounts(scanner=0, team=0)
        # Default to no due vision actions unless a test overrides it.
        if activity_fn is evaluate_due_vision_actions_activity and activity_fn not in self.activity_results:
            return []
        # Default to not-capped so the budget gate leaves every other sweep test unaffected.
        if activity_fn is check_scanner_budget_activity and activity_fn not in self.activity_results:
            return CheckScannerBudgetOutput(capped=False)
        result = self.activity_results.get(activity_fn)
        if isinstance(result, Exception):
            raise result
        return result

    async def start_child_workflow(self, *args: Any, **kwargs: Any) -> Any:
        wid = kwargs.get("id")
        self.child_calls.append({"args": args, "kwargs": kwargs, "id": wid})
        if wid is not None and wid in self.child_errors_for_ids:
            raise self.child_errors_for_ids[wid]
        return MagicMock()


def _build_payload(session_id: str, ts: dt.datetime) -> CandidateSessionPayload:
    return CandidateSessionPayload(session_id=session_id, session_end=ts)


def _sweep_inputs() -> SweepScannerInputs:
    return SweepScannerInputs(scanner_id=uuid.uuid4(), team_id=42)


async def _run_sweep(mocks: _SweepMocks, inputs: SweepScannerInputs | None = None, patched: bool = True) -> None:
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
        # `workflow.patched` also needs the runtime; new executions take the patched branch.
        patch("temporalio.workflow.patched", return_value=patched),
        patch("temporalio.workflow.unsafe.is_replaying", return_value=False),
    ):
        await SweepScannerWorkflow().run(inputs or _sweep_inputs())


@pytest.mark.asyncio
async def test_empty_batch_skips_dispatch_and_advance() -> None:
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        }
    )

    await _run_sweep(mocks)

    assert [fn for fn, _ in mocks.activity_calls] == [
        evaluate_due_vision_actions_activity,
        refresh_prompt_suggestion_activity,
        check_scanner_budget_activity,
        count_in_flight_by_team_activity,
        find_scanner_candidates_activity,
    ]
    assert mocks.child_calls == []


@pytest.mark.asyncio
async def test_empty_batch_with_horizon_advances_watermark_without_dispatch() -> None:
    horizon = dt.datetime(2026, 8, 4, 12, 0, 0, tzinfo=dt.UTC)
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(
                candidates=[], saturated=False, swept_through=horizon
            ),
        }
    )

    await _run_sweep(mocks)

    assert mocks.child_calls == []
    advance_call = next(call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity)
    assert advance_call.new_last_swept_at == horizon
    assert advance_call.new_last_seen_session_id == ""


@pytest.mark.asyncio
async def test_non_saturated_batch_dispatches_and_clears_tiebreaker() -> None:
    candidates = [
        _build_payload("sess-a", dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC)),
        _build_payload("sess-b", dt.datetime(2026, 5, 1, 10, 5, 0, tzinfo=dt.UTC)),
    ]
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=candidates, saturated=False),
        }
    )
    inputs = _sweep_inputs()

    await _run_sweep(mocks, inputs)

    assert len(mocks.child_calls) == 2
    assert mocks.child_calls[0]["id"] == f"replay-vision-apply-scanner-{inputs.scanner_id}-sess-a"
    # Each child is stamped with the scanner id so the in-flight count can find it.
    child_attrs = mocks.child_calls[0]["kwargs"]["search_attributes"]
    assert any(p.key.name == "PostHogScannerId" and p.value == str(inputs.scanner_id) for p in child_attrs)
    advance_call = next(call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity)
    assert advance_call.new_last_swept_at == candidates[-1].session_end
    assert advance_call.new_last_seen_session_id == ""


@pytest.mark.asyncio
async def test_saturated_batch_carries_session_id_as_tiebreaker() -> None:
    candidates = [_build_payload(f"sess-{i:02d}", dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC)) for i in range(3)]
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=candidates, saturated=True),
        }
    )

    await _run_sweep(mocks)

    advance_call = next(call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity)
    assert advance_call.new_last_swept_at == candidates[-1].session_end
    assert advance_call.new_last_seen_session_id == "sess-02"


@pytest.mark.asyncio
async def test_deep_candidates_dispatch_alongside_fast_and_forward_deep_watermark() -> None:
    deep_horizon = dt.datetime(2026, 5, 1, 9, 0, 0, tzinfo=dt.UTC)
    fast = [_build_payload("sess-a", dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC))]
    deep = [_build_payload("deep-a", dt.datetime(2026, 5, 1, 4, 0, 0, tzinfo=dt.UTC))]
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(
                candidates=fast, saturated=False, deep_candidates=deep, deep_swept_through=deep_horizon
            ),
        }
    )
    inputs = _sweep_inputs()

    await _run_sweep(mocks, inputs)

    dispatched = {c["id"] for c in mocks.child_calls}
    assert dispatched == {
        f"replay-vision-apply-scanner-{inputs.scanner_id}-sess-a",
        f"replay-vision-apply-scanner-{inputs.scanner_id}-deep-a",
    }
    advance_call = next(call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity)
    # Deep candidates never drive the fast watermark — their session_end predates it.
    assert advance_call.new_last_swept_at == fast[-1].session_end
    assert advance_call.new_last_deep_swept_at == deep_horizon


@pytest.mark.asyncio
async def test_deep_candidates_dispatch_even_when_fast_batch_is_empty() -> None:
    horizon = dt.datetime(2026, 5, 1, 11, 0, 0, tzinfo=dt.UTC)
    deep_horizon = dt.datetime(2026, 5, 1, 9, 0, 0, tzinfo=dt.UTC)
    deep = [_build_payload("deep-a", dt.datetime(2026, 5, 1, 4, 0, 0, tzinfo=dt.UTC))]
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(
                candidates=[],
                saturated=False,
                swept_through=horizon,
                deep_candidates=deep,
                deep_swept_through=deep_horizon,
            ),
        }
    )
    inputs = _sweep_inputs()

    await _run_sweep(mocks, inputs)

    assert [c["id"] for c in mocks.child_calls] == [f"replay-vision-apply-scanner-{inputs.scanner_id}-deep-a"]
    advance_call = next(call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity)
    assert advance_call.new_last_swept_at == horizon
    assert advance_call.new_last_deep_swept_at == deep_horizon


@pytest.mark.asyncio
async def test_already_started_child_is_silently_skipped() -> None:
    candidates = [
        _build_payload("sess-a", dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC)),
        _build_payload("sess-b", dt.datetime(2026, 5, 1, 10, 5, 0, tzinfo=dt.UTC)),
    ]
    inputs = _sweep_inputs()
    already_started_id = f"replay-vision-apply-scanner-{inputs.scanner_id}-sess-a"
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=candidates, saturated=False),
        },
        child_errors_for_ids={
            already_started_id: WorkflowAlreadyStartedError(workflow_id=already_started_id, workflow_type="x"),
        },
    )

    await _run_sweep(mocks, inputs)

    advance_calls = [call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity]
    assert len(advance_calls) == 1


@pytest.mark.asyncio
async def test_child_start_failure_propagates_and_skips_advance() -> None:
    candidates = [_build_payload("sess-a", dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC))]
    inputs = _sweep_inputs()
    failed_id = f"replay-vision-apply-scanner-{inputs.scanner_id}-sess-a"
    mocks = _SweepMocks(
        activity_results={
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=candidates, saturated=False),
        },
        child_errors_for_ids={failed_id: RuntimeError("temporal outage")},
    )

    with pytest.raises(RuntimeError, match="temporal outage"):
        await _run_sweep(mocks, inputs)

    assert [call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity] == []


@pytest.mark.parametrize(
    "in_flight, expected_candidate_limit",
    [
        (InFlightApplyCounts(scanner=MAX_IN_FLIGHT_APPLIES_PER_SCANNER, team=0), None),  # scanner cap → throttled
        (InFlightApplyCounts(scanner=MAX_IN_FLIGHT_APPLIES_PER_SCANNER + 10, team=0), None),  # over → throttled
        (InFlightApplyCounts(scanner=0, team=MAX_IN_FLIGHT_APPLIES_PER_TEAM), None),  # team cap → throttled
        (
            # At the reserved scanner ceiling the sweep throttles even though on-demand still admits.
            InFlightApplyCounts(scanner=MAX_IN_FLIGHT_APPLIES_PER_SCANNER - ON_DEMAND_RESERVED_SCANNER_SLOTS, team=0),
            None,
        ),
        (
            # Same for the reserved team ceiling.
            InFlightApplyCounts(scanner=0, team=MAX_IN_FLIGHT_APPLIES_PER_TEAM - ON_DEMAND_RESERVED_TEAM_SLOTS),
            None,
        ),
        (
            # Partial scanner headroom below the reserved ceiling.
            InFlightApplyCounts(
                scanner=MAX_IN_FLIGHT_APPLIES_PER_SCANNER - ON_DEMAND_RESERVED_SCANNER_SLOTS - 10, team=0
            ),
            10,
        ),
        (
            # Team headroom smaller than scanner headroom → team cap binds the fetch.
            InFlightApplyCounts(scanner=0, team=MAX_IN_FLIGHT_APPLIES_PER_TEAM - ON_DEMAND_RESERVED_TEAM_SLOTS - 5),
            5,
        ),
        (
            # Idle → full scheduled headroom, i.e. the scanner cap minus the on-demand reserve.
            InFlightApplyCounts(scanner=0, team=0),
            MAX_IN_FLIGHT_APPLIES_PER_SCANNER - ON_DEMAND_RESERVED_SCANNER_SLOTS,
        ),
    ],
)
@pytest.mark.asyncio
async def test_inflight_cap_gates_the_sweep(
    in_flight: InFlightApplyCounts, expected_candidate_limit: int | None
) -> None:
    mocks = _SweepMocks(
        activity_results={
            count_in_flight_by_team_activity: in_flight,
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        },
    )

    await _run_sweep(mocks)

    find_calls = [inp for fn, inp in mocks.activity_calls if fn == find_scanner_candidates_activity]
    if expected_candidate_limit is None:
        # Throttled: vision-action eval still runs (it rides every sweep), but no find, no apply dispatch.
        assert [fn for fn, _ in mocks.activity_calls] == [
            evaluate_due_vision_actions_activity,
            refresh_prompt_suggestion_activity,
            check_scanner_budget_activity,
            count_in_flight_by_team_activity,
        ]
        assert mocks.child_calls == []
    else:
        assert find_calls[0].candidate_limit == expected_candidate_limit


@pytest.mark.asyncio
async def test_capped_scanner_skips_the_sweep_entirely() -> None:
    mocks = _SweepMocks(
        activity_results={
            check_scanner_budget_activity: CheckScannerBudgetOutput(capped=True),
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        },
    )

    await _run_sweep(mocks)

    called = [fn for fn, _ in mocks.activity_calls]
    # Capped means no session scans; the heartbeats spend no scanner credits, so they still run.
    assert evaluate_due_vision_actions_activity in called
    assert refresh_prompt_suggestion_activity in called
    assert find_scanner_candidates_activity not in called
    assert count_in_flight_by_team_activity not in called
    assert mocks.child_calls == []


@pytest.mark.asyncio
async def test_budget_check_failure_does_not_fail_the_sweep() -> None:
    # A rolling deploy can land the activity on a worker without it registered; the gate fails
    # open rather than erroring the whole sweep.
    mocks = _SweepMocks(
        activity_results={
            check_scanner_budget_activity: RuntimeError("activity type not registered"),
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        },
    )

    await _run_sweep(mocks)

    called = [fn for fn, _ in mocks.activity_calls]
    assert find_scanner_candidates_activity in called


@pytest.mark.asyncio
async def test_unpatched_sweep_replays_legacy_scanner_counter() -> None:
    # A sweep that started before the team-cap patch must replay the legacy scanner-only counter (its
    # recorded int result), never the team-aware activity that returns a different type; otherwise the
    # in-flight execution wedges on a deserialization mismatch across the deploy.
    mocks = _SweepMocks(
        activity_results={
            count_in_flight_applies_activity: 3,
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        },
    )

    await _run_sweep(mocks, patched=False)

    called = [fn for fn, _ in mocks.activity_calls]
    assert count_in_flight_applies_activity in called
    assert count_in_flight_by_team_activity not in called
    # The budget gate is patched too, so a pre-deploy sweep replays its history without it.
    assert check_scanner_budget_activity not in called
    find_calls = [inp for fn, inp in mocks.activity_calls if fn == find_scanner_candidates_activity]
    assert find_calls[0].candidate_limit == MAX_IN_FLIGHT_APPLIES_PER_SCANNER - 3


# SweepScannerWorkflow vision-action dispatch (the "and then…" trigger riding the sweep)


@pytest.mark.asyncio
async def test_sweep_dispatches_a_child_per_due_vision_action() -> None:
    due = [DueVisionAction(vision_action_id=uuid.uuid4(), team_id=42) for _ in range(2)]
    mocks = _SweepMocks(
        activity_results={
            evaluate_due_vision_actions_activity: due,
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        }
    )

    await _run_sweep(mocks)

    started = {call["id"] for call in mocks.child_calls}
    assert started == {build_process_vision_action_workflow_id(d.vision_action_id) for d in due}
    # Dispatch happens first, before the budget gate and the session scan, so the children
    # start even with no candidates.
    assert evaluate_due_vision_actions_activity == mocks.activity_calls[0][0]


@pytest.mark.asyncio
async def test_sweep_one_failed_vision_child_does_not_drop_the_others() -> None:
    # Each due action is already claimed independently, so one child failing to start must not abort
    # dispatch of the rest — the others still get fired this sweep.
    failing = DueVisionAction(vision_action_id=uuid.uuid4(), team_id=42)
    ok = DueVisionAction(vision_action_id=uuid.uuid4(), team_id=42)
    mocks = _SweepMocks(
        activity_results={
            evaluate_due_vision_actions_activity: [failing, ok],
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        },
        child_errors_for_ids={
            build_process_vision_action_workflow_id(failing.vision_action_id): RuntimeError("temporal blip")
        },
    )

    await _run_sweep(mocks)

    started = {call["id"] for call in mocks.child_calls}
    # Both were attempted; the healthy one's start is recorded despite the other failing.
    assert build_process_vision_action_workflow_id(ok.vision_action_id) in started


@pytest.mark.asyncio
async def test_sweep_vision_action_failure_does_not_block_session_scan() -> None:
    # A vision-action child that fails to start must not abort the scanner's core duty: the session
    # scan still runs and advances its watermark.
    d = DueVisionAction(vision_action_id=uuid.uuid4(), team_id=42)
    candidate = _build_payload("sess-a", dt.datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt.UTC))
    mocks = _SweepMocks(
        activity_results={
            evaluate_due_vision_actions_activity: [d],
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[candidate], saturated=False),
        },
        child_errors_for_ids={
            build_process_vision_action_workflow_id(d.vision_action_id): RuntimeError("temporal down")
        },
    )

    await _run_sweep(mocks)

    assert [call for fn, call in mocks.activity_calls if fn == advance_scanner_watermark_activity]


@pytest.mark.asyncio
async def test_sweep_swallows_already_running_vision_action() -> None:
    d = DueVisionAction(vision_action_id=uuid.uuid4(), team_id=42)
    vision_child_id = build_process_vision_action_workflow_id(d.vision_action_id)
    mocks = _SweepMocks(
        activity_results={
            evaluate_due_vision_actions_activity: [d],
            find_scanner_candidates_activity: FindScannerCandidatesOutput(candidates=[], saturated=False),
        },
        child_errors_for_ids={
            vision_child_id: WorkflowAlreadyStartedError(workflow_id=vision_child_id, workflow_type="x")
        },
    )

    # An already-running action is skipped, not a failure.
    await _run_sweep(mocks)
