import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock

from temporalio.exceptions import ActivityError, ApplicationError, RetryState, TimeoutError, TimeoutType

from products.wizard.backend.facade.enums import WizardRunErrorCode, WizardRunStatus, WizardWorkspaceType
from products.wizard.backend.temporal.activities.execution import WIZARD_WORKER_TIMEOUT_ERROR_TYPE, execute_wizard
from products.wizard.backend.temporal.activities.handoff import create_run_artifacts
from products.wizard.backend.temporal.activities.lifecycle import finalize_run
from products.wizard.backend.temporal.activities.local_package import prepare_local_wizard
from products.wizard.backend.temporal.activities.workspace import clone_repository, destroy_worker, provision_worker
from products.wizard.backend.temporal.contracts import (
    PreparedGitRepositoryWorkspace,
    ProvisionedWizardWorker,
    WizardRunActivityInput,
    WizardRunFinalizationActivityInput,
)
from products.wizard.backend.temporal.workflows import execute_run as execute_run_workflow_module
from products.wizard.backend.temporal.workflows.execute_run import ExecuteWizardRunWorkflow


def _activity_error(cause: BaseException, activity_type: str = "wizard_execute") -> ActivityError:
    error = ActivityError(
        "Activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type=activity_type,
        activity_id="activity",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )
    error.__cause__ = cause
    return error


@pytest.fixture
def workflow_input() -> WizardRunActivityInput:
    return WizardRunActivityInput(team_id=1, run_id=uuid4())


@pytest.fixture
def worker(workflow_input: WizardRunActivityInput) -> ProvisionedWizardWorker:
    return ProvisionedWizardWorker(
        team_id=workflow_input.team_id,
        run_id=workflow_input.run_id,
        sandbox_id="worker",
        workspace_type=WizardWorkspaceType.GIT_REPOSITORY,
    )


@pytest.fixture
def workspace(
    workflow_input: WizardRunActivityInput,
    worker: ProvisionedWizardWorker,
) -> PreparedGitRepositoryWorkspace:
    return PreparedGitRepositoryWorkspace(
        team_id=workflow_input.team_id,
        run_id=workflow_input.run_id,
        sandbox_id=worker.sandbox_id,
        repository="posthog/posthog",
        root_path="/tmp/workspace/repos/posthog/posthog",
        github_integration_id=123,
    )


@pytest.mark.asyncio
async def test_cloud_workflow_completes_after_worker_execution(
    monkeypatch: pytest.MonkeyPatch,
    workflow_input: WizardRunActivityInput,
    worker: ProvisionedWizardWorker,
    workspace: PreparedGitRepositoryWorkspace,
) -> None:
    execute_activity = AsyncMock(side_effect=[worker, workspace, None, None, None])
    monkeypatch.setattr(execute_run_workflow_module.workflow, "execute_activity", execute_activity)

    await ExecuteWizardRunWorkflow().run(workflow_input)

    assert [call.args[0] for call in execute_activity.await_args_list] == [
        provision_worker,
        clone_repository,
        execute_wizard,
        create_run_artifacts,
        destroy_worker,
    ]
    assert execute_activity.await_args_list[0].args[1] == workflow_input
    assert execute_activity.await_args_list[1].args[1] == worker
    assert execute_activity.await_args_list[2].args[1] == workspace
    assert execute_activity.await_args_list[3].args[1] == workspace
    assert execute_activity.await_args_list[4].args[1] == worker
    assert execute_activity.await_args_list[1].kwargs["retry_policy"].maximum_attempts == 3
    assert execute_activity.await_args_list[2].kwargs["retry_policy"].maximum_attempts == 1
    assert execute_activity.await_args_list[3].kwargs["retry_policy"].maximum_attempts == 3
    assert execute_activity.await_args_list[0].kwargs["retry_policy"].maximum_attempts == 1
    assert execute_activity.await_args_list[4].kwargs["retry_policy"].maximum_attempts == 3


