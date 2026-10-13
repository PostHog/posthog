import asyncio
from uuid import UUID

from temporalio import workflow
from temporalio.exceptions import ActivityError

from posthog.temporal.common.base import PostHogWorkflow

from products.wizard.backend.facade.enums import WizardRunErrorCode, WizardRunStatus, WizardWorkspaceType
from products.wizard.backend.temporal.activities.execution import execute_wizard
from products.wizard.backend.temporal.activities.handoff import create_run_artifacts
from products.wizard.backend.temporal.activities.lifecycle import finalize_run
from products.wizard.backend.temporal.activities.local_package import prepare_local_wizard
from products.wizard.backend.temporal.activities.workspace import clone_repository, destroy_worker, provision_worker
from products.wizard.backend.temporal.config import (
    CLEANUP_RETRY_POLICY,
    CLEANUP_TIMEOUT,
    EXECUTION_RETRY_POLICY,
    EXECUTION_TIMEOUT,
    FINALIZATION_RETRY_POLICY,
    FINALIZATION_TIMEOUT,
    HANDOFF_RETRY_POLICY,
    HANDOFF_TIMEOUT,
    LOCAL_PACKAGE_PREPARATION_RETRY_POLICY,
    LOCAL_PACKAGE_PREPARATION_TIMEOUT,
    PREPARATION_RETRY_POLICY,
    PREPARATION_TIMEOUT,
    PROVISION_RETRY_POLICY,
    PROVISION_TIMEOUT,
)
from products.wizard.backend.temporal.constants import EXECUTE_WIZARD_RUN_WORKFLOW, wizard_run_workflow_id
from products.wizard.backend.temporal.contracts import (
    PreparedGitRepositoryWorkspace,
    ProvisionedWizardWorker,
    WizardRunActivityInput,
    WizardRunFinalizationActivityInput,
)
from products.wizard.backend.temporal.errors import wizard_run_error_code
from products.wizard.backend.temporal.serializers import deserialize_workflow_input


@workflow.defn(name=EXECUTE_WIZARD_RUN_WORKFLOW)
class ExecuteWizardRunWorkflow(PostHogWorkflow):
    @staticmethod
    def workflow_id_for(run_id: UUID) -> str:
        return wizard_run_workflow_id(run_id)

    @staticmethod
    def parse_inputs(inputs: list[str]) -> WizardRunActivityInput:
        return deserialize_workflow_input(inputs)

    @workflow.run
    async def run(self, input: WizardRunActivityInput) -> None:
        worker: ProvisionedWizardWorker | None = None
        try:
            worker = await workflow.execute_activity(
                provision_worker,
                input,
                start_to_close_timeout=PROVISION_TIMEOUT,
                retry_policy=PROVISION_RETRY_POLICY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )

            if worker is None:
                raise RuntimeError("Wizard Worker provisioning returned no worker.")

            if input.use_local_wizard_source:
                await workflow.execute_activity(
                    prepare_local_wizard,
                    worker,
                    start_to_close_timeout=LOCAL_PACKAGE_PREPARATION_TIMEOUT,
                    retry_policy=LOCAL_PACKAGE_PREPARATION_RETRY_POLICY,
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                )

            workspace = await self._prepare_workspace(worker)

            await workflow.execute_activity(
                execute_wizard,
                workspace,
                start_to_close_timeout=EXECUTION_TIMEOUT,
                retry_policy=EXECUTION_RETRY_POLICY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )

            await workflow.execute_activity(
                create_run_artifacts,
                workspace,
                start_to_close_timeout=HANDOFF_TIMEOUT,
                retry_policy=HANDOFF_RETRY_POLICY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        except asyncio.CancelledError:
            await self._destroy_worker(worker)

            await self._finalize_run(
                WizardRunFinalizationActivityInput(
                    team_id=input.team_id,
                    run_id=input.run_id,
                    status=WizardRunStatus.CANCELLED,
                )
            )
            raise
        except ActivityError as error:
            await self._destroy_worker(worker)

            await self._finalize_run(
                WizardRunFinalizationActivityInput(
                    team_id=input.team_id,
                    run_id=input.run_id,
                    status=WizardRunStatus.FAILED,
                    error_code=wizard_run_error_code(error),
                )
            )
            raise
        except Exception:
            workflow.logger.exception(
                "wizard_run_workflow_failed",
                extra={"team_id": input.team_id, "run_id": str(input.run_id)},
            )
            await self._destroy_worker(worker)

            await self._finalize_run(
                WizardRunFinalizationActivityInput(
                    team_id=input.team_id,
                    run_id=input.run_id,
                    status=WizardRunStatus.FAILED,
                    error_code=WizardRunErrorCode.EXECUTION_FAILED,
                )
            )
            raise
        else:
            await self._destroy_worker(worker)

    @staticmethod
    async def _finalize_run(input: WizardRunFinalizationActivityInput) -> None:
        await workflow.execute_activity(
            finalize_run,
            input,
            start_to_close_timeout=FINALIZATION_TIMEOUT,
            retry_policy=FINALIZATION_RETRY_POLICY,
        )

    @staticmethod
    async def _destroy_worker(worker: ProvisionedWizardWorker | None) -> None:
        if worker is None:
            return
        try:
            await workflow.execute_activity(
                destroy_worker,
                worker,
                start_to_close_timeout=CLEANUP_TIMEOUT,
                retry_policy=CLEANUP_RETRY_POLICY,
            )
        except ActivityError:
            workflow.logger.exception(
                "wizard_worker_cleanup_failed",
                extra={"team_id": worker.team_id, "run_id": str(worker.run_id)},
            )

    @staticmethod
    async def _prepare_workspace(worker: ProvisionedWizardWorker) -> PreparedGitRepositoryWorkspace:
        if worker.workspace_type == WizardWorkspaceType.GIT_REPOSITORY:
            return await workflow.execute_activity(
                clone_repository,
                worker,
                start_to_close_timeout=PREPARATION_TIMEOUT,
                retry_policy=PREPARATION_RETRY_POLICY,
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        raise ValueError(f"Unsupported cloud workspace type: {worker.workspace_type}")
