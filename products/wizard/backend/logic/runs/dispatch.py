from uuid import UUID

from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.logic.runs import (
    cancellation as cancellation_service,
    store,
)
from products.wizard.backend.logic.runs.errors import WizardRunDispatchError
from products.wizard.backend.logic.workers.config import local_wizard_source_root
from products.wizard.backend.observability.contracts import WizardRunDispatchOutcome
from products.wizard.backend.observability.service import wizard_observability
from products.wizard.backend.temporal import client as temporal_client
from products.wizard.backend.temporal.constants import wizard_run_workflow_id
from products.wizard.backend.temporal.contracts import WizardRunActivityInput
from products.wizard.backend.temporal.errors import WizardTemporalError


def dispatch_created_cloud_wizard_run_to_temporal_worker(team_id: int, run_id: UUID) -> None:
    run = store.get_run(team_id, run_id)

    if run.environment != WizardRunEnvironment.CLOUD or run.status != WizardRunStatus.CREATED:
        return

    try:
        temporal_client.start_wizard_run_workflow(
            WizardRunActivityInput(
                team_id=team_id,
                run_id=run_id,
                use_local_wizard_source=local_wizard_source_root() is not None,
            )
        )
    except WizardTemporalError as error:
        # marks the failed dispatch, which returns whether the run has exhausted its retry attempts
        is_exhausted = store.mark_dispatch_failed(team_id, run_id)

        wizard_observability.dispatch_finished(run, WizardRunDispatchOutcome.FAILED)

        raise WizardRunDispatchError(is_exhausted=is_exhausted) from error

    store.mark_dispatch_succeeded(team_id, run_id, wizard_run_workflow_id(run_id))
    if store.cancellation_requested(team_id, run_id):
        cancellation_service.dispatch_cancellation(team_id, run_id)
    wizard_observability.dispatch_finished(run, WizardRunDispatchOutcome.SUCCEEDED)
