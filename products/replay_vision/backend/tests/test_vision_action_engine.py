import uuid
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models import ReplayScanner, VisionAction, VisionActionRun
from products.replay_vision.backend.models.replay_scanner import ScannerModel, ScannerType
from products.replay_vision.backend.models.vision_action import TriggerType, VisionActionRunStatus
from products.replay_vision.backend.temporal.vision_actions import activities as act
from products.replay_vision.backend.temporal.vision_actions.synthesis import synthesize_group_summary_activity
from products.replay_vision.backend.temporal.vision_actions.types import (
    CreateVisionActionRunInputs,
    EmitActionReadyInputs,
    EvaluateDueVisionActionsInputs,
    ProcessVisionActionInputs,
    SynthesisStatus,
    SynthesizeGroupSummaryResult,
    UpdateVisionActionRunInputs,
    ValidateVisionActionInputs,
)
from products.replay_vision.backend.temporal.vision_actions.workflows import ProcessVisionActionWorkflow

DAILY = "FREQ=DAILY;BYHOUR=9"


def _action(team, **overrides) -> VisionAction:
    if "scanner" not in overrides:
        overrides["scanner"] = ReplayScanner.objects.create(
            team=team,
            name=f"scanner-{uuid.uuid4().hex[:8]}",
            scanner_type=ScannerType.SUMMARIZER,
            scanner_config={"prompt": "x"},
            model=ScannerModel.GEMINI_3_FLASH,
        )
    defaults: dict = {"team": team, "name": "a", "trigger_config": {"rrule": DAILY, "timezone": "UTC"}}
    defaults.update(overrides)
    a = VisionAction(**defaults)
    a.save()
    return a


def _scanner(team) -> ReplayScanner:
    return ReplayScanner.objects.create(
        team=team,
        name=f"scanner-{uuid.uuid4().hex[:8]}",
        scanner_type=ScannerType.SUMMARIZER,
        scanner_config={"prompt": "x"},
        model=ScannerModel.GEMINI_3_FLASH,
    )


def _make_due(action) -> None:
    VisionAction.all_teams.filter(pk=action.pk).update(next_run_at=timezone.now() - timedelta(hours=1))


class TestEvaluateDue(BaseTest):
    def _inputs(self, scanner) -> EvaluateDueVisionActionsInputs:
        return EvaluateDueVisionActionsInputs(scanner_id=scanner.id, team_id=self.team.id)

    def test_selects_only_this_scanners_due_enabled_schedule(self) -> None:
        scanner = _scanner(self.team)
        due = _action(self.team, name="due", scanner=scanner)
        _make_due(due)

        future = _action(self.team, name="future", scanner=scanner)
        VisionAction.all_teams.filter(pk=future.pk).update(next_run_at=timezone.now() + timedelta(days=1))

        disabled = _action(self.team, name="disabled", scanner=scanner, enabled=False)
        _make_due(disabled)

        threshold = _action(self.team, name="threshold", scanner=scanner, trigger_type=TriggerType.THRESHOLD)
        _make_due(threshold)

        # Due action on a *different* scanner must not be picked up by this scanner's sweep.
        other_scanner_action = _action(self.team, name="other-scanner")
        _make_due(other_scanner_action)

        result = act._evaluate_due(self._inputs(scanner))
        self.assertEqual([d.vision_action_id for d in result], [due.id])
        self.assertEqual(result[0].team_id, self.team.id)

    def test_claims_by_advancing_next_run_at(self) -> None:
        scanner = _scanner(self.team)
        action = _action(self.team, scanner=scanner)
        _make_due(action)
        action.refresh_from_db()
        fired_at = action.next_run_at

        result = act._evaluate_due(self._inputs(scanner))

        # The fired time is reported as scheduled_at, and the cursor is advanced past now so the next
        # sweep won't re-fire while the child runs.
        self.assertEqual(result[0].scheduled_at, fired_at)
        action.refresh_from_db()
        assert action.next_run_at is not None
        self.assertGreater(action.next_run_at, timezone.now())
        self.assertIsNotNone(action.last_run_at)

        # A second eval finds nothing — the claim already moved the cursor.
        self.assertEqual(act._evaluate_due(self._inputs(scanner)), [])

    def test_scoped_to_team(self) -> None:
        scanner = _scanner(self.team)
        action = _action(self.team, scanner=scanner)
        _make_due(action)
        # Querying the same scanner id but a different (real) team returns nothing (for_team scoping).
        other_team = self.organization.teams.create(name="other")
        self.assertEqual(
            act._evaluate_due(EvaluateDueVisionActionsInputs(scanner_id=scanner.id, team_id=other_team.id)), []
        )


