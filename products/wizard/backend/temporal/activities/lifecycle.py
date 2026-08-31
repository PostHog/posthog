from uuid import UUID

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import WizardRunDTO
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.facade.errors import IllegalStatusTransitionError
from products.wizard.backend.temporal.contracts import WizardRunFinalizationActivityInput


@activity.defn(name="wizard_finalize_run")
@asyncify
def finalize_run(input: WizardRunFinalizationActivityInput) -> None:
    transition_cloud_run(
        input.team_id,
        input.run_id,
        input.status,
        error_code=input.error_code,
    )


def transition_cloud_run(
    team_id: int,
    run_id: UUID,
    status: WizardRunStatus,
    *,
    error_code: str | None = None,
) -> None:
    current = _get_cloud_run(team_id, run_id)
    if _matches(current, status, error_code):
        return

    try:
        wizard_facade.update_run_status(team_id, run_id, status, error_code=error_code)
    except IllegalStatusTransitionError:
        current = _get_cloud_run(team_id, run_id)
        if _matches(current, status, error_code):
            return
        raise


def _get_cloud_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    run = wizard_facade.get_run(team_id, run_id)
    if run.environment != WizardRunEnvironment.CLOUD:
        raise ValueError("Wizard Run transitions require a cloud Wizard Run.")
    return run


def _matches(
    run: WizardRunDTO,
    status: WizardRunStatus,
    error_code: str | None,
) -> bool:
    return run.status == status and run.error_code == error_code
