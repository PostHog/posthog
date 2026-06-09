import uuid
import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.queries.scanner_candidate_query import DEFAULT_CANDIDATE_LIMIT, CandidateSession
from products.replay_vision.backend.temporal import SweepScannerWorkflow
from products.replay_vision.backend.temporal.activities.advance_scanner_watermark import (
    advance_scanner_watermark_activity,
)
from products.replay_vision.backend.temporal.activities.find_scanner_candidates import find_scanner_candidates_activity
from products.replay_vision.backend.temporal.sweep_types import (
    AdvanceScannerWatermarkInputs,
    CandidateSessionPayload,
    FindScannerCandidatesInputs,
    FindScannerCandidatesOutput,
    SweepScannerInputs,
)


def _make_scanner(**overrides) -> ReplayScanner:
    org = Organization.objects.create(name="vision-sweep-test-org")
    team = Team.objects.create(organization=org, name="vision-sweep-test-team")
    defaults: dict[str, Any] = {
        "team": team,
        "name": "sweep-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_FLASH,
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


async def _run_sweep(mocks: _SweepMocks, inputs: SweepScannerInputs | None = None) -> None:
    with (
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.start_child_workflow", side_effect=mocks.start_child_workflow),
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

    assert [fn for fn, _ in mocks.activity_calls] == [find_scanner_candidates_activity]
    assert mocks.child_calls == []


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
