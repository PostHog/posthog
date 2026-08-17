import uuid

import pytest
from unittest.mock import Mock

from products.tasks.backend.temporal.constants import MAX_INACTIVITY_DEFERRALS
from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.read_agent_turn_state import ReadAgentTurnStateOutput
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

pytestmark = [pytest.mark.asyncio]


def _workflow_under_test() -> ProcessTaskWorkflow:
    wf = ProcessTaskWorkflow()
    wf._context = TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        github_integration_id=1,
        repository="org/repo",
        distinct_id="user-1",
    )
    return wf


class TestAgentTurnConfirmation:
    # The inactivity window closing means "no events", not "no work": a long build emits nothing
    # for many minutes. The workflow asks before terminating, and only an explicit yes defers.
    @pytest.mark.parametrize(
        "turn_in_flight,expected",
        [
            # Working but silent: the case that would otherwise lose the turn's uncommitted work.
            (True, True),
            # Finished: the idle sandbox this timeout exists to reclaim.
            (False, False),
            # Unanswerable. Terminating keeps a dead sandbox from outliving its window just
            # because it stopped answering.
            (None, False),
        ],
    )
    async def test_only_a_reported_turn_defers_the_timeout(self, monkeypatch, turn_in_flight, expected):
        wf = _workflow_under_test()

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            return ReadAgentTurnStateOutput(turn_in_flight=turn_in_flight)

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        assert await wf._agent_is_mid_turn() is expected

    async def test_deferrals_are_capped_even_while_the_agent_keeps_claiming_a_turn(self, monkeypatch):
        # A turn parked on an unanswered permission request reports itself in flight indefinitely,
        # and interactive and user-origin runs have no hard duration cap to catch that.
        wf = _workflow_under_test()

        async def always_mid_turn(activity_fn, *args, **kwargs):
            return ReadAgentTurnStateOutput(turn_in_flight=True)

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", always_mid_turn)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        deferrals = 0
        while await wf._agent_is_mid_turn():
            deferrals += 1
            assert deferrals <= MAX_INACTIVITY_DEFERRALS + 1, "deferral loop is unbounded"

        assert deferrals == MAX_INACTIVITY_DEFERRALS

    async def test_activity_failure_terminates_rather_than_extending(self, monkeypatch):
        # Retries are exhausted or the worker is degraded. Treating that as "still working" would
        # hand every unreachable sandbox an unbounded extension on the strength of an error.
        wf = _workflow_under_test()

        async def failing_execute_activity(activity_fn, *args, **kwargs):
            raise RuntimeError("activity failed")

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", failing_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        assert await wf._agent_is_mid_turn() is False

    async def test_pre_patch_histories_never_call_the_activity(self, monkeypatch):
        # The patch gate must be read before the activity, or a history recorded without the
        # marker replays into a command it cannot account for and fails non-deterministically.
        wf = _workflow_under_test()
        called = False

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            nonlocal called
            called = True
            return ReadAgentTurnStateOutput(turn_in_flight=True)

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())
        monkeypatch.setattr(process_task_workflow_module, "confirm_turn_before_timeout", lambda: False)

        assert await wf._agent_is_mid_turn() is False
        assert called is False
