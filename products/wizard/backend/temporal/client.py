from uuid import UUID

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from products.wizard.backend.temporal.constants import EXECUTE_WIZARD_RUN_WORKFLOW, wizard_run_workflow_id
from products.wizard.backend.temporal.contracts import WizardRunActivityInput
from products.wizard.backend.temporal.errors import WizardTemporalError

WORKFLOW_RETRY_POLICY = RetryPolicy(maximum_attempts=1)


@async_to_sync
async def start_wizard_run_workflow(input: WizardRunActivityInput) -> None:
    try:
        client = await async_connect()
        await client.start_workflow(
            EXECUTE_WIZARD_RUN_WORKFLOW,
            input,
            id=wizard_run_workflow_id(input.run_id),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            task_queue=settings.WIZARD_TASK_QUEUE,
            retry_policy=WORKFLOW_RETRY_POLICY,
        )
    except WorkflowAlreadyStartedError:
        return
    except (RPCError, RuntimeError) as error:
        raise WizardTemporalError from error


@async_to_sync
async def cancel_wizard_run_workflow(run_id: UUID) -> None:
    try:
        client = await async_connect()
        await client.get_workflow_handle(wizard_run_workflow_id(run_id)).cancel()
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return
        raise WizardTemporalError from error
    except RuntimeError as error:
        raise WizardTemporalError from error