class TestEngineActivities(BaseTest):
    def test_create_run_is_idempotent(self) -> None:
        action = _action(self.team)
        inputs = CreateVisionActionRunInputs(
            vision_action_id=action.id, team_id=self.team.id, idempotency_key="key-x", temporal_workflow_id="wf-1"
        )
        first = act._create_run(inputs)
        second = act._create_run(inputs)
        self.assertEqual(first, second)
        self.assertEqual(VisionActionRun.all_teams.filter(idempotency_key="key-x").count(), 1)

    @parameterized.expand(
        [
            ("not_found",),
            ("disabled",),
            ("no_delivery",),
        ]
    )
    def test_validate_reasons(self, case: str) -> None:
        if case == "not_found":
            action_id = uuid.uuid4()
        elif case == "disabled":
            action_id = _action(self.team, name="off", enabled=False).id
        else:
            # No delivery_config → nothing to deliver to → skip.
            action_id = _action(self.team, name="nodelivery").id
        self.assertEqual(
            act._validate(ValidateVisionActionInputs(vision_action_id=action_id, team_id=self.team.id)), case
        )

    def test_validate_passes_when_delivery_configured(self) -> None:
        # Regression: the gate used to check the now-vestigial hog_flow_id (always null after the
        # internal_destination rework), which skipped every action. It must pass when delivery_config is set.
        action = _action(
            self.team,
            name="delivers",
            delivery_config=[{"type": "slack", "integration_id": 1, "channel": "#general"}],
        )
        self.assertIsNone(act._validate(ValidateVisionActionInputs(vision_action_id=action.id, team_id=self.team.id)))

    def test_update_run(self) -> None:
        action = _action(self.team)
        run = VisionActionRun(vision_action=action, team=self.team, idempotency_key="k")
        run.save()
        act._update_run(
            UpdateVisionActionRunInputs(
                run_id=run.id, team_id=self.team.id, status=VisionActionRunStatus.FAILED.value, error={"message": "x"}
            )
        )
        run.refresh_from_db()
        self.assertEqual(run.status, VisionActionRunStatus.FAILED)
        self.assertEqual(run.error, {"message": "x"})

    def test_emit_produces_internal_event(self) -> None:
        action = _action(self.team)
        run = VisionActionRun(
            vision_action=action, team=self.team, idempotency_key="k", output={"slack": "hello *world*"}
        )
        run.save()

        # Delivery rides the private internal-events channel (not the public capture pipeline), so it
        # can't be forged with the project token.
        with patch.object(act, "produce_internal_event") as mock_emit:
            act._emit(EmitActionReadyInputs(run_id=run.id, team_id=self.team.id))

        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        self.assertEqual(kwargs["team_id"], self.team.id)
        event = kwargs["event"]
        self.assertEqual(event.event, "$replay_vision_action_ready")
        self.assertEqual(event.uuid, str(run.id))
        self.assertEqual(event.properties["vision_action_id"], str(action.id))
        self.assertEqual(event.properties["slack_text"], "hello *world*")


# --- workflow orchestration (activities mocked at the temporalio.workflow boundary) ---


class _Mocks:
    def __init__(self, *, results=None, errors=None):
        self.results = results or {}
        self.errors = errors or {}
        self.activity_calls: list = []

    async def execute_activity(self, fn, arg=None, **_kwargs):
        self.activity_calls.append((fn, arg))
        if fn in self.errors:
            raise self.errors[fn]
        return self.results.get(fn)

    def calls(self) -> list:
        return [fn for fn, _ in self.activity_calls]

    def arg_for(self, fn):
        return next(arg for f, arg in self.activity_calls if f is fn)


