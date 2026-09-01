import logging
from dataclasses import replace
from functools import partial
from uuid import UUID

from django.db import transaction as database_transaction

from posthog.models import Team, User

from products.wizard.backend.facade.config import DEFAULT_WIZARD_VERSION
from products.wizard.backend.facade.contracts import (
    CreateWizardRunInput,
    GitRepositoryWorkspace,
    ListWizardRunsInput,
    LocalFolderWorkspace,
    WizardRunCreationResult,
    WizardRunDTO,
    WizardRunPage,
)
from products.wizard.backend.facade.enums import (
    WizardRunEnvironment,
    WizardRunErrorCode,
    WizardRunStage,
    WizardRunStatus,
)
from products.wizard.backend.facade.errors import (
    IllegalStatusTransitionError,
    InvalidWorkspaceEnvironmentError,
    MissingWizardRunIdempotencyKeyError,
    WizardProgramEnvironmentNotSupportedError,
    WizardRunIdempotencyConflictError,
)
from products.wizard.backend.logic import registry as registry_service
from products.wizard.backend.logic.runs import (
    cancellation as cancellation_service,
    store,
)
from products.wizard.backend.logic.runs.admission import enforce_cloud_run_creation_policy
from products.wizard.backend.logic.runs.dispatch import dispatch_created_cloud_wizard_run_to_temporal_worker
from products.wizard.backend.logic.runs.errors import WizardRunDispatchError
from products.wizard.backend.logic.runs.fingerprints import create_run_request_fingerprint
from products.wizard.backend.logic.runs.repository_access import authorize_git_repository_access
from products.wizard.backend.logic.runs.transitions import transition
from products.wizard.backend.observability.service import wizard_observability as run_observability

logger = logging.getLogger(__name__)


def create_run(params: CreateWizardRunInput) -> WizardRunDTO:
    return create_run_with_result(params).run


def create_run_with_result(params: CreateWizardRunInput) -> WizardRunCreationResult:
    match params.environment, params.workspace:
        case WizardRunEnvironment.LOCAL, LocalFolderWorkspace():
            pass
        case WizardRunEnvironment.CLOUD, GitRepositoryWorkspace():
            pass
        case _:
            raise InvalidWorkspaceEnvironmentError

    request_fingerprint: str | None = None
    is_cloud_run = params.environment == WizardRunEnvironment.CLOUD

    if is_cloud_run:
        if params.idempotency_key is None:
            raise MissingWizardRunIdempotencyKeyError

        request_fingerprint = create_run_request_fingerprint(params)

        existing = store.get_run_by_idempotency_key(params.team_id, params.idempotency_key)

        if existing is not None:
            if store.get_request_fingerprint(params.team_id, existing.id) != request_fingerprint:
                raise WizardRunIdempotencyConflictError

            return WizardRunCreationResult(run=existing, created=False)

    user = User.objects.only("distinct_id").get(id=params.created_by_id)
    team = Team.objects.only("organization_id").get(id=params.team_id)

    program = registry_service.get_program(
        program_id=params.program_id,
        distinct_id=user.distinct_id,
        organization_id=str(team.organization_id),
    )

    program = replace(program, wizard_version=params.wizard_version or DEFAULT_WIZARD_VERSION)

    if params.environment not in program.supported_environments:
        raise WizardProgramEnvironmentNotSupportedError

    if isinstance(params.workspace, GitRepositoryWorkspace):
        authorize_git_repository_access(params.team_id, params.workspace.repository)

    initial_status = (
        WizardRunStatus.RUNNING if params.environment == WizardRunEnvironment.LOCAL else WizardRunStatus.CREATED
    )

    with database_transaction.atomic():
        if is_cloud_run:
            enforce_cloud_run_creation_policy(params.team_id, params.created_by_id, params.idempotency_key)

        result = store.create_run(
            team_id=params.team_id,
            created_by_id=params.created_by_id,
            environment=params.environment,
            workspace=params.workspace,
            program=program,
            status=initial_status,
            idempotency_key=params.idempotency_key,
            request_fingerprint=request_fingerprint,
        )

        if not result.created and store.get_request_fingerprint(params.team_id, result.run.id) != request_fingerprint:
            raise WizardRunIdempotencyConflictError

        should_dispatch_wizard_run = is_cloud_run and result.created

        if should_dispatch_wizard_run:
            database_transaction.on_commit(
                partial(
                    _dispatch_cloud_run,
                    params.team_id,
                    result.run.id,
                ),
            )

    if is_cloud_run:
        result = WizardRunCreationResult(run=store.get_run(params.team_id, result.run.id), created=result.created)

    if result.created and not is_cloud_run:
        run_observability.run_created(result.run)

    return result


