from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import CreatePullRequestArtifactInput
from products.wizard.backend.facade.enums import WizardRunStage, WizardRunStatus
from products.wizard.backend.logic.workers import service as cloud_worker
from products.wizard.backend.logic.workers.service import GitRepositoryHandoffRequest
from products.wizard.backend.temporal.activities.errors import WIZARD_WORKER_EXECUTION_ERROR_TYPE
from products.wizard.backend.temporal.activities.lifecycle import transition_cloud_run
from products.wizard.backend.temporal.contracts import PreparedGitRepositoryWorkspace


@activity.defn(name="wizard_create_run_artifacts")
@asyncify
def create_run_artifacts(input: PreparedGitRepositoryWorkspace) -> None:
    wizard_facade.update_run_stage(input.team_id, input.run_id, WizardRunStage.CREATING_ARTIFACTS)
    try:
        result = cloud_worker.create_git_repository_handoff(
            GitRepositoryHandoffRequest(
                team_id=input.team_id,
                run_id=input.run_id,
                sandbox_id=input.sandbox_id,
                workspace_path=input.root_path,
                github_integration_id=input.github_integration_id,
                repository=input.repository,
            )
        )
    except cloud_worker.WizardWorkerExecutionError as error:
        raise ApplicationError(
            str(error),
            type=WIZARD_WORKER_EXECUTION_ERROR_TYPE,
            non_retryable=True,
        ) from error

    wizard_facade.create_git_diff_artifact(input.team_id, input.run_id, result.diff)
    if result.pull_request is not None:
        wizard_facade.create_pull_request_artifact(
            CreatePullRequestArtifactInput(
                team_id=input.team_id,
                run_id=input.run_id,
                url=result.pull_request.url,
                number=result.pull_request.number,
                repository=result.pull_request.repository,
                head_branch=result.pull_request.head_branch,
                base_branch=result.pull_request.base_branch,
            )
        )

    transition_cloud_run(input.team_id, input.run_id, WizardRunStatus.COMPLETED)