@pytest.mark.asyncio
async def test_cloud_workflow_prepares_local_wizard_before_workspace(
    monkeypatch: pytest.MonkeyPatch,
    workflow_input: WizardRunActivityInput,
    worker: ProvisionedWizardWorker,
    workspace: PreparedGitRepositoryWorkspace,
) -> None:
    local_input = replace(workflow_input, use_local_wizard_source=True)
    local_worker = replace(worker, use_local_wizard_source=True)
    local_workspace = replace(workspace, use_local_wizard_source=True)
    execute_activity = AsyncMock(side_effect=[local_worker, None, local_workspace, None, None, None])
    monkeypatch.setattr(execute_run_workflow_module.workflow, "execute_activity", execute_activity)

    await ExecuteWizardRunWorkflow().run(local_input)

    assert [call.args[0] for call in execute_activity.await_args_list] == [
        provision_worker,
        prepare_local_wizard,
        clone_repository,
        execute_wizard,
        create_run_artifacts,
        destroy_worker,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cause", "expected_error_code"),
    [
        (
            ApplicationError("Wizard Worker timed out.", type=WIZARD_WORKER_TIMEOUT_ERROR_TYPE),
            WizardRunErrorCode.TIMEOUT,
        ),
        (
            TimeoutError("Activity timed out", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]),
            WizardRunErrorCode.TIMEOUT,
        ),
        (
            ApplicationError("Wizard failed", type="PHW_DETECT_NO_POSTHOG_SDK"),
            "PHW_DETECT_NO_POSTHOG_SDK",
        ),
        (ApplicationError("Worker failed", type="WorkerFailure"), WizardRunErrorCode.EXECUTION_FAILED),
    ],
)
async def test_cloud_workflow_persists_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
    workflow_input: WizardRunActivityInput,
    worker: ProvisionedWizardWorker,
    workspace: PreparedGitRepositoryWorkspace,
    cause: BaseException,
    expected_error_code: str,
) -> None:
    activity_error = _activity_error(cause)
    execute_activity = AsyncMock(side_effect=[worker, workspace, activity_error, None, None])
    monkeypatch.setattr(execute_run_workflow_module.workflow, "execute_activity", execute_activity)

    with pytest.raises(ActivityError) as raised:
        await ExecuteWizardRunWorkflow().run(workflow_input)

    assert raised.value is activity_error
    assert execute_activity.await_args_list[3].args == (destroy_worker, worker)
    assert execute_activity.await_args_list[4].args == (
        finalize_run,
        WizardRunFinalizationActivityInput(
            team_id=workflow_input.team_id,
            run_id=workflow_input.run_id,
            status=WizardRunStatus.FAILED,
            error_code=expected_error_code,
        ),
    )


@pytest.mark.asyncio
async def test_cloud_workflow_persists_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    workflow_input: WizardRunActivityInput,
    worker: ProvisionedWizardWorker,
    workspace: PreparedGitRepositoryWorkspace,
) -> None:
    execute_activity = AsyncMock(side_effect=[worker, workspace, asyncio.CancelledError(), None, None])
    monkeypatch.setattr(execute_run_workflow_module.workflow, "execute_activity", execute_activity)

    with pytest.raises(asyncio.CancelledError):
        await ExecuteWizardRunWorkflow().run(workflow_input)

    assert execute_activity.await_args_list[3].args == (destroy_worker, worker)
    assert execute_activity.await_args_list[4].args == (
        finalize_run,
        WizardRunFinalizationActivityInput(
            team_id=workflow_input.team_id,
            run_id=workflow_input.run_id,
            status=WizardRunStatus.CANCELLED,
        ),
    )


@pytest.mark.asyncio
async def test_cloud_workflow_persists_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch,
    workflow_input: WizardRunActivityInput,
) -> None:
    unexpected_error = RuntimeError("unexpected workflow failure")
    execute_activity = AsyncMock(side_effect=[unexpected_error, None])
    workflow_logger = MagicMock()
    monkeypatch.setattr(execute_run_workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(execute_run_workflow_module.workflow, "logger", workflow_logger)

    with pytest.raises(RuntimeError) as raised:
        await ExecuteWizardRunWorkflow().run(workflow_input)

    assert raised.value is unexpected_error
    workflow_logger.exception.assert_called_once_with(
        "wizard_run_workflow_failed",
        extra={"team_id": workflow_input.team_id, "run_id": str(workflow_input.run_id)},
    )
    assert execute_activity.await_args_list[1].args == (
        finalize_run,
        WizardRunFinalizationActivityInput(
            team_id=workflow_input.team_id,
            run_id=workflow_input.run_id,
            status=WizardRunStatus.FAILED,
            error_code=WizardRunErrorCode.EXECUTION_FAILED,
        ),
    )


@pytest.mark.asyncio
async def test_cloud_workflow_keeps_success_when_worker_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    workflow_input: WizardRunActivityInput,
    worker: ProvisionedWizardWorker,
    workspace: PreparedGitRepositoryWorkspace,
) -> None:
    cleanup_error = _activity_error(ApplicationError("Worker cleanup failed", type="CleanupFailure"))
    execute_activity = AsyncMock(side_effect=[worker, workspace, None, None, cleanup_error])
    workflow_logger = MagicMock()
    monkeypatch.setattr(execute_run_workflow_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(execute_run_workflow_module.workflow, "logger", workflow_logger)

    await ExecuteWizardRunWorkflow().run(workflow_input)

    assert len(execute_activity.await_args_list) == 5
    workflow_logger.exception.assert_called_once()


def test_cloud_workflow_identity_and_input_parsing() -> None:
    run_id = uuid4()

    assert ExecuteWizardRunWorkflow.workflow_id_for(run_id) == f"wizard-run-{run_id}"
    assert ExecuteWizardRunWorkflow.parse_inputs([f'{{"team_id": 1, "run_id": "{run_id}"}}']) == WizardRunActivityInput(
        team_id=1,
        run_id=UUID(str(run_id)),
    )


@pytest.mark.parametrize(
    ("activity_type", "expected_error_code"),
    (
        ("wizard_provision_worker", "provisioning_failed"),
        ("wizard_clone_repository", "workspace_preparation_failed"),
        ("wizard_execute", "execution_failed"),
        ("wizard_create_run_artifacts", "artifact_creation_failed"),
    ),
)
def test_activity_failures_map_to_their_stage(activity_type: str, expected_error_code: str) -> None:
    error = _activity_error(ApplicationError("failed", type="ExternalFailure"), activity_type)

    assert execute_run_workflow_module.wizard_run_error_code(error) == expected_error_code
