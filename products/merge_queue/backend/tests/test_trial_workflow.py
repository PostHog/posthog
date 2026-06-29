import uuid
from datetime import timedelta

import pytest

from django.conf import settings

from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.merge_queue.backend.temporal.activities import RecordResultInput, SuiteResult, TrialRef
from products.merge_queue.backend.temporal.trial_workflow import TrialWorkflow, TrialWorkflowInputs


async def _run_workflow(*, passed: bool, failing: list[str]) -> tuple[bool, list]:
    """Drive TrialWorkflow against fake activities; return (result, ordered call log)."""
    calls: list = []

    @activity.defn(name="mark_trial_running")
    async def fake_mark(ref: TrialRef) -> None:
        calls.append(("mark", ref.trial_id))

    @activity.defn(name="run_full_suite")
    async def fake_suite(ref: TrialRef) -> SuiteResult:
        calls.append(("suite", ref.trial_id))
        return SuiteResult(passed=passed, failing_tests=failing)

    @activity.defn(name="record_trial_result")
    async def fake_record(result: RecordResultInput) -> None:
        calls.append(("record", result.trial_id, result.passed, result.failing_tests))

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.MERGE_QUEUE_TASK_QUEUE,
            workflows=[TrialWorkflow],
            activities=[fake_mark, fake_suite, fake_record],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                TrialWorkflow.run,
                TrialWorkflowInputs(trial_id=99),
                id=str(uuid.uuid4()),
                task_queue=settings.MERGE_QUEUE_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=timedelta(seconds=30),
            )
    return result, calls


class TestTrialWorkflow:
    @pytest.mark.parametrize("passed,failing", [(True, []), (False, ["test_real"])])
    async def test_orchestrates_run_then_records_verdict(self, passed, failing):
        result, calls = await _run_workflow(passed=passed, failing=failing)

        assert result is passed
        # mark running → run suite → record, in order, all for the same trial
        assert calls == [
            ("mark", 99),
            ("suite", 99),
            ("record", 99, passed, failing),
        ]
