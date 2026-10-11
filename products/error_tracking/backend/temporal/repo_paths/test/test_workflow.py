import uuid

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.temporal.repo_paths.types import (
    RepoPathsWorkflowInputs,
    StoreReleaseFileListInputs,
)
from products.error_tracking.backend.temporal.repo_paths.workflow import (
    BUDGET_DEFERRALS,
    ErrorTrackingRepoPathsWorkflow,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcomes, expected_result, expected_last_tries",
    [
        (["budget_exhausted", "budget_exhausted", "written"], "written", [False, False, False]),
        (
            ["budget_exhausted"] * (BUDGET_DEFERRALS + 1),
            "budget_exhausted",
            [False] * BUDGET_DEFERRALS + [True],
        ),
    ],
    ids=["budget_frees_up", "budget_stays_spent"],
)
async def test_a_spent_budget_defers_the_job_until_the_last_try(
    outcomes: list[str], expected_result: str, expected_last_tries: list[bool]
) -> None:
    last_tries: list[bool] = []

    @activity.defn(name="store_release_file_list_activity")
    async def store(inputs: StoreReleaseFileListInputs) -> str:
        last_tries.append(inputs.last_try)
        return outcomes[len(last_tries) - 1]

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingRepoPathsWorkflow],
            activities=[store],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                ErrorTrackingRepoPathsWorkflow.run,
                RepoPathsWorkflowInputs(team_id=1, release_id=str(uuid.uuid4())),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result == expected_result
    assert last_tries == expected_last_tries
