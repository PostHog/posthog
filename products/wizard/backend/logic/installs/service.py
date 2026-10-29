from uuid import UUID, uuid4

from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    StartWizardInstallInput,
    WizardInstallStatusDTO,
    WizardRunCreationResult,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment
from products.wizard.backend.facade.errors import RepositoryNotAccessibleError, WizardRunNotFoundError
from products.wizard.backend.logic.artifacts import store as artifacts_store
from products.wizard.backend.logic.installs.next_step import next_step
from products.wizard.backend.logic.registry.config import POSTHOG_INTEGRATION_PROGRAM
from products.wizard.backend.logic.runs import lifecycle, store
from products.wizard.backend.logic.runs.repository_access import refresh_repository_cache
from products.wizard.backend.logic.runs.validation import validate_git_branch_name, validate_git_repository_name
from products.wizard.backend.observability.tracing import wizard_span


@wizard_span("wizard.install.start")
def start_install(params: StartWizardInstallInput) -> WizardRunCreationResult:
    validate_git_repository_name(params.repository)
    if params.branch is not None:
        validate_git_branch_name(params.branch)

    run_params = CreateWizardRunInput(
        team_id=params.team_id,
        created_by_id=params.created_by_id,
        environment=WizardRunEnvironment.CLOUD,
        workspace=GitRepositoryWorkspace(repository=params.repository, branch=params.branch),
        program_id=POSTHOG_INTEGRATION_PROGRAM.id,
        idempotency_key=params.idempotency_key or f"install-{uuid4()}",
    )

    try:
        return lifecycle.create_run_with_result(run_params)
    except RepositoryNotAccessibleError:
        if not refresh_repository_cache(params.team_id):
            raise
        return lifecycle.create_run_with_result(run_params)


def get_install_status(team_id: int, run_id: UUID) -> WizardInstallStatusDTO:
    run = store.get_run(team_id, run_id)
    if run.environment != WizardRunEnvironment.CLOUD:
        raise WizardRunNotFoundError

    pull_request_url = artifacts_store.get_pull_request_url(team_id, run.id)

    return WizardInstallStatusDTO(
        run=run, pull_request_url=pull_request_url, next_step=next_step(run, pull_request_url)
    )
