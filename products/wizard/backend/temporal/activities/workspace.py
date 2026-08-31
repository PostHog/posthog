from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import GitRepositoryWorkspace, WizardRunDTO
from products.wizard.backend.facade.enums import (
    WizardRunEnvironment,
    WizardRunStage,
    WizardRunStatus,
    WizardWorkspaceType,
)
from products.wizard.backend.facade.errors import (
    InvalidRepositoryError,
    MissingGitHubIntegrationError,
    RepositoryNotAccessibleError,
)
from products.wizard.backend.logic.runs.repository_access import authorize_git_repository_access
from products.wizard.backend.logic.workers import (
    lifecycle as worker_lifecycle,
    service as cloud_worker,
    store as worker_store,
)
from products.wizard.backend.logic.workers.service import GitRepositoryCloneRequest, WizardWorkerProvisionRequest
from products.wizard.backend.temporal.activities.errors import (
    WIZARD_REPOSITORY_ACCESS_ERROR_TYPE,
    WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
    WIZARD_WORKER_EXECUTION_ERROR_TYPE,
)
from products.wizard.backend.temporal.activities.lifecycle import transition_cloud_run
from products.wizard.backend.temporal.contracts import (
    PreparedGitRepositoryWorkspace,
    ProvisionedWizardWorker,
    WizardRunActivityInput,
)


@activity.defn(name="wizard_provision_worker")
@asyncify
def provision_worker(input: WizardRunActivityInput) -> ProvisionedWizardWorker:
    run = _get_cloud_run(input)
    wizard_facade.update_run_stage(input.team_id, input.run_id, WizardRunStage.PROVISIONING)
    if run.created_by_id is None:
        raise ApplicationError(
            "Wizard run creator is no longer available.",
            type=WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
            non_retryable=True,
        )
    if not isinstance(run.workspace, GitRepositoryWorkspace):
        raise ApplicationError(
            "Wizard run does not have a supported cloud workspace.",
            type=WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
            non_retryable=True,
        )

    existing_sandbox_id = worker_store.get_sandbox_id(input.team_id, input.run_id)
    if existing_sandbox_id is not None:
        return ProvisionedWizardWorker(
            team_id=input.team_id,
            run_id=input.run_id,
            sandbox_id=existing_sandbox_id,
            workspace_type=WizardWorkspaceType.GIT_REPOSITORY,
            use_local_wizard_source=input.use_local_wizard_source,
        )

    provisioning = cloud_worker.provision_wizard_worker(
        WizardWorkerProvisionRequest(
            team_id=input.team_id,
            created_by_id=run.created_by_id,
            run_id=input.run_id,
        )
    )
    worker_store.record_provisioned_worker(input.team_id, input.run_id, provisioning)
    transition_cloud_run(input.team_id, input.run_id, WizardRunStatus.RUNNING)
    return ProvisionedWizardWorker(
        team_id=input.team_id,
        run_id=input.run_id,
        sandbox_id=provisioning.sandbox_id,
        workspace_type=WizardWorkspaceType.GIT_REPOSITORY,
        use_local_wizard_source=input.use_local_wizard_source,
    )


@activity.defn(name="wizard_clone_repository")
@asyncify
def clone_repository(input: ProvisionedWizardWorker) -> PreparedGitRepositoryWorkspace:
    run = _get_cloud_run(WizardRunActivityInput(team_id=input.team_id, run_id=input.run_id))
    wizard_facade.update_run_stage(input.team_id, input.run_id, WizardRunStage.PREPARING_WORKSPACE)
    if not isinstance(run.workspace, GitRepositoryWorkspace):
        raise ApplicationError(
            "Wizard run does not have a Git repository workspace.",
            type=WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
            non_retryable=True,
        )

    try:
        integration_id = authorize_git_repository_access(input.team_id, run.workspace.repository)
    except (InvalidRepositoryError, MissingGitHubIntegrationError, RepositoryNotAccessibleError) as error:
        raise ApplicationError(
            "GitHub access to the Wizard run repository is unavailable.",
            type=WIZARD_REPOSITORY_ACCESS_ERROR_TYPE,
            non_retryable=True,
        ) from error

    try:
        root_path = cloud_worker.clone_repository(
            GitRepositoryCloneRequest(
                sandbox_id=input.sandbox_id,
                github_integration_id=integration_id,
                repository=run.workspace.repository,
            )
        )
    except cloud_worker.WizardWorkerExecutionError as error:
        raise ApplicationError(
            str(error),
            type=WIZARD_WORKER_EXECUTION_ERROR_TYPE,
            non_retryable=True,
        ) from error

    return PreparedGitRepositoryWorkspace(
        team_id=input.team_id,
        run_id=input.run_id,
        sandbox_id=input.sandbox_id,
        repository=run.workspace.repository,
        root_path=root_path,
        github_integration_id=integration_id,
        use_local_wizard_source=input.use_local_wizard_source,
    )


@activity.defn(name="wizard_destroy_worker")
@asyncify
def destroy_worker(input: ProvisionedWizardWorker) -> None:
    worker_lifecycle.cleanup_worker(input.team_id, input.run_id, input.sandbox_id)


def _get_cloud_run(input: WizardRunActivityInput) -> WizardRunDTO:
    run = wizard_facade.get_run(input.team_id, input.run_id)
    if run.environment != WizardRunEnvironment.CLOUD:
        raise ApplicationError(
            "Wizard Worker requires a cloud run.",
            type=WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
            non_retryable=True,
        )
    return run
