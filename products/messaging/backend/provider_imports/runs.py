"""Start provider import runs, run their steps page by page, and record the outcome."""

import hmac
import hashlib
import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
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
    ImportItem,
    ImportPage,
    ImportProvider,
    ImportStepError,
    PassedObjects,
    StepCheckpoint,
)
from products.messaging.backend.provider_imports.registry import get_provider
from products.messaging.backend.temporal.client import RUN_EXECUTION_TIMEOUT, start_provider_import_workflow

logger = logging.getLogger(__name__)

# A run still active after the workflow's execution timeout has no workflow left to finish it.
STALE_RUN_AGE = RUN_EXECUTION_TIMEOUT + timedelta(hours=1)
MAX_STEP_WARNINGS = 50
MAX_STEP_ITEMS = 200
UNEXPECTED_ERROR_MESSAGE = "An unexpected error interrupted this step."
# Temporal numbers its attempts from 1, so a step run in the request never shares an attempt with the workflow.
PASSED_STEP_ATTEMPT = 0


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
    team_id: int,
    provider_key: str,
    steps: list[str],
    api_key: str | None,
    created_by_id: int | None,
    objects: PassedObjects | None = None,
) -> ProviderImportRun:
    """Check the credentials, claim a queued run, store the credentials, and start the run's workflow.

    With `objects`, the steps the provider imports from them run in this request first, through the same save code
    as the key, and only the rest need the key and the workflow. A run whose every step imports from them ends
    before this returns.

    Raises UnknownImportProvider, InvalidImportSteps, InvalidPassedObjects, ProviderImportAlreadyRunning, the
    ImportCredentials* errors and ImportProviderUnavailable.
    """
    provider = get_provider(provider_key)
    ordered_steps = _order_steps(provider, steps)
    passed_steps = provider.check_passed_objects(ordered_steps, objects) if objects is not None else []
    key_steps = [step for step in ordered_steps if step not in passed_steps]

    _fail_stale_runs(team_id)
    if _runs(team_id).filter(provider=provider.key, status__in=ACTIVE_IMPORT_STATUSES).exists():
        raise ProviderImportAlreadyRunning(f"A {provider.label} import is already running.")

    credentials = provider.check_credentials(team_id, api_key) if key_steps else None
    progress = {step: _new_step_progress() for step in ordered_steps}
    for step in passed_steps:
        progress[step]["from_objects"] = True
    if provider.resumes_after_failure and credentials is not None:
        _continue_failed_steps(team_id, provider.key, progress, _key_id(credentials.api_key))
    try:
        with transaction.atomic():
            # Create the run before storing the credentials. A concurrent start then waits on the active-run index
            # and fails, so only the request that owns the run stores its key.
            run = _runs(team_id).create(
                team_id=team_id,
                provider=provider.key,
                steps=ordered_steps,
                created_by_id=created_by_id,
                progress=progress,
            )
            if credentials is not None:
                if provider.retains_credentials:
                    run.integration_id = provider.store_credentials(team_id, credentials, created_by_id)
                else:
                    run.temporary_api_key = credentials.api_key
                run.save(update_fields=["integration", "temporary_api_key"])
    except IntegrityError as e:
        raise ProviderImportAlreadyRunning(f"A {provider.label} import is already running.") from e

    if objects is not None and passed_steps:
        _run_passed_steps(team_id, run, provider, passed_steps, objects)
    if not key_steps:
        _close_run(team_id, run.id)
        run.refresh_from_db()
        return run

    try:
        start_provider_import_workflow(team_id=team_id, run_id=run.id, steps=key_steps)
    except Exception:
        # A queued run without a workflow would block every later import until it goes stale. If Temporal started
        # the workflow but the response got lost, its steps find the run closed and import nothing.
        _close_run(team_id, run.id)
        raise
    run.refresh_from_db()
    return run


def _run_passed_steps(
    team_id: int, run: ProviderImportRun, provider: ImportProvider, steps: list[str], objects: PassedObjects
) -> None:
    context = ImportContext(team_id=team_id, created_by_id=run.created_by_id, integration_id=run.integration_id)
    try:
        for step in steps:
            _claim_step(team_id, run.id, step, PASSED_STEP_ATTEMPT)
            try:
                _save_pages(
                    team_id, run.id, step, PASSED_STEP_ATTEMPT, provider.run_passed_step(step, context, objects)
                )
            except (StaleImportAttempt, ImportRunClosed):
                raise
            except Exception:
                # The step keeps its error and fails when the run ends. The steps after it still run.
                continue
    except Exception:
        # Without a workflow the run would stay active and block the next import until it goes stale.
        _close_run(team_id, run.id)
        raise


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

    context = ImportContext(
        team_id=team_id,
        created_by_id=run.created_by_id,
        integration_id=run.integration_id,
        api_key=run.temporary_api_key,
    )
    _save_pages(team_id, run_id, step, attempt, provider.run_step(step, context, claim.checkpoint))


