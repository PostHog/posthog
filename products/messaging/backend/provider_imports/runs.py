"""Start provider import runs, run their steps page by page, and record the outcome."""

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.event_usage import report_team_action
from posthog.models import Team

from products.messaging.backend.models.provider_import_run import (
    ACTIVE_IMPORT_STATUSES,
    ImportStepStatus,
    ProviderImportRun,
    ProviderImportStatus,
)
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportPage,
    ImportProvider,
    ImportStepError,
    StepCheckpoint,
)
from products.messaging.backend.provider_imports.registry import get_provider
from products.messaging.backend.temporal.client import RUN_EXECUTION_TIMEOUT, start_provider_import_workflow

logger = logging.getLogger(__name__)

# A run still active after the workflow's execution timeout has no workflow left to finish it.
STALE_RUN_AGE = RUN_EXECUTION_TIMEOUT + timedelta(hours=1)
MAX_STEP_WARNINGS = 50
UNEXPECTED_ERROR_MESSAGE = "An unexpected error interrupted this step."


class ProviderImportAlreadyRunning(Exception):
    pass


class InvalidImportSteps(Exception):
    pass


class ImportRunClosed(Exception):
    """The run already ended, for example because its workflow failed to start. Its steps must not import."""


class StaleImportAttempt(Exception):
    """A newer attempt of the step took over, so this attempt must stop without writing."""


@frozen
class _StepClaim:
    completed: bool
    checkpoint: StepCheckpoint | None


def start_run(
    team_id: int, provider_key: str, steps: list[str], api_key: str | None, created_by_id: int | None
) -> ProviderImportRun:
    """Check the credentials, claim a queued run, store the credentials, and start the run's workflow.

    Raises UnknownImportProvider, InvalidImportSteps, ProviderImportAlreadyRunning, the ImportCredentials* errors and
    ImportProviderUnavailable.
    """
    provider = get_provider(provider_key)
    ordered_steps = _order_steps(provider, steps)

    _fail_stale_runs(team_id)
    if _runs(team_id).filter(provider=provider.key, status__in=ACTIVE_IMPORT_STATUSES).exists():
        raise ProviderImportAlreadyRunning(f"A {provider.label} import is already running.")

    credentials = provider.check_credentials(team_id, api_key)
    try:
        with transaction.atomic():
            # Create the run before storing the credentials. A concurrent start then waits on the active-run index
            # and fails, so only the request that owns the run stores its key.
            run = _runs(team_id).create(
                team_id=team_id,
                provider=provider.key,
                steps=ordered_steps,
                created_by_id=created_by_id,
                progress={step: _new_step_progress() for step in ordered_steps},
            )
            run.integration_id = provider.store_credentials(team_id, credentials, created_by_id)
            run.save(update_fields=["integration"])
    except IntegrityError as e:
        raise ProviderImportAlreadyRunning(f"A {provider.label} import is already running.") from e

    try:
        start_provider_import_workflow(team_id=team_id, run_id=run.id, steps=ordered_steps)
    except Exception:
        # A queued run without a workflow would block every later import until it goes stale. If Temporal started
        # the workflow but the response got lost, its steps find the run closed and import nothing.
        _close_run(team_id, run.id)
        raise
    return run


def run_step(team_id: int, run_id: UUID, step: str, attempt: int) -> None:
    """Run one step from its saved checkpoint, and save each page together with the step's progress.

    `attempt` is the Temporal attempt number. An older attempt can keep running after Temporal starts a newer one,
    so each page write checks that its attempt still owns the step.
    """
    run = _runs(team_id).get(id=run_id)
    provider = get_provider(run.provider)
    claim = _claim_step(team_id, run_id, step, attempt)
    if claim.completed:
        return

    context = ImportContext(team_id=team_id, created_by_id=run.created_by_id, integration_id=run.integration_id)
    try:
        for page in provider.run_step(step, context, claim.checkpoint):
            _save_page(team_id, run_id, step, attempt, page)
            if page.checkpoint is None:
                return
        _update_owned_step(team_id, run_id, step, attempt, _mark_completed)
    except (StaleImportAttempt, ImportRunClosed):
        raise
    except Exception as e:
        if not isinstance(e, ImportStepError):
            logger.exception("Provider import step failed", extra={"run_id": str(run_id), "step": step})
        last_error = str(e)[:500] if isinstance(e, ImportStepError) else UNEXPECTED_ERROR_MESSAGE
        try:
            _update_owned_step(team_id, run_id, step, attempt, lambda progress: progress.update(last_error=last_error))
        except (StaleImportAttempt, ImportRunClosed):
            pass
        raise


def finish_run(team_id: int, run_id: UUID) -> None:
    """Fail the steps that did not complete, and set the run's final status. A run that already ended stays as it is."""
    _close_run(team_id, run_id)


def list_runs(team_id: int, limit: int) -> list[ProviderImportRun]:
    _fail_stale_runs(team_id)
    return list(_runs(team_id).order_by("-created_at")[:limit])


def get_run(team_id: int, run_id: UUID) -> ProviderImportRun | None:
    _fail_stale_runs(team_id)
    return _runs(team_id).filter(id=run_id).first()


