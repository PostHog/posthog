from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.enums import WizardRunStage
from products.wizard.backend.logic.workers import service as cloud_worker
from products.wizard.backend.logic.workers.service import WizardExecutionRequest
from products.wizard.backend.temporal.activities.errors import (
    WIZARD_WORKER_EXECUTION_ERROR_TYPE,
    WIZARD_WORKER_TIMEOUT_ERROR_TYPE,
)
from products.wizard.backend.temporal.contracts import PreparedGitRepositoryWorkspace


@activity.defn(name="wizard_execute")
@asyncify
def execute_wizard(input: PreparedGitRepositoryWorkspace) -> None:
    wizard_facade.update_run_stage(input.team_id, input.run_id, WizardRunStage.EXECUTING_WIZARD)
    run = wizard_facade.get_run(input.team_id, input.run_id)
    try:
        cloud_worker.execute_wizard(
            WizardExecutionRequest(
                sandbox_id=input.sandbox_id,
                workspace_path=input.root_path,
                team_id=input.team_id,
                wizard_version=run.program.wizard_version,
                program_command=run.program.command,
                use_local_wizard_source=input.use_local_wizard_source,
            )
        )
    except cloud_worker.WizardWorkerTimeoutError as error:
        raise ApplicationError(
            "Wizard Worker timed out.",
            type=WIZARD_WORKER_TIMEOUT_ERROR_TYPE,
            non_retryable=True,
        ) from error
    except cloud_worker.WizardWorkerExecutionError as error:
        raise ApplicationError(
            str(error),
            type=error.wizard_error_code or WIZARD_WORKER_EXECUTION_ERROR_TYPE,
            non_retryable=True,
        ) from error
