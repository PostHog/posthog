from uuid import UUID, uuid4

from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    StartWizardInstallInput,
    WizardInstallStatusDTO,
    WizardRunCreationResult,
    WizardRunPullRequestArtifactDTO,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment
from products.wizard.backend.facade.errors import WizardRunNotFoundError
from products.wizard.backend.logic.artifacts import service as artifacts
from products.wizard.backend.logic.installs.config import INSTALL_PROGRAM_ID
from products.wizard.backend.logic.installs.next_step import next_step
from products.wizard.backend.logic.installs.rate_limits import release_token_daily_run, reserve_token_daily_run
from products.wizard.backend.logic.runs import lifecycle, store
from products.wizard.backend.logic.runs.repository_access import authorize_git_repository_access
from products.wizard.backend.logic.runs.validation import validate_git_branch_name, validate_git_repository_name
from products.wizard.backend.observability.tracing import wizard_span


@wizard_span("wizard.install.start")
def start_install(params: StartWizardInstallInput) -> WizardRunCreationResult:
    validate_git_repository_name(params.repository)
    if params.branch is not None:
        validate_git_branch_name(params.branch)

    idempotency_key = params.idempotency_key or f"install-{uuid4()}"
    run_params = CreateWizardRunInput(
        team_id=params.team_id,
        created_by_id=params.created_by_id,
        environment=WizardRunEnvironment.CLOUD,
        workspace=GitRepositoryWorkspace(repository=params.repository, branch=params.branch),
        program_id=INSTALL_PROGRAM_ID,
        idempotency_key=idempotency_key,
        one_active_run_per_project=True,
    )

    if store.get_run_by_idempotency_key(params.team_id, idempotency_key) is not None:
        # A retry of a request that already created its run: return that run without spending more quota.
        return lifecycle.create_run_with_result(run_params)

    authorize_git_repository_access(params.team_id, params.repository, refresh_cache_on_miss=True)

    counter_key = reserve_token_daily_run(params.created_by_id) if params.counts_against_token_daily_limit else None
    try:
        result = lifecycle.create_run_with_result(run_params)
    except Exception:
        if counter_key is not None:
            release_token_daily_run(counter_key)
        raise

    if counter_key is not None and not result.created:
        release_token_daily_run(counter_key)

    return result


def get_install_status(team_id: int, run_id: UUID) -> WizardInstallStatusDTO:
    run = store.get_run(team_id, run_id)
    if run.environment != WizardRunEnvironment.CLOUD:
        raise WizardRunNotFoundError

    pull_request = next(
        (
            artifact
            for artifact in artifacts.list_run_artifacts(team_id, run.id)
            if isinstance(artifact, WizardRunPullRequestArtifactDTO)
        ),
        None,
    )
    pull_request_url = pull_request.url if pull_request is not None else None

    return WizardInstallStatusDTO(
        run=run, pull_request_url=pull_request_url, next_step=next_step(run, pull_request_url)
    )
