from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify

from products.wizard.backend.logic.workers import service as cloud_worker
from products.wizard.backend.logic.workers.config import local_wizard_source_root
from products.wizard.backend.logic.workers.local_package import InvalidLocalWizardSourceError
from products.wizard.backend.temporal.activities.errors import (
    WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
    WIZARD_WORKER_EXECUTION_ERROR_TYPE,
)
from products.wizard.backend.temporal.contracts import ProvisionedWizardWorker


@activity.defn(name="wizard_prepare_local_package")
@asyncify
def prepare_local_wizard(input: ProvisionedWizardWorker) -> None:
    source_root = local_wizard_source_root()
    if not input.use_local_wizard_source or source_root is None:
        raise ApplicationError(
            "Local Wizard source is not available.",
            type=WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
            non_retryable=True,
        )

    try:
        cloud_worker.prepare_local_wizard(input.sandbox_id, source_root)
    except InvalidLocalWizardSourceError as error:
        raise ApplicationError(
            str(error),
            type=WIZARD_RUN_CONFIGURATION_ERROR_TYPE,
            non_retryable=True,
        ) from error
    except cloud_worker.WizardWorkerExecutionError as error:
        raise ApplicationError(
            str(error),
            type=WIZARD_WORKER_EXECUTION_ERROR_TYPE,
            non_retryable=True,
        ) from error
