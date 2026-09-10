from typing import Any, cast
from uuid import UUID

import pytest

from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from products.tasks.backend.temporal.publish_task_artifact import workflow as workflow_module
from products.tasks.backend.temporal.publish_task_artifact.workflow import (
    PublishTaskArtifactInput,
    PublishTaskArtifactWorkflow,
)


def test_workflow_input_contains_only_publication_identifiers() -> None:
    input = PublishTaskArtifactInput(staged_run_id=UUID(int=1), publication_id=UUID(int=2))

    assert input.staged_run_id == UUID(int=1)
    assert input.publication_id == UUID(int=2)
    assert set(input.__dataclass_fields__) == {"staged_run_id", "publication_id"}


@pytest.mark.asyncio
async def test_workflow_retries_unknown_activity_outcomes_with_bounded_attempts(monkeypatch) -> None:
    input = PublishTaskArtifactInput(staged_run_id=UUID(int=1), publication_id=UUID(int=2))
    calls: list[dict[str, Any]] = []

    async def execute_activity(*args, **kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(workflow_module.workflow, "execute_activity", execute_activity)

    await PublishTaskArtifactWorkflow().run(input)

    assert cast(RetryPolicy, calls[0]["retry_policy"]).maximum_attempts == 3
    assert calls[0]["start_to_close_timeout"].total_seconds() == 12 * 60


@pytest.mark.asyncio
async def test_workflow_finalizes_an_unexported_publication_after_activity_exhaustion(monkeypatch) -> None:
    input = PublishTaskArtifactInput(staged_run_id=UUID(int=1), publication_id=UUID(int=2))
    finalizer = object()
    calls: list[object] = []

    async def execute_activity(activity, *_args, **_kwargs) -> None:
        calls.append(activity)
        if activity is workflow_module.publish_task_artifact:
            raise ApplicationError("publication exhausted")

    monkeypatch.setattr(workflow_module, "finalize_failed_publication", finalizer, raising=False)
    monkeypatch.setattr(workflow_module.workflow, "execute_activity", execute_activity)

    with pytest.raises(ApplicationError, match="exhausted"):
        await PublishTaskArtifactWorkflow().run(input)

    assert calls == [workflow_module.publish_task_artifact, finalizer]
