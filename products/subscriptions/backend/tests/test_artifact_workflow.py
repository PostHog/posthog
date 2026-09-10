from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.subscriptions.backend.facade import artifacts as artifacts_facade
from products.subscriptions.backend.temporal import artifacts


def test_artifact_activity_passes_only_the_team_and_completed_run_identifiers(monkeypatch) -> None:
    run_id = uuid4()
    calls: list[tuple[int, object]] = []

    def prepare(*, team_id: int, run_id: object) -> None:
        calls.append((team_id, run_id))

    monkeypatch.setattr(artifacts_facade, "prepare_proactive_artifact_for_run", prepare)

    artifacts.prepare_proactive_artifact(artifacts.ProactiveArtifactPreparationInput(team_id=17, run_id=run_id))

    assert calls == [(17, run_id)]
    assert artifacts.WORKFLOWS == [artifacts.PrepareProactiveArtifactWorkflow]
    assert artifacts.ACTIVITIES == [artifacts.prepare_proactive_artifact]


@pytest.mark.asyncio
async def test_artifact_workflow_retries_a_transient_preparation_failure(monkeypatch) -> None:
    run_id = uuid4()
    attempts = 0

    def prepare(*, team_id: int, run_id: object) -> None:
        nonlocal attempts
        assert team_id == 17
        assert run_id is not None
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary outage")

    monkeypatch.setattr(artifacts_facade, "prepare_proactive_artifact_for_run", prepare)

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        with ThreadPoolExecutor() as activity_executor:
            async with Worker(
                environment.client,
                task_queue="proactive-artifact-retry-test",
                workflows=[artifacts.PrepareProactiveArtifactWorkflow],
                activities=[artifacts.prepare_proactive_artifact],
                activity_executor=activity_executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await environment.client.execute_workflow(
                    artifacts.PrepareProactiveArtifactWorkflow.run,
                    artifacts.ProactiveArtifactPreparationInput(team_id=17, run_id=run_id),
                    id=f"proactive-artifact-retry-{run_id}",
                    task_queue="proactive-artifact-retry-test",
                )

    assert attempts == 2
