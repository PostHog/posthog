from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import override_settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    WizardRunDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import (
    WizardRunArtifactType,
    WizardRunEnvironment,
    WizardRunStatus,
    WizardWorkspaceType,
)
from products.wizard.backend.logic.workers.contracts import RepositoryPullRequest, WizardWorkerResourceUsage
from products.wizard.backend.logic.workers.service import (
    GitRepositoryCloneRequest,
    GitRepositoryHandoffRequest,
    WizardExecutionRequest,
    WizardWorkerExecutionError,
    WizardWorkerProvisioning,
    WizardWorkerProvisionRequest,
    WizardWorkerResult,
    WizardWorkerTimeoutError,
)
from products.wizard.backend.temporal.activities.errors import (
    WIZARD_REPOSITORY_ACCESS_ERROR_TYPE,
    WIZARD_WORKER_EXECUTION_ERROR_TYPE,
    WIZARD_WORKER_TIMEOUT_ERROR_TYPE,
)
from products.wizard.backend.temporal.activities.execution import execute_wizard
from products.wizard.backend.temporal.activities.handoff import create_run_artifacts
from products.wizard.backend.temporal.activities.local_package import prepare_local_wizard
from products.wizard.backend.temporal.activities.workspace import clone_repository, provision_worker
from products.wizard.backend.temporal.contracts import (
    PreparedGitRepositoryWorkspace,
    ProvisionedWizardWorker,
    WizardRunActivityInput,
)


def _create_cloud_run(
    team_id: int,
    user_id: int,
    *,
    program_id: str = "posthog-integration",
    registry_payload: object = None,
) -> WizardRunDTO:
    with (
        patch("posthoganalytics.get_feature_flag_payload", return_value=registry_payload),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=123,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
    ):
        return wizard_facade.create_run(
            CreateWizardRunInput(
                team_id=team_id,
                created_by_id=user_id,
                environment=WizardRunEnvironment.CLOUD,
                idempotency_key="test-cloud-activity",
                workspace=GitRepositoryWorkspace(repository="posthog/posthog"),
                program_id=program_id,
            )
        )


def _worker(run: WizardRunDTO) -> ProvisionedWizardWorker:
    return ProvisionedWizardWorker(
        team_id=run.team_id,
        run_id=run.id,
        sandbox_id="worker-id",
        workspace_type=WizardWorkspaceType.GIT_REPOSITORY,
    )


def _provisioning() -> WizardWorkerProvisioning:
    return WizardWorkerProvisioning(
        sandbox_id="worker-id",
        resource_usage=WizardWorkerResourceUsage(
            cpu_cores=2,
            memory_gb=4,
            disk_size_gb=16,
            ttl_seconds=4500,
            ttl_expires_at=timezone.now() + timedelta(seconds=4500),
        ),
    )


def _workspace(run: WizardRunDTO) -> PreparedGitRepositoryWorkspace:
    return PreparedGitRepositoryWorkspace(
        team_id=run.team_id,
        run_id=run.id,
        sandbox_id="worker-id",
        repository="posthog/posthog",
        root_path="/tmp/workspace/repos/posthog/posthog",
        github_integration_id=456,
    )


async def _run_provision_worker(input: WizardRunActivityInput) -> ProvisionedWizardWorker:
    return await ActivityEnvironment().run(provision_worker, input)


async def _run_clone_repository(input: ProvisionedWizardWorker) -> PreparedGitRepositoryWorkspace:
    return await ActivityEnvironment().run(clone_repository, input)


async def _run_prepare_local_wizard(input: ProvisionedWizardWorker) -> None:
    await ActivityEnvironment().run(prepare_local_wizard, input)


async def _run_execute_wizard(input: PreparedGitRepositoryWorkspace) -> None:
    await ActivityEnvironment().run(execute_wizard, input)


async def _run_create_run_artifacts(input: PreparedGitRepositoryWorkspace) -> None:
    await ActivityEnvironment().run(create_run_artifacts, input)