def _save_pages(team_id: int, run_id: UUID, step: str, attempt: int, pages: Iterator[ImportPage]) -> None:
    try:
        for page in pages:
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


def close_stale_runs() -> int:
    """End runs whose workflow is gone, in every team. A timed-out workflow can't clear its own key."""
    stale = list(
        ProviderImportRun.objects.unscoped()
        .filter(status__in=ACTIVE_IMPORT_STATUSES, created_at__lt=timezone.now() - STALE_RUN_AGE)
        .values_list("team_id", "id")
    )
    for team_id, run_id in stale:
        _close_run(team_id, run_id)
    return len(stale)


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


def _continue_failed_steps(
    team_id: int, provider_key: str, progress: dict[str, dict[str, Any]], key_id: str | None
) -> None:
    for step_progress in progress.values():
        step_progress["key_id"] = key_id
    latest = _runs(team_id).filter(provider=provider_key).order_by("-created_at").first()
    if latest is None or latest.status != ProviderImportStatus.FAILED:
        return
    for step, step_progress in progress.items():
        previous = latest.progress.get(step, {})
        # A cursor from another key can point into another account, so a new key starts the step over.
        if previous.get("key_id") == key_id:
            step_progress["checkpoint"] = previous.get("checkpoint")


def _key_id(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return hmac.new(settings.SECRET_KEY.encode(), api_key.encode(), hashlib.sha256).hexdigest()[:16]


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
        run.temporary_api_key = None
        run.save(update_fields=["progress", "status", "finished_at", "temporary_api_key"])

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
        _add_warnings(progress, saved.warnings)
        _add_counts(progress, saved.counts)
        _add_items(progress, saved.items)
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


def _add_warnings(progress: dict[str, Any], warnings: tuple[str, ...]) -> None:
    combined = progress["warnings"] + list(warnings)
    progress["warnings"] = combined[:MAX_STEP_WARNINGS]
    if len(combined) > MAX_STEP_WARNINGS:
        progress["warnings_omitted"] = progress.get("warnings_omitted", 0) + len(combined) - MAX_STEP_WARNINGS


def _add_counts(progress: dict[str, Any], counts: Mapping[str, int]) -> None:
    if not counts:
        return
    totals = progress.setdefault("counts", {})
    for key, value in counts.items():
        totals[key] = totals.get(key, 0) + value


def _add_items(progress: dict[str, Any], items: tuple[ImportItem, ...]) -> None:
    if not items:
        return
    combined = progress.get("items", []) + [asdict(item) for item in items]
    progress["items"] = combined[:MAX_STEP_ITEMS]
    if len(combined) > MAX_STEP_ITEMS:
        progress["items_omitted"] = progress.get("items_omitted", 0) + len(combined) - MAX_STEP_ITEMS


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
        team = Team.objects.get(id=run.team_id)
        duration_seconds = int((run.finished_at - run.created_at).total_seconds()) if run.finished_at else None
        report_team_action(
            team,
            "messaging provider import finished",
            {
                "provider": run.provider,
                "status": run.status,
                "steps": run.steps,
                "duration_seconds": duration_seconds,
                **{f"{step}_status": run.progress[step]["status"] for step in run.steps},
                **{f"{step}_imported": run.progress[step]["imported"] for step in run.steps},
            },
        )
        report_team_action(
            team,
            "workflows import run",
            {
                "source": run.provider,
                "stage": "finished",
                "dry_run": False,
                "status": run.status,
                "steps": run.steps,
                "duration_seconds": duration_seconds,
                "statuses": [run.progress[step]["status"] for step in run.steps],
                "counts": {step: run.progress[step].get("counts", {}) for step in run.steps},
                "note_count": sum(
                    len(item.get("notes", [])) for step in run.steps for item in run.progress[step].get("items", [])
                ),
            },
        )
    except Exception:
        logger.exception("Failed to report the provider import outcome")
