from datetime import timedelta
from enum import StrEnum

from temporalio import workflow
from temporalio.common import RetryPolicy

from products.tasks.backend.temporal.constants import CREDENTIAL_REFRESH_INITIAL_DELAY

from .activities.get_task_processing_context import TaskProcessingContext
from .activities.refresh_sandbox_credentials import RefreshSandboxCredentialsInput, refresh_sandbox_credentials


class CredentialRefreshExitReason(StrEnum):
    SANDBOX_GONE = "sandbox_gone"
    CREDENTIALS_UNAVAILABLE = "credentials_unavailable"


SANDBOX_GONE_ERROR_MESSAGE = "Sandbox stopped; resume to continue"


async def run_credential_refresh_loop(context: TaskProcessingContext, sandbox_id: str) -> CredentialRefreshExitReason:
    """Periodically re-inject fresh credentials into the running sandbox.

    Sandbox credentials (GitHub token; user *or* installation, per authorship)
    are frozen into ``.git/config`` and the agentsh env file at boot/resume and
    expire while the sandbox stays warm. This loop re-applies them in place on a
    token-aware cadence so ``git``/``gh`` auth never lapses mid-run. Runs
    concurrently with the agent and is cancelled on completion. Shared by the
    ``process_task`` and ``execute_sandbox`` workflows.
    """
    next_refresh_seconds = CREDENTIAL_REFRESH_INITIAL_DELAY.total_seconds()
    exclude_kinds: list[str] = []
    while True:
        await workflow.sleep(next_refresh_seconds)
        try:
            result = await workflow.execute_activity(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=context, sandbox_id=sandbox_id, exclude_kinds=exclude_kinds),
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            if result.sandbox_gone:
                workflow.logger.info("Stopping credential refresh loop: sandbox is gone")
                return CredentialRefreshExitReason.SANDBOX_GONE
            for kind in result.orphaned_kinds:
                if kind not in exclude_kinds:
                    exclude_kinds.append(kind)
            if result.no_credentials_left:
                workflow.logger.info("Stopping credential refresh loop: no refreshable credentials left")
                return CredentialRefreshExitReason.CREDENTIALS_UNAVAILABLE
            next_refresh_seconds = result.next_refresh_seconds
        except Exception as e:
            # Non-fatal: keep the run alive and retry on the default cadence.
            workflow.logger.warning(f"Sandbox credential refresh failed (non-fatal): {e}")
            next_refresh_seconds = CREDENTIAL_REFRESH_INITIAL_DELAY.total_seconds()
