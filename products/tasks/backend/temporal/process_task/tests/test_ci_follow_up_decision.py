import uuid

import pytest
from unittest.mock import Mock

from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities.get_pr_context import GetPrContextOutput
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.workflow import CIFollowUpDecision, ProcessTaskWorkflow

pytestmark = [pytest.mark.asyncio]


class TestShouldRunCIFollowUpDecision:
    # Direct decision tests for ProcessTaskWorkflow's copy of the CI follow-up
    # gate (task_management has its own copy with an equivalent suite). Guards
    # against re-introducing "nothing to report" wake-ups: a fingerprint change
    # must only fire when the PR state is actionable.
    @pytest.mark.parametrize(
        "ci_status,changes_requested,expected_decision,expected_fingerprint",
        [
            # Actionable changes fire.
            ("failing", False, CIFollowUpDecision.FIRE, "fp-1"),
            ("passing", True, CIFollowUpDecision.FIRE, "fp-1"),
            # Non-actionable changes persist the fingerprint but stay quiet.
            # Pending needs no deferral: the settled state hashes differently
            # (CI status and head SHA are both in the fingerprint), so it still
            # registers as a change on a later tick.
            ("passing", False, CIFollowUpDecision.SKIP, "fp-1"),
            ("none", False, CIFollowUpDecision.SKIP, "fp-1"),
            ("pending", False, CIFollowUpDecision.SKIP, "fp-1"),
        ],
    )
    async def test_fingerprint_change_fires_only_when_actionable(
        self,
        monkeypatch,
        ci_status,
        changes_requested,
        expected_decision,
        expected_fingerprint,
    ):
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
        wf._pr_fingerprint = "fp-0"
        wf._pr_progress_emitted = True

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            return GetPrContextOutput(
                pr_url="https://github.com/org/repo/pull/1",
                pr_state="open",
                fingerprint="fp-1",
                ci_status=ci_status,
                changes_requested=changes_requested,
            )

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        decision = await wf._should_run_ci_follow_up()

        assert decision is expected_decision
        assert wf._pr_fingerprint == expected_fingerprint
