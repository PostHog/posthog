"""Start provider import runs, run their steps page by page, and record the outcome."""

import logging
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from posthog.event_usage import report_team_action
from posthog.models import Team

from products.messaging.backend.models.provider_import_run import (
    ACTIVE_IMPORT_STATUSES,
    ImportStepStatus,
    ProviderImportRun,
    ProviderImportStatus,
)
from products.messaging.backend.provider_imports.base import ImportContext, ImportPage, ImportProvider
from products.messaging.backend.provider_imports.registry import get_provider
from products.messaging.backend.temporal.client import RUN_EXECUTION_TIMEOUT, start_provider_import_workflow

logger = logging.getLogger(__name__)

# A run still active after the workflow's execution timeout has no workflow left to finish it.
STALE_RUN_AGE = RUN_EXECUTION_TIMEOUT + timedelta(hours=1)
MAX_STEP_WARNINGS = 50


class ProviderImportAlreadyRunning(Exception):
    pass


class InvalidImportSteps(Exception):
    pass


def start_run(
    team_id: int, provider_key: str, steps: list[str], api_key: str | None, created_by_id: int | None
) -> ProviderImportRun:
    """Check the credentials, create a queued run, and start its workflow.

    Raises UnknownImportProvider, InvalidImportSteps, ProviderImportAlreadyRunning and the ImportCredentials* errors.
    """
    provider = get_provider(provider_key)
    ordered_steps = _order_steps(provider, steps)

    _fail_stale_runs(team_id)
    if _runs(team_id).filter(provider=provider.key, status__in=ACTIVE_IMPORT_STATUSES).exists():
        raise ProviderImportAlreadyRunning(f"A {provider.label} import is already running.")

    integration_id = provider.save_credentials(team_id, api_key, created_by_id)
    try:
        with transaction.atomic():
            run = _runs(team_id).create(
                team_id=team_id,
                provider=provider.key,
                integration_id=integration_id,
                steps=ordered_steps,
                created_by_id=created_by_id,
                progress={step: _new_step_progress() for step in ordered_steps},
            )
    except IntegrityError as e:
        raise ProviderImportAlreadyRunning(f"A {provider.label} import is already running.") from e

    try:
        start_provider_import_workflow(team_id=team_id, run_id=run.id, steps=ordered_steps)
    except Exception:
        # A queued run without a workflow would block every later import until it goes stale.
        _runs(team_id).filter(id=run.id).update(status=ProviderImportStatus.FAILED, finished_at=timezone.now())
        raise
    return run


def run_step(team_id: int, run_id: UUID, step: str) -> None:
    """Run one step of a run, from the checkpoint a failed attempt saved, and save progress after each page."""
    run = _runs(team_id).get(id=run_id)
    provider = get_provider(run.provider)
    checkpoint = run.progress.get(step, {}).get("checkpoint")
    _update_step(team_id, run_id, step, _mark_running)

    context = ImportContext(team_id=team_id, created_by_id=run.created_by_id, integration_id=run.integration_id)
    try:
        for page in provider.run_step(step, context, checkpoint):
            _update_step(team_id, run_id, step, partial(_add_page, page=page))
    except Exception as e:
        last_error = str(e)[:500]
        _update_step(team_id, run_id, step, lambda progress: progress.update(last_error=last_error))
        raise

    _update_step(team_id, run_id, step, _mark_completed)


def finish_run(team_id: int, run_id: UUID) -> None:
    """Fail the steps that did not complete, and set the run's final status."""
    with transaction.atomic():
        run = _runs(team_id).select_for_update().get(id=run_id)
        for step in run.steps:
            progress = run.progress.setdefault(step, _new_step_progress())
            if progress["status"] != ImportStepStatus.COMPLETED:
                progress["status"] = ImportStepStatus.FAILED
        completed = all(run.progress[step]["status"] == ImportStepStatus.COMPLETED for step in run.steps)
        run.status = ProviderImportStatus.COMPLETED if completed else ProviderImportStatus.FAILED
        run.finished_at = timezone.now()
        run.save(update_fields=["progress", "status", "finished_at"])

    _report_finished(run)


def list_runs(team_id: int, limit: int) -> list[ProviderImportRun]:
    return list(_runs(team_id).order_by("-created_at")[:limit])


def get_run(team_id: int, run_id: UUID) -> ProviderImportRun | None:
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
    _runs(team_id).filter(status__in=ACTIVE_IMPORT_STATUSES, created_at__lt=timezone.now() - STALE_RUN_AGE).update(
        status=ProviderImportStatus.FAILED, finished_at=timezone.now()
    )


def _new_step_progress() -> dict[str, Any]:
    return {
        "status": ImportStepStatus.PENDING.value,
        "processed": 0,
        "imported": 0,
        "warnings": [],
        "last_error": None,
        "checkpoint": None,
    }


def _update_step(team_id: int, run_id: UUID, step: str, change: Callable[[dict[str, Any]], None]) -> None:
    with transaction.atomic():
        run = _runs(team_id).select_for_update().get(id=run_id)
        change(run.progress.setdefault(step, _new_step_progress()))
        update_fields = ["progress"]
        if run.status == ProviderImportStatus.QUEUED:
            run.status = ProviderImportStatus.RUNNING
            run.started_at = timezone.now()
            update_fields += ["status", "started_at"]
        run.save(update_fields=update_fields)


def _mark_running(progress: dict[str, Any]) -> None:
    progress["status"] = ImportStepStatus.RUNNING.value


def _mark_completed(progress: dict[str, Any]) -> None:
    progress.update(status=ImportStepStatus.COMPLETED.value, last_error=None, checkpoint=None)


def _add_page(progress: dict[str, Any], page: ImportPage) -> None:
    progress["processed"] += page.processed
    progress["imported"] += page.imported
    progress["warnings"] = (progress["warnings"] + list(page.warnings))[:MAX_STEP_WARNINGS]
    progress["checkpoint"] = page.checkpoint


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
