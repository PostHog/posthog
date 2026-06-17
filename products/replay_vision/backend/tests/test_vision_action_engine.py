import uuid
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.replay_vision.backend.models import VisionAction, VisionActionRun
from products.replay_vision.backend.models.vision_action import TriggerType, VisionActionRunStatus
from products.replay_vision.backend.temporal.vision_actions import activities as act
from products.replay_vision.backend.temporal.vision_actions.synthesis import synthesize_action_activity
from products.replay_vision.backend.temporal.vision_actions.types import (
    CreateVisionActionRunInputs,
    EmitActionReadyInputs,
    ProcessVisionActionInputs,
    ScheduleAllVisionActionsInputs,
    SynthesisStatus,
    SynthesizeActionResult,
    UpdateVisionActionRunInputs,
)
from products.replay_vision.backend.temporal.vision_actions.workflows import (
    ProcessVisionActionWorkflow,
    ScheduleAllVisionActionsWorkflow,
)

DAILY = "FREQ=DAILY;BYHOUR=9"


def _action(team, **overrides) -> VisionAction:
    defaults: dict = {"team": team, "name": "a", "trigger_config": {"rrule": DAILY, "timezone": "UTC"}}
    defaults.update(overrides)
    a = VisionAction(**defaults)
    a.save()
    return a


class TestEngineActivities(BaseTest):
    def test_fetch_due_selects_only_due_enabled_schedule(self) -> None:
        due = _action(self.team, name="due")
        VisionAction.all_teams.filter(pk=due.pk).update(next_run_at=timezone.now() - timedelta(hours=1))

        future = _action(self.team, name="future")
        VisionAction.all_teams.filter(pk=future.pk).update(next_run_at=timezone.now() + timedelta(days=1))

        _action(self.team, name="disabled", enabled=False)
        VisionAction.all_teams.filter(name="disabled").update(next_run_at=timezone.now() - timedelta(hours=1))

        _action(self.team, name="threshold", trigger_type=TriggerType.THRESHOLD, trigger_config={})

        result = act._fetch_due(ScheduleAllVisionActionsInputs())
        self.assertEqual([d.vision_action_id for d in result], [due.id])
        self.assertEqual(result[0].team_id, self.team.id)

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
            ("no_delivery_flow",),
        ]
    )
    def test_validate_reasons(self, case: str) -> None:
        if case == "not_found":
            action_id = uuid.uuid4()
        elif case == "disabled":
            action_id = _action(self.team, name="off", enabled=False).id
        else:
            action_id = _action(self.team, name="noflow").id
        self.assertEqual(act._validate(action_id), case)

    def test_update_run(self) -> None:
        action = _action(self.team)
        run = VisionActionRun(vision_action=action, team=self.team, idempotency_key="k")
        run.save()
        act._update_run(
            UpdateVisionActionRunInputs(
                run_id=run.id, status=VisionActionRunStatus.FAILED.value, error={"message": "x"}
            )
        )
        run.refresh_from_db()
        self.assertEqual(run.status, VisionActionRunStatus.FAILED)
        self.assertEqual(run.error, {"message": "x"})

    def test_advance_next_run(self) -> None:
        action = _action(self.team)
        VisionAction.all_teams.filter(pk=action.pk).update(next_run_at=timezone.now() - timedelta(days=2))
        act._advance_next_run(action.id)
        action.refresh_from_db()
        self.assertIsNotNone(action.next_run_at)
        assert action.next_run_at is not None
        self.assertGreater(action.next_run_at, timezone.now())
        self.assertIsNotNone(action.last_run_at)

    def test_emit_captures_event(self) -> None:
        action = _action(self.team)
        run = VisionActionRun(vision_action=action, team=self.team, idempotency_key="k", slack_text="hello *world*")
        run.save()

        captured = MagicMock()
        captured.raise_for_status = MagicMock()
        with patch.object(act, "capture_internal_routed", return_value=captured) as mock_capture:
            act._emit(EmitActionReadyInputs(run_id=run.id))

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        self.assertEqual(kwargs["event_name"], "$replay_vision_action_ready")
        self.assertEqual(kwargs["event_uuid"], str(run.id))
        self.assertEqual(kwargs["properties"]["vision_action_id"], str(action.id))
        self.assertEqual(kwargs["properties"]["slack_text"], "hello *world*")
        self.assertFalse(kwargs["process_person_profile"])
        captured.raise_for_status.assert_called_once()


# --- workflow orchestration (activities mocked at the temporalio.workflow boundary) ---