@pytest.mark.django_db(transaction=True)
def test_provision_worker_uses_persisted_run_identity(team, user) -> None:
    run = _create_cloud_run(team.id, user.id)

    with patch(
        "products.wizard.backend.temporal.activities.workspace.cloud_worker.provision_wizard_worker",
        return_value=_provisioning(),
    ) as provision:
        result = async_to_sync(_run_provision_worker)(WizardRunActivityInput(team_id=team.id, run_id=run.id))

    assert result == _worker(run)
    persisted_run = wizard_facade.get_run(team.id, run.id)
    assert persisted_run.status == WizardRunStatus.RUNNING
    assert persisted_run.stage == "provisioning"
    provision.assert_called_once_with(
        WizardWorkerProvisionRequest(team_id=team.id, created_by_id=user.id, run_id=run.id)
    )

    worker_record = apps.get_model("wizard", "WizardWorker").objects.for_team(team.id).get(run_id=run.id)
    assert worker_record.sandbox_id == "worker-id"
    assert worker_record.cleanup_status == "active"
    assert worker_record.resource_usage["cpu_cores"] == 2.0

    provision.reset_mock()
    repeated = async_to_sync(_run_provision_worker)(WizardRunActivityInput(team_id=team.id, run_id=run.id))

    assert repeated == result
    provision.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_clone_repository_rechecks_access_before_preparing_workspace(team, user) -> None:
    run = _create_cloud_run(team.id, user.id)
    worker = _worker(run)

    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=456,
        ) as resolve_integration,
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ) as repository_accessible,
        patch(
            "products.wizard.backend.temporal.activities.workspace.cloud_worker.clone_repository",
            return_value="/tmp/workspace/repos/posthog/posthog",
        ) as clone,
    ):
        result = async_to_sync(_run_clone_repository)(worker)

    assert result == _workspace(run)
    assert wizard_facade.get_run(team.id, run.id).stage == "preparing_workspace"
    resolve_integration.assert_called_once_with(team.id)
    repository_accessible.assert_called_once_with(team.id, 456, "posthog/posthog")
    clone.assert_called_once_with(
        GitRepositoryCloneRequest(
            sandbox_id=worker.sandbox_id,
            github_integration_id=456,
            repository="posthog/posthog",
        )
    )


@override_settings(DEBUG=True, LOCAL_WIZARD_ROOT="/tmp/posthog-wizard")
def test_prepare_local_wizard_uses_configured_source() -> None:
    worker = ProvisionedWizardWorker(
        team_id=7,
        run_id=uuid4(),
        sandbox_id="worker-id",
        workspace_type=WizardWorkspaceType.GIT_REPOSITORY,
        use_local_wizard_source=True,
    )

    with patch(
        "products.wizard.backend.temporal.activities.local_package.cloud_worker.prepare_local_wizard"
    ) as prepare:
        async_to_sync(_run_prepare_local_wizard)(worker)

    prepare.assert_called_once_with(worker.sandbox_id, Path("/tmp/posthog-wizard").resolve())


@pytest.mark.django_db(transaction=True)
def test_clone_repository_rejects_access_revoked_after_creation(team, user) -> None:
    run = _create_cloud_run(team.id, user.id)

    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=None,
        ),
        patch("products.wizard.backend.temporal.activities.workspace.cloud_worker.clone_repository") as clone,
        pytest.raises(ApplicationError) as error,
    ):
        async_to_sync(_run_clone_repository)(_worker(run))

    assert error.value.type == WIZARD_REPOSITORY_ACCESS_ERROR_TYPE
    assert error.value.non_retryable is True
    clone.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_clone_repository_keeps_transient_clone_failure_retryable(team, user) -> None:
    run = _create_cloud_run(team.id, user.id)

    with (
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.resolve_team_github_integration_id",
            return_value=456,
        ),
        patch(
            "products.wizard.backend.logic.runs.repository_access.repo_selection.repository_accessible_via_integration",
            return_value=True,
        ),
        patch(
            "products.wizard.backend.temporal.activities.workspace.cloud_worker.clone_repository",
            side_effect=WizardWorkerExecutionError("repository clone", 128),
        ),
        pytest.raises(ApplicationError) as error,
    ):
        async_to_sync(_run_clone_repository)(_worker(run))

    assert error.value.type == WIZARD_WORKER_EXECUTION_ERROR_TYPE
    assert not error.value.non_retryable