async def _run_process(inputs: ProcessVisionActionInputs, mocks: _Mocks) -> None:
    info = MagicMock()
    info.workflow_id = "wf-test"
    with (
        patch("temporalio.workflow.info", return_value=info),
        patch("temporalio.workflow.uuid4", return_value=uuid.UUID("00000000-0000-0000-0000-0000000000aa")),
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        await ProcessVisionActionWorkflow().run(inputs)


def _process_inputs() -> ProcessVisionActionInputs:
    return ProcessVisionActionInputs(vision_action_id=uuid.uuid4(), team_id=1)


def _final_status(mocks: _Mocks) -> str:
    return mocks.arg_for(act.update_vision_action_run_activity).status


def _final_error(mocks: _Mocks) -> dict | None:
    return mocks.arg_for(act.update_vision_action_run_activity).error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "synth_status, expected_final, expect_emit, expected_error",
    [
        (SynthesisStatus.SYNTHESIZED, VisionActionRunStatus.COMPLETED.value, True, None),
        (SynthesisStatus.SKIPPED_EMPTY, VisionActionRunStatus.SKIPPED.value, False, {"skip_reason": "skipped_empty"}),
        (
            SynthesisStatus.SKIPPED_OVER_BUDGET,
            VisionActionRunStatus.SKIPPED.value,
            False,
            {"skip_reason": "skipped_over_budget"},
        ),
        (
            SynthesisStatus.ABORTED_NO_CONSENT,
            VisionActionRunStatus.FAILED.value,
            False,
            {"aborted": "aborted_no_consent"},
        ),
        (SynthesisStatus.ABORTED_NO_USER, VisionActionRunStatus.FAILED.value, False, {"aborted": "aborted_no_user"}),
    ],
)
async def test_process_maps_synthesis_status(
    synth_status: SynthesisStatus, expected_final: str, expect_emit: bool, expected_error: dict | None
) -> None:
    mocks = _Mocks(
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: None,
            synthesize_group_summary_activity: SynthesizeGroupSummaryResult(status=synth_status),
        }
    )
    await _run_process(_process_inputs(), mocks)

    call_fns = mocks.calls()
    assert synthesize_group_summary_activity in call_fns
    assert (act.emit_action_ready_activity in call_fns) is expect_emit
    assert _final_status(mocks) == expected_final
    # Skip/abort runs carry the reason so they aren't unexplained; a completed run records no error.
    assert _final_error(mocks) == expected_error
    # The schedule cursor is advanced by the eligibility claim, never by this workflow.
    assert act.evaluate_due_vision_actions_activity not in call_fns


@pytest.mark.asyncio
async def test_process_skips_when_validate_returns_reason() -> None:
    mocks = _Mocks(
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: "no_delivery",
        }
    )
    await _run_process(_process_inputs(), mocks)

    assert act.emit_action_ready_activity not in mocks.calls()
    assert _final_status(mocks) == VisionActionRunStatus.SKIPPED.value
    assert _final_error(mocks) == {"skip_reason": "no_delivery"}


@pytest.mark.asyncio
async def test_process_synthesis_failure_records_failed_and_reraises() -> None:
    mocks = _Mocks(
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: None,
        },
        errors={synthesize_group_summary_activity: RuntimeError("llm exploded")},
    )
    with pytest.raises(RuntimeError, match="llm exploded"):
        await _run_process(_process_inputs(), mocks)

    # Even on failure the run is still updated to FAILED (the schedule was already advanced at claim).
    assert _final_status(mocks) == VisionActionRunStatus.FAILED.value


@pytest.mark.asyncio
async def test_update_run_failure_after_success_is_swallowed() -> None:
    # Body succeeded (emit happened → Slack delivered); a failed bookkeeping update must NOT flip the
    # workflow to FAILED — re-running would double-post. The workflow finishes without raising.
    mocks = _Mocks(
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: None,
            synthesize_group_summary_activity: SynthesizeGroupSummaryResult(status=SynthesisStatus.SYNTHESIZED),
        },
        errors={act.update_vision_action_run_activity: RuntimeError("update boom")},
    )
    await _run_process(_process_inputs(), mocks)

    assert act.emit_action_ready_activity in mocks.calls()
    assert _final_status(mocks) == VisionActionRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_update_run_failure_does_not_mask_body_error() -> None:
    # If both the body and the finally's run-update raise, the original body error must win —
    # the update failure must not clobber it.
    mocks = _Mocks(
        errors={
            synthesize_group_summary_activity: RuntimeError("llm exploded"),
            act.update_vision_action_run_activity: RuntimeError("update boom"),
        },
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: None,
        },
    )
    with pytest.raises(RuntimeError, match="llm exploded"):
        await _run_process(_process_inputs(), mocks)
