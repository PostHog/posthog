import uuid
import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.queries.scanner_candidate_query import (
    DEFAULT_CANDIDATE_LIMIT,
    SWEEP_EVENTS_LOOKBACK,
    CandidateSession,
)
from products.replay_vision.backend.temporal import SweepScannerWorkflow
from products.replay_vision.backend.temporal.activities.advance_scanner_watermark import (
    advance_scanner_watermark_activity,
)
from products.replay_vision.backend.temporal.activities.count_in_flight_applies import (
    count_in_flight_applies_activity,
    count_in_flight_by_team_activity,
)
from products.replay_vision.backend.temporal.activities.find_scanner_candidates import find_scanner_candidates_activity
from products.replay_vision.backend.temporal.activities.refresh_prompt_suggestion import (
    refresh_prompt_suggestion_activity,
)
from products.replay_vision.backend.temporal.constants import (
    MAX_IN_FLIGHT_APPLIES_PER_SCANNER,
    MAX_IN_FLIGHT_APPLIES_PER_TEAM,
    build_process_vision_action_workflow_id,
)
from products.replay_vision.backend.temporal.sweep_types import (
    AdvanceScannerWatermarkInputs,
    CandidateSessionPayload,
    FindScannerCandidatesInputs,
    FindScannerCandidatesOutput,
    InFlightApplyCounts,
    SweepScannerInputs,
)
from products.replay_vision.backend.temporal.vision_actions.activities import evaluate_due_vision_actions_activity
from products.replay_vision.backend.temporal.vision_actions.types import DueVisionAction