def _dispatch_cloud_run(team_id: int, run_id: UUID) -> None:
    run_observability.run_created(store.get_run(team_id, run_id))

    try:
        dispatch_created_cloud_wizard_run_to_temporal_worker(team_id, run_id)

    except WizardRunDispatchError as error:
        logger.exception(
            "wizard_run_dispatch_failed",
            extra={"team_id": team_id, "run_id": str(run_id), "exhausted": error.exhausted},
        )
        if error.exhausted:
            fail_run(team_id, run_id, error_code=WizardRunErrorCode.DISPATCH_FAILED.value)


def get_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    return store.get_run(team_id, run_id)


def list_runs(params: ListWizardRunsInput) -> WizardRunPage:
    return store.list_runs(params)


def start_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    return transition_run(team_id, run_id, WizardRunStatus.RUNNING)


def complete_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    return transition_run(team_id, run_id, WizardRunStatus.COMPLETED)


def fail_run(
    team_id: int,
    run_id: UUID,
    *,
    error_code: str | None = None,
) -> WizardRunDTO:
    return transition_run(team_id, run_id, WizardRunStatus.FAILED, error_code=error_code)


def cancel_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    with database_transaction.atomic():
        run = store.get_run_for_update(team_id, run_id)
        previous = run
        next_status = transition(run.status, WizardRunStatus.CANCELLED)
        run = store.set_run_status(team_id, run_id, next_status, None)

        if previous.environment == WizardRunEnvironment.CLOUD:
            # Persist the cancellation intent in the same transaction as the status, so a crash
            # before dispatch still leaves the run in the recovery index. Send the Temporal cancel
            # only after the commit, since it is an external side effect.
            store.mark_cancellation_requested(team_id, run_id)
            database_transaction.on_commit(partial(cancellation_service.dispatch_cancellation, team_id, run_id))

    run_observability.run_transitioned(previous, run)
    return run


def request_cloud_run_cancellation(team_id: int, run_id: UUID) -> None:
    store.mark_cancellation_requested(team_id, run_id)
    cancellation_service.dispatch_cancellation(team_id, run_id)


def update_run_stage(team_id: int, run_id: UUID, stage: WizardRunStage) -> WizardRunDTO:
    with database_transaction.atomic():
        run = store.get_run_for_update(team_id, run_id)
        previous = run

        if run.status not in (WizardRunStatus.CREATED, WizardRunStatus.RUNNING):
            raise IllegalStatusTransitionError

        if run.stage == stage:
            return run

        run = store.set_run_stage(team_id, run_id, stage)

    run_observability.stage_changed(previous, run)

    return run


def transition_run(
    team_id: int,
    run_id: UUID,
    next_status: WizardRunStatus,
    *,
    error_code: str | None = None,
) -> WizardRunDTO:
    with database_transaction.atomic():
        run = store.get_run_for_update(team_id, run_id)
        previous = run
        next_status = transition(run.status, next_status, error_code=error_code)
        run = store.set_run_status(team_id, run_id, next_status, error_code)

    run_observability.run_transitioned(previous, run)
    return run
