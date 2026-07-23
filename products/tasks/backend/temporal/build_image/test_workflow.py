import pytest
from unittest.mock import AsyncMock

from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from products.tasks.backend.temporal.build_image import workflow as build_image_workflow_module
from products.tasks.backend.temporal.build_image.activities import MarkImageBuildFailedInput
from products.tasks.backend.temporal.build_image.workflow import BuildSandboxImageInput, BuildSandboxImageWorkflow


@pytest.mark.asyncio
async def test_build_failure_surfaces_activity_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    activity_error = ActivityError(
        "Activity task failed",
        scheduled_event_id=10,
        started_event_id=11,
        identity="worker-1",
        activity_type="scan_image_spec",
        activity_id="activity-1",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )
    activity_error.__cause__ = ApplicationError("Security scanner unavailable", type="ScannerUnavailableError")
    execute_activity = AsyncMock(side_effect=[activity_error, None])
    monkeypatch.setattr(build_image_workflow_module.workflow, "execute_activity", execute_activity)

    result = await BuildSandboxImageWorkflow().run(BuildSandboxImageInput(image_id="image-id", team_id=1))

    assert result.success is False
    assert result.error == "Security scanner unavailable"
    failure_input = execute_activity.await_args_list[1].args[1]
    assert failure_input == MarkImageBuildFailedInput(
        image_id="image-id", team_id=1, error="Security scanner unavailable", refresh=False
    )