@pytest.mark.parametrize(
    "worker_error, error_type",
    (
        (WizardWorkerTimeoutError(), WIZARD_WORKER_TIMEOUT_ERROR_TYPE),
        (WizardWorkerExecutionError("execution", 1), WIZARD_WORKER_EXECUTION_ERROR_TYPE),
        (
            WizardWorkerExecutionError("execution", 1, wizard_error_code="PHW_DETECT_NO_POSTHOG_SDK"),
            "PHW_DETECT_NO_POSTHOG_SDK",
        ),
    ),
)
def test_execute_wizard_maps_worker_error(worker_error: Exception, error_type: str) -> None:
    workspace = PreparedGitRepositoryWorkspace(
        team_id=7,
        run_id=uuid4(),
        sandbox_id="worker-id",
        repository="posthog/posthog",
        root_path="/tmp/workspace/repos/posthog/posthog",
        github_integration_id=456,
    )

    with (
        patch("products.wizard.backend.temporal.activities.execution.wizard_facade.update_run_stage"),
        patch("products.wizard.backend.temporal.activities.execution.wizard_facade.get_run") as get_run,
        patch(
            "products.wizard.backend.temporal.activities.execution.cloud_worker.execute_wizard",
            side_effect=worker_error,
        ) as execute,
        pytest.raises(ApplicationError) as error,
    ):
        get_run.return_value.program.command = ()
        get_run.return_value.program.wizard_version = "2.60.0"
        async_to_sync(_run_execute_wizard)(workspace)

    execute.assert_called_once_with(
        WizardExecutionRequest(
            sandbox_id=workspace.sandbox_id,
            workspace_path=workspace.root_path,
            team_id=workspace.team_id,
            wizard_version="2.60.0",
            program_command=(),
        )
    )
    assert error.value.type == error_type


@pytest.mark.django_db(transaction=True)
@patch("products.wizard.backend.logic.artifacts.service.object_storage.write")
def test_create_run_artifacts_persists_git_diff_and_pull_request(_write: MagicMock, team, user) -> None:
    run = _create_cloud_run(team.id, user.id)
    wizard_facade.update_run_status(team.id, run.id, WizardRunStatus.RUNNING)
    workspace = _workspace(run)
    diff = b"diff --git a/a b/a\n"
    pull_request = RepositoryPullRequest(
        repository=workspace.repository,
        number=123,
        url="https://github.com/posthog/posthog/pull/123",
        head_branch="posthog/wizard-123",
        base_branch="master",
    )

    with patch(
        "products.wizard.backend.temporal.activities.handoff.cloud_worker.create_git_repository_handoff",
        return_value=WizardWorkerResult(diff=diff, pull_request=pull_request),
    ) as handoff:
        async_to_sync(_run_create_run_artifacts)(workspace)

    handoff.assert_called_once_with(
        GitRepositoryHandoffRequest(
            team_id=workspace.team_id,
            run_id=workspace.run_id,
            sandbox_id=workspace.sandbox_id,
            workspace_path=workspace.root_path,
            github_integration_id=workspace.github_integration_id,
            repository=workspace.repository,
        )
    )
    artifacts = wizard_facade.list_run_artifacts(team.id, run.id)
    assert {artifact.artifact_type for artifact in artifacts} == {
        WizardRunArtifactType.GIT_DIFF,
        WizardRunArtifactType.PULL_REQUEST,
    }
    git_diff_artifact = next(artifact for artifact in artifacts if isinstance(artifact, WizardRunGitDiffArtifactDTO))
    assert git_diff_artifact.size_bytes == len(diff)
    pull_request_artifact = next(
        artifact for artifact in artifacts if isinstance(artifact, WizardRunPullRequestArtifactDTO)
    )
    assert pull_request_artifact.url == pull_request.url
    assert pull_request_artifact.number == pull_request.number
    assert wizard_facade.get_run(team.id, run.id).status == WizardRunStatus.COMPLETED