def _runs(team_id: int) -> QuerySet[ProviderImportRun]:
    return ProviderImportRun.objects.for_team(team_id)


def _order_steps(provider: ImportProvider, steps: list[str]) -> list[str]:
    known = [spec.key for spec in provider.steps]
    unknown = sorted(set(steps) - set(known))
    if unknown:
        raise InvalidImportSteps(f"{provider.label} has no step named {', '.join(unknown)}.")
    if not steps:
        raise InvalidImportSteps("Select at least one thing to import.")
    return [key for key in known if key in steps]


def _fail_stale_runs(team_id: int) -> None:
    stale_ids = list(
        _runs(team_id)
        .filter(status__in=ACTIVE_IMPORT_STATUSES, created_at__lt=timezone.now() - STALE_RUN_AGE)
        .values_list("id", flat=True)
    )
    for run_id in stale_ids:
        _close_run(team_id, run_id)


def _close_run(team_id: int, run_id: UUID) -> None:
    with transaction.atomic():
        run = _runs(team_id).select_for_update().get(id=run_id)
        if run.status not in ACTIVE_IMPORT_STATUSES:
            return
        for step in run.steps:
            progress = run.progress.setdefault(step, _new_step_progress())
            if progress["status"] != ImportStepStatus.COMPLETED:
                progress["status"] = ImportStepStatus.FAILED
        completed = all(run.progress[step]["status"] == ImportStepStatus.COMPLETED for step in run.steps)
        run.status = ProviderImportStatus.COMPLETED if completed else ProviderImportStatus.FAILED
        run.finished_at = timezone.now()
        run.save(update_fields=["progress", "status", "finished_at"])

    _report_finished(run)


def _claim_step(team_id: int, run_id: UUID, step: str, attempt: int) -> _StepClaim:
    with transaction.atomic():
        run = _runs(team_id).select_for_update().get(id=run_id)
        if run.status not in ACTIVE_IMPORT_STATUSES:
            raise ImportRunClosed(f"Import run {run_id} already ended.")
        progress = run.progress.setdefault(step, _new_step_progress())
        if progress["status"] == ImportStepStatus.COMPLETED:
            return _StepClaim(completed=True, checkpoint=None)
        progress.update(status=ImportStepStatus.RUNNING.value, attempt=attempt)
        update_fields = ["progress"]
        if run.status == ProviderImportStatus.QUEUED:
            run.status = ProviderImportStatus.RUNNING
            run.started_at = timezone.now()
            update_fields += ["status", "started_at"]
        run.save(update_fields=update_fields)
        return _StepClaim(completed=False, checkpoint=progress.get("checkpoint"))


def _save_page(team_id: int, run_id: UUID, step: str, attempt: int, page: ImportPage) -> None:
    with transaction.atomic():
        run, progress = _lock_owned_step(team_id, run_id, step, attempt)
        saved = page.save()
        progress["processed"] += page.processed
        progress["imported"] += saved.imported
        progress["warnings"] = (progress["warnings"] + list(saved.warnings))[:MAX_STEP_WARNINGS]
        progress["checkpoint"] = page.checkpoint
        if page.checkpoint is None:
            _mark_completed(progress)
        run.save(update_fields=["progress"])


def _update_owned_step(
    team_id: int, run_id: UUID, step: str, attempt: int, change: Callable[[dict[str, Any]], None]
) -> None:
    with transaction.atomic():
        run, progress = _lock_owned_step(team_id, run_id, step, attempt)
        change(progress)
        run.save(update_fields=["progress"])


def _lock_owned_step(team_id: int, run_id: UUID, step: str, attempt: int) -> tuple[ProviderImportRun, dict[str, Any]]:
    run = _runs(team_id).select_for_update().get(id=run_id)
    if run.status not in ACTIVE_IMPORT_STATUSES:
        raise ImportRunClosed(f"Import run {run_id} ended while step {step} was running.")
    progress = run.progress.setdefault(step, _new_step_progress())
    if progress.get("attempt") != attempt:
        raise StaleImportAttempt(f"Attempt {attempt} of step {step} no longer owns import run {run_id}.")
    return run, progress


def _new_step_progress() -> dict[str, Any]:
    return {
        "status": ImportStepStatus.PENDING.value,
        "processed": 0,
        "imported": 0,
        "warnings": [],
        "last_error": None,
        "checkpoint": None,
        "attempt": None,
    }


def _mark_completed(progress: dict[str, Any]) -> None:
    progress.update(status=ImportStepStatus.COMPLETED.value, last_error=None, checkpoint=None)


def _report_finished(run: ProviderImportRun) -> None:
    try:
        report_team_action(
            Team.objects.get(id=run.team_id),
            "messaging provider import finished",
            {
                "provider": run.provider,
                "status": run.status,
                "steps": run.steps,
                "duration_seconds": int((run.finished_at - run.created_at).total_seconds())
                if run.finished_at
                else None,
                **{f"{step}_status": run.progress[step]["status"] for step in run.steps},
                **{f"{step}_imported": run.progress[step]["imported"] for step in run.steps},
            },
        )
    except Exception:
        logger.exception("Failed to report the provider import outcome")