def _make_scanner(**overrides) -> ReplayScanner:
    org = Organization.objects.create(name="vision-sweep-test-org")
    team = Team.objects.create(organization=org, name="vision-sweep-test-team")
    defaults: dict[str, Any] = {
        "team": team,
        "name": "sweep-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_6_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


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

    def test_proceeds_when_created_by_is_null(self) -> None:
        scanner = _make_scanner(created_by=None)
        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
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

    def test_threads_last_seen_session_id_when_set(self) -> None:
        scanner = _make_scanner(last_seen_session_id="prev-id")

        with patch(
            "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
        ) as MockQuery:
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
            MockQuery.return_value.run.return_value = candidates
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert result.saturated is True
        assert len(result.candidates) == DEFAULT_CANDIDATE_LIMIT

    def test_first_sweep_initializes_deep_watermark_without_catchup_query(self) -> None:
        scanner = _make_scanner()
        assert scanner.last_deep_swept_at is None

        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockQuery,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.BackfillCandidateQuery"
            ) as MockDeep,
        ):
            MockQuery.return_value.run.return_value = []
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        MockDeep.assert_not_called()
        assert result.deep_candidates == []
        assert result.deep_swept_through == scanner.last_swept_at

    def test_stale_deep_watermark_runs_full_width_catchup(self) -> None:
        deep_watermark = dt.datetime.now(dt.UTC) - dt.timedelta(hours=7)
        scanner = _make_scanner(last_deep_swept_at=deep_watermark)
        straggler = CandidateSession(
            session_id="deep-sess", session_end=dt.datetime(2026, 5, 1, 6, 0, 0, tzinfo=dt.UTC)
        )

        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockQuery,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.BackfillCandidateQuery"
            ) as MockDeep,
        ):
            MockQuery.return_value.run.return_value = []
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
            ("fresh_watermark_skips", dt.timedelta(hours=1), False),
            ("stale_watermark_runs", dt.timedelta(hours=7), True),
        ]
    )
    def test_deep_pass_gated_on_watermark_age(self, _name: str, watermark_age: dt.timedelta, expect_run: bool) -> None:
        scanner = _make_scanner(last_deep_swept_at=dt.datetime.now(dt.UTC) - watermark_age)
        straggler = CandidateSession(session_id="deep-a", session_end=dt.datetime(2026, 5, 1, 6, 0, tzinfo=dt.UTC))

        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockQuery,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.BackfillCandidateQuery"
            ) as MockDeep,
        ):
            MockQuery.return_value.run.return_value = []
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
        assert scanner.last_deep_swept_at is None
        fast = [
            CandidateSession(session_id=f"sess-{i}", session_end=dt.datetime(2026, 5, 1, 10, 0, i, tzinfo=dt.UTC))
            for i in range(2)
        ]

        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockQuery,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.BackfillCandidateQuery"
            ) as MockDeep,
        ):
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
        scanner = _make_scanner(last_deep_swept_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=7))
        fast = [
            CandidateSession(session_id=f"sess-{i}", session_end=dt.datetime(2026, 5, 1, 10, 0, i, tzinfo=dt.UTC))
            for i in range(fast_count)
        ]

        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockQuery,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.BackfillCandidateQuery"
            ) as MockDeep,
        ):
            MockQuery.return_value.run.return_value = fast
            MockDeep.return_value.run.return_value = []
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
        scanner = _make_scanner(last_deep_swept_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=7))
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

        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockQuery,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.BackfillCandidateQuery"
            ) as MockDeep,
        ):
            MockQuery.return_value.run.return_value = []
            MockDeep.return_value.run.return_value = []
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id, candidate_limit=5)
            )

        excluded = MockDeep.call_args.kwargs["exclude_session_ids"]
        assert sorted(excluded) == ["failed-sess", "ok-sess"]
        # The ingested event is no longer consulted, so it cannot suppress a candidate either.
        assert "exclude_observed_by_scanner" not in MockDeep.call_args.kwargs

    def test_truncated_deep_batch_holds_watermark(self) -> None:
        scanner = _make_scanner(last_deep_swept_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=7))
        stragglers = [
            CandidateSession(session_id=f"deep-{i}", session_end=dt.datetime(2026, 5, 1, 6, 0, i, tzinfo=dt.UTC))
            for i in range(3)
        ]

        with (
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.ScannerCandidateQuery"
            ) as MockQuery,
            patch(
                "products.replay_vision.backend.temporal.activities.find_scanner_candidates.BackfillCandidateQuery"
            ) as MockDeep,
        ):
            MockQuery.return_value.run.return_value = []
            MockDeep.return_value.run.return_value = stragglers
            result = find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id, candidate_limit=3)
            )

        assert [c.session_id for c in result.deep_candidates] == ["deep-0", "deep-1", "deep-2"]
        # The walk is newest-first, so advancing on a truncated batch would drop the oldest for good.
        assert result.deep_swept_through is None

    def test_raises_non_retryable_on_malformed_query(self) -> None:
        scanner = _make_scanner()
        scanner.query = {"kind": "TrendsQuery"}
        scanner.save(update_fields=["query"])

        with pytest.raises(ApplicationError) as exc_info:
            find_scanner_candidates_activity(
                FindScannerCandidatesInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )
        assert exc_info.value.non_retryable is True


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
        scanner = _make_scanner(last_deep_swept_at=existing_deep)
        new_deep = dt.datetime(2026, 5, 1, 11, 0, 0, tzinfo=dt.UTC)

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC),
                new_last_seen_session_id="",
            )
        )
        scanner.refresh_from_db()
        assert scanner.last_deep_swept_at == existing_deep

        advance_scanner_watermark_activity(
            AdvanceScannerWatermarkInputs(
                scanner_id=scanner.id,
                new_last_swept_at=dt.datetime(2026, 5, 1, 12, 5, 0, tzinfo=dt.UTC),
                new_last_seen_session_id="",
                new_last_deep_swept_at=new_deep,
            )
        )
        scanner.refresh_from_db()
        assert scanner.last_deep_swept_at == new_deep

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
        return self.activity_results.get(activity_fn)

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
        (InFlightApplyCounts(scanner=MAX_IN_FLIGHT_APPLIES_PER_SCANNER - 10, team=0), 10),  # partial scanner headroom
        (
            # Team headroom smaller than scanner headroom → team cap binds the fetch.
            InFlightApplyCounts(scanner=0, team=MAX_IN_FLIGHT_APPLIES_PER_TEAM - 5),
            5,
        ),
        (InFlightApplyCounts(scanner=0, team=0), MAX_IN_FLIGHT_APPLIES_PER_SCANNER),  # idle → full headroom
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
            count_in_flight_by_team_activity,
        ]
        assert mocks.child_calls == []
    else:
        assert find_calls[0].candidate_limit == expected_candidate_limit


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
    # Dispatch happens before the session scan, so the children start even with no candidates.
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
