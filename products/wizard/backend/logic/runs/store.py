import logging
from uuid import UUID

from django.db import (
    models,
    transaction as database_transaction,
)
from django.utils import timezone

from products.wizard.backend.facade.config import WIZARD_RUN_DEADLINE
from products.wizard.backend.facade.contracts import (
    ListWizardRunsInput,
    WizardProgram,
    WizardRunCreationResult,
    WizardRunDTO,
    WizardRunPage,
    WizardWorkspace,
)
from products.wizard.backend.facade.enums import (
    WizardRunDispatchStatus,
    WizardRunEnvironment,
    WizardRunStage,
    WizardRunStatus,
)
from products.wizard.backend.facade.errors import WizardRunNotFoundError
from products.wizard.backend.logic.programs import program_to_mapping
from products.wizard.backend.logic.runs.config import (
    DISPATCH_RETRY_BASE_DELAY,
    DISPATCH_RETRY_MAX_ATTEMPTS,
    DISPATCH_RETRY_MAX_DELAY,
)
from products.wizard.backend.logic.runs.diagnostics import error_message
from products.wizard.backend.logic.runs.mappers import record_to_run, workspace_to_record
from products.wizard.backend.models import WizardRun

logger = logging.getLogger(__name__)


def _get_run_record(team_id: int, run_id: UUID) -> WizardRun:
    run = WizardRun.objects.for_team(team_id).filter(id=run_id).first()

    if run is None:
        raise WizardRunNotFoundError

    return run


def create_run(
    *,
    team_id: int,
    created_by_id: int,
    environment: WizardRunEnvironment,
    workspace: WizardWorkspace,
    program: WizardProgram,
    status: WizardRunStatus,
    idempotency_key: str | None = None,
    request_fingerprint: str | None = None,
) -> WizardRunCreationResult:
    workspace_type, workspace_metadata = workspace_to_record(workspace)
    now = timezone.now()

    values = {
        "created_by_id": created_by_id,
        "environment": environment.value,
        "workspace_type": workspace_type.value,
        "workspace": workspace_metadata,
        "program": program_to_mapping(program),
        "status": status.value,
        "request_fingerprint": request_fingerprint,
        "dispatch_status": (
            WizardRunDispatchStatus.PENDING.value if environment == WizardRunEnvironment.CLOUD else None
        ),
        "stage": WizardRunStage.DISPATCHING.value if environment == WizardRunEnvironment.CLOUD else None,
        "stage_started_at": now if environment == WizardRunEnvironment.CLOUD else None,
        "started_at": now if environment == WizardRunEnvironment.LOCAL else None,
        "deadline_at": now + WIZARD_RUN_DEADLINE if environment == WizardRunEnvironment.CLOUD else None,
    }

    if idempotency_key is None:
        run = WizardRun.objects.for_team(team_id).create(team_id=team_id, idempotency_key=None, **values)
        return WizardRunCreationResult(run=record_to_run(run), created=True)

    run, created = WizardRun.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        idempotency_key=idempotency_key,
        defaults=values,
    )

    return WizardRunCreationResult(run=record_to_run(run), created=created)


def get_run_by_idempotency_key(team_id: int, idempotency_key: str) -> WizardRunDTO | None:
    run = WizardRun.objects.for_team(team_id).filter(idempotency_key=idempotency_key).first()

    return record_to_run(run) if run is not None else None


def get_request_fingerprint(team_id: int, run_id: UUID) -> str | None:
    return _get_run_record(team_id, run_id).request_fingerprint


def get_workflow_id(team_id: int, run_id: UUID) -> str | None:
    return _get_run_record(team_id, run_id).workflow_id


def mark_cancellation_requested(team_id: int, run_id: UUID) -> None:
    WizardRun.objects.for_team(team_id).filter(id=run_id).update(cancellation_requested_at=timezone.now())


def mark_cancellation_dispatched(team_id: int, run_id: UUID) -> None:
    WizardRun.objects.for_team(team_id).filter(id=run_id).update(cancellation_dispatched_at=timezone.now())


def mark_dispatch_succeeded(team_id: int, run_id: UUID, workflow_id: str) -> None:
    WizardRun.objects.for_team(team_id).filter(id=run_id).update(
        dispatch_status=WizardRunDispatchStatus.DISPATCHED.value,
        dispatch_attempts=models.F("dispatch_attempts") + 1,
        dispatch_error=None,
        dispatch_next_attempt_at=None,
        workflow_id=workflow_id,
    )


def mark_dispatch_failed(team_id: int, run_id: UUID) -> bool:
    with database_transaction.atomic():
        run = WizardRun.objects.for_team(team_id).select_for_update().filter(id=run_id).first()
        if run is None:
            raise WizardRunNotFoundError

        run.dispatch_attempts += 1
        run.dispatch_error = "Temporal dispatch failed."
        exhausted = run.dispatch_attempts >= DISPATCH_RETRY_MAX_ATTEMPTS

        if exhausted:
            run.dispatch_next_attempt_at = None
        else:
            retry_delay = min(
                DISPATCH_RETRY_BASE_DELAY * 2 ** (run.dispatch_attempts - 1),
                DISPATCH_RETRY_MAX_DELAY,
            )
            run.dispatch_next_attempt_at = timezone.now() + retry_delay

        run.save(update_fields=["dispatch_attempts", "dispatch_error", "dispatch_next_attempt_at", "updated_at"])
        return exhausted


def set_run_stage(team_id: int, run_id: UUID, stage: WizardRunStage) -> WizardRunDTO:
    run = _get_run_record(team_id, run_id)

    run.stage = stage.value
    run.stage_started_at = timezone.now()
    run.save(update_fields=["stage", "stage_started_at", "updated_at"])

    return record_to_run(run)


def get_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    return record_to_run(_get_run_record(team_id, run_id))


def get_run_for_update(team_id: int, run_id: UUID) -> WizardRunDTO:
    run = WizardRun.objects.for_team(team_id).select_for_update().filter(id=run_id).first()
    if run is None:
        raise WizardRunNotFoundError

    return record_to_run(run)


def list_runs(params: ListWizardRunsInput) -> WizardRunPage:
    runs = WizardRun.objects.for_team(params.team_id).order_by("-created_at")
    page = runs[params.offset : params.offset + params.limit]
    results: list[WizardRunDTO] = []
    for run in page:
        try:
            results.append(record_to_run(run))
        except ValueError:
            logger.exception(
                "wizard_run_deserialization_failed",
                extra={"team_id": params.team_id, "run_id": str(run.id)},
            )
    return WizardRunPage(results=tuple(results), count=runs.count())


def set_run_status(
    team_id: int,
    run_id: UUID,
    status: WizardRunStatus,
    error_code: str | None,
) -> WizardRunDTO:
    run = _get_run_record(team_id, run_id)
    run.status = status.value
    run.error_code = error_code
    run.error_message = error_message(error_code)

    update_fields = ["status", "error_code", "error_message", "updated_at"]

    now = timezone.now()

    if status == WizardRunStatus.RUNNING and run.started_at is None:
        run.started_at = now
        update_fields.append("started_at")

    if status in (WizardRunStatus.COMPLETED, WizardRunStatus.FAILED, WizardRunStatus.CANCELLED):
        run.finished_at = now
        run.stage = None
        run.stage_started_at = None
        update_fields.extend(["finished_at", "stage", "stage_started_at"])

    run.save(update_fields=update_fields)

    return record_to_run(run)