class _Mocks:
    def __init__(self, *, results=None, errors=None, child_errors=None):
        self.results = results or {}
        self.errors = errors or {}
        self.child_errors = child_errors or {}
        self.activity_calls: list = []
        self.child_calls: list = []

    async def execute_activity(self, fn, arg=None, **_kwargs):
        self.activity_calls.append((fn, arg))
        if fn in self.errors:
            raise self.errors[fn]
        return self.results.get(fn)

    async def execute_child_workflow(self, _run, arg=None, **kwargs):
        cid = kwargs.get("id")
        self.child_calls.append((cid, arg))
        if cid in self.child_errors:
            raise self.child_errors[cid]
        return None

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "synth_status, expected_final, expect_emit",
    [
        (SynthesisStatus.SYNTHESIZED, VisionActionRunStatus.COMPLETED.value, True),
        (SynthesisStatus.SKIPPED_EMPTY, VisionActionRunStatus.SKIPPED.value, False),
        (SynthesisStatus.SKIPPED_OVER_BUDGET, VisionActionRunStatus.SKIPPED.value, False),
        (SynthesisStatus.ABORTED_NO_CONSENT, VisionActionRunStatus.FAILED.value, False),
        (SynthesisStatus.ABORTED_NO_USER, VisionActionRunStatus.FAILED.value, False),
    ],
)
async def test_process_maps_synthesis_status(
    synth_status: SynthesisStatus, expected_final: str, expect_emit: bool
) -> None:
    mocks = _Mocks(
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: None,
            synthesize_action_activity: SynthesizeActionResult(status=synth_status),
        }
    )
    await _run_process(_process_inputs(), mocks)

    call_fns = mocks.calls()
    assert synthesize_action_activity in call_fns
    assert (act.emit_action_ready_activity in call_fns) is expect_emit
    assert _final_status(mocks) == expected_final
    # The schedule is always advanced, whatever the outcome — a stuck run must not hot-loop.
    assert act.advance_next_run_at_activity in call_fns


@pytest.mark.asyncio
async def test_process_skips_when_validate_returns_reason() -> None:
    mocks = _Mocks(
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: "no_delivery_flow",
        }
    )
    await _run_process(_process_inputs(), mocks)

    assert act.emit_action_ready_activity not in mocks.calls()
    assert _final_status(mocks) == VisionActionRunStatus.SKIPPED.value
    assert act.advance_next_run_at_activity in mocks.calls()


@pytest.mark.asyncio
async def test_process_synthesis_failure_records_failed_and_reraises() -> None:
    mocks = _Mocks(
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: None,
        },
        errors={synthesize_action_activity: RuntimeError("llm exploded")},
    )
    with pytest.raises(RuntimeError, match="llm exploded"):
        await _run_process(_process_inputs(), mocks)

    # Even on failure: run is updated to FAILED and the schedule is advanced (no hot-loop).
    assert _final_status(mocks) == VisionActionRunStatus.FAILED.value
    assert act.advance_next_run_at_activity in mocks.calls()


@pytest.mark.asyncio
async def test_advance_failure_does_not_mask_body_error() -> None:
    # If both the body and the finally's advance raise, the original body error must win —
    # the advance failure must not clobber it.
    mocks = _Mocks(
        errors={
            synthesize_action_activity: RuntimeError("llm exploded"),
            act.advance_next_run_at_activity: RuntimeError("advance boom"),
        },
        results={
            act.create_vision_action_run_activity: uuid.uuid4(),
            act.validate_vision_action_activity: None,
        },
    )
    with pytest.raises(RuntimeError, match="llm exploded"):
        await _run_process(_process_inputs(), mocks)


async def _run_schedule_all(due_list, mocks: _Mocks) -> None:
    with (
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.execute_child_workflow", side_effect=mocks.execute_child_workflow),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        mocks.results[act.fetch_due_vision_actions_activity] = due_list
        await ScheduleAllVisionActionsWorkflow().run(ScheduleAllVisionActionsInputs())


@pytest.mark.asyncio
async def test_schedule_all_fans_out_one_child_per_due_action() -> None:
    from products.replay_vision.backend.temporal.vision_actions.types import DueVisionAction

    due = [DueVisionAction(vision_action_id=uuid.uuid4(), team_id=1) for _ in range(3)]
    mocks = _Mocks()
    await _run_schedule_all(due, mocks)

    child_ids = {cid for cid, _ in mocks.child_calls}
    assert child_ids == {f"process-vision-action-{d.vision_action_id}" for d in due}


@pytest.mark.asyncio
async def test_schedule_all_swallows_already_started() -> None:
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from products.replay_vision.backend.temporal.vision_actions.types import DueVisionAction

    d = DueVisionAction(vision_action_id=uuid.uuid4(), team_id=1)
    cid = f"process-vision-action-{d.vision_action_id}"
    mocks = _Mocks(
        child_errors={cid: WorkflowAlreadyStartedError(workflow_id=cid, workflow_type="process-vision-action")}
    )
    # Should not raise — an already-running action is skipped, not a failure.
    await _run_schedule_all([d], mocks)


@pytest.mark.asyncio
async def test_schedule_all_noop_when_nothing_due() -> None:
    mocks = _Mocks()
    await _run_schedule_all([], mocks)
    assert mocks.child_calls == []
