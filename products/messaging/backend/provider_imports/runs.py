"""Start provider import runs, run their steps page by page, and record the outcome."""

import hmac
import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings as django_settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.event_usage import report_team_action, report_user_action
from posthog.models import Team, User

from products.messaging.backend.models.provider_import_run import (
    ACTIVE_IMPORT_STATUSES,
    ImportStepStatus,
    ProviderImportRun,
    ProviderImportStatus,
)
from products.messaging.backend.provider_imports.base import (
    ImportAccessLost,
    ImportContext,
    ImportItem,
    ImportPage,
    ImportProvider,
    ImportStepBlocked,
    ImportStepError,
    PeopleImportPlan,
    StepCheckpoint,
)
from products.messaging.backend.provider_imports.metrics import IMPORT_CONTACTS, IMPORT_RUNS
from products.messaging.backend.provider_imports.registry import get_provider
from products.messaging.backend.temporal.client import RUN_EXECUTION_TIMEOUT, start_provider_import_workflow
from products.workflows.backend.facade.api import can_edit_workflows
from products.workflows.backend.facade.people_import import (
    discard_staged_contacts,
    fail_contacts_cohort,
    staged_contact_imports,
)

logger = logging.getLogger(__name__)

STAGED_CONTACTS_CLEANUP_FAILED = Counter(
    "messaging_provider_import_staged_contacts_cleanup_failed_total",
    "Times the hourly sweep couldn't delete the contacts a provider import stored.",
)

# A run still active after the workflow's execution timeout has no workflow left to finish it.
STALE_RUN_AGE = RUN_EXECUTION_TIMEOUT + timedelta(hours=1)
MAX_STEP_WARNINGS = 50
MAX_STEP_ITEMS = 200
UNEXPECTED_ERROR_MESSAGE = "An unexpected error interrupted this step."
PEOPLE_IMPORT_FAILED_MESSAGE = "Some contacts couldn't become people or join their cohort. Import again to finish."
PEOPLE_IMPORT_FAILED_CLASS = "PeopleImportFailed"
# The class a failed step reports when nothing raised, because its workflow ended before the step finished.
STEP_NOT_FINISHED_CLASS = "StepNotFinished"


class ProviderImportAlreadyRunning(Exception):
    pass


class InvalidImportSettings(Exception):
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
    settings: Mapping[str, str] | None = None,
) -> ProviderImportRun:
    """Check the credentials, claim a queued run, store the credentials, and start the run's workflow.

    Raises UnknownImportProvider, InvalidImportSteps, InvalidImportSettings, ProviderImportAlreadyRunning, the
    ImportCredentials* errors and ImportProviderUnavailable.
    """
    provider = get_provider(provider_key)
    ordered_steps = _order_steps(provider, steps)
    resolved_settings = _resolve_settings(provider, settings or {})

    _fail_stale_runs(team_id)
    if _runs(team_id).filter(provider=provider.key, status__in=ACTIVE_IMPORT_STATUSES).exists():
        raise ProviderImportAlreadyRunning(f"A {provider.label} import is already running.")

    credentials = provider.check_credentials(team_id, api_key, resolved_settings, ordered_steps)
    provider.check_step_access(team_id, credentials, ordered_steps)
    progress = {step: _new_step_progress() for step in ordered_steps}
    if provider.resumes_after_failure:
        _continue_failed_steps(team_id, provider.key, progress, resolved_settings, _key_id(credentials.api_key))
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
                settings=resolved_settings,
            )
            if provider.retains_credentials:
                run.integration_id = provider.store_credentials(team_id, credentials, created_by_id)
            else:
                run.temporary_api_key = credentials.api_key
            run.save(update_fields=["integration", "temporary_api_key"])
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


def run_step(team_id: int, run_id: UUID, step: str, attempt: int) -> list[PeopleImportPlan]:
    """Run one step from its saved checkpoint, and save each page together with the step's progress.

    `attempt` is the Temporal attempt number. An older attempt can keep running after Temporal starts a newer one,
    so each page write checks that its attempt still owns the step. Returns the contact lists the step stored, which
    the run's workflow sends next.
    """
    run = _runs(team_id).get(id=run_id)
    provider = get_provider(run.provider)
    claim = _claim_step(team_id, run_id, step, attempt)
    if claim.completed:
        return _people_imports(team_id, run_id, step)

    context = ImportContext(
        team_id=team_id,
        created_by_id=run.created_by_id,
        integration_id=run.integration_id,
        api_key=run.temporary_api_key,
        steps=tuple(run.steps),
        run_id=str(run_id),
        settings=run.settings,
        completed_steps=tuple(
            key for key in run.steps if run.progress.get(key, {}).get("status") == ImportStepStatus.COMPLETED.value
        ),
    )
    try:
        _check_required_steps(provider, run, step)
        for page in provider.run_step(step, context, claim.checkpoint):
            _check_creator_access(team_id, run.created_by_id)
            _save_page(team_id, run_id, step, attempt, page)
            if page.checkpoint is None:
                return _people_imports(team_id, run_id, step)
        _update_owned_step(team_id, run_id, step, attempt, _mark_completed)
        return _people_imports(team_id, run_id, step)
    except (StaleImportAttempt, ImportRunClosed):
        raise
    except Exception as e:
        if not isinstance(e, ImportStepError):
            logger.exception("Provider import step failed", extra={"run_id": str(run_id), "step": step})
        last_error = str(e)[:500] if isinstance(e, ImportStepError) else UNEXPECTED_ERROR_MESSAGE
        error_class = type(e).__name__
        try:
            _update_owned_step(
                team_id,
                run_id,
                step,
                attempt,
                lambda progress: progress.update(last_error=last_error, error_class=error_class),
            )
        except (StaleImportAttempt, ImportRunClosed):
            pass
        raise


def _check_creator_access(team_id: int, created_by_id: int | None) -> None:
    # The run writes in the background, so the person who started it may have lost access since.
    if not can_edit_workflows(team_id=team_id, user_id=created_by_id):
        raise ImportAccessLost(
            "The person who started this import can't edit workflows in this project anymore, so it stopped."
        )


def _check_required_steps(provider: ImportProvider, run: ProviderImportRun, step: str) -> None:
    spec = next((spec for spec in provider.steps if spec.key == step), None)
    labels = {spec.key: spec.label for spec in provider.steps}
    missing = [
        labels.get(required, required)
        for required in (spec.requires if spec else ())
        if required in run.steps and run.progress.get(required, {}).get("status") != ImportStepStatus.COMPLETED.value
    ]
    if missing:
        raise ImportStepBlocked(
            f"This step waits for {', '.join(missing)}, which didn't finish. Import again once it has."
        )


def finish_run(team_id: int, run_id: UUID) -> None:
    """Fail the steps that did not complete, and set the run's final status. A run that already ended stays as it is."""
    # Before the run closes, so a storage error retries the finish. It also removes what a save that rolled back, or
    # a step that failed, stored.
    discard_staged_contacts(team_id, str(run_id))
    _close_run(team_id, run_id)


def record_people_import(team_id: int, run_id: UUID, step: str, outcome: Mapping[str, int | None]) -> None:
    """Save how sending a step's contact lists went. A list that failed fails the step, so the run shows it."""
    with transaction.atomic():
        run = _runs(team_id).select_for_update().get(id=run_id)
        if run.status not in ACTIVE_IMPORT_STATUSES:
            return
        progress = run.progress.setdefault(step, _new_step_progress())
        already_recorded = "people_import" in progress
        progress["people_import"] = dict(outcome)
        not_sent = 0
        if (sent := outcome.get("sent")) is not None:
            counts = progress.setdefault("counts", {})
            if "people_to_send" not in counts:
                # Stored before this count existed: its contacts sit in `people`, and its parts don't say who is new.
                counts["people_to_send"] = counts.get("people", 0)
            else:
                counts["new_people"] = outcome.get("new_people") or 0
            not_sent = max(counts["people_to_send"] - sent, 0)
            counts.update(people=sent, not_sent=not_sent)
            progress["imported"] = sent
        if not_sent:
            progress.update(
                status=ImportStepStatus.FAILED.value,
                last_error=f"{not_sent:,} {'contact' if not_sent == 1 else 'contacts'} didn't reach PostHog, so their "
                "people weren't created or updated. Import again to retry.",
                error_class=PEOPLE_IMPORT_FAILED_CLASS,
            )
        elif outcome.get("failed_lists"):
            progress.update(
                status=ImportStepStatus.FAILED.value,
                last_error=PEOPLE_IMPORT_FAILED_MESSAGE,
                error_class=PEOPLE_IMPORT_FAILED_CLASS,
            )
        run.save(update_fields=["progress"])
    if already_recorded:
        # Temporal ran this again after it saved, and the counter adds each contact once.
        return
    _count_contacts(run.provider, step, progress)


def _count_contacts(provider: str, step: str, progress: Mapping[str, Any]) -> None:
    for outcome_name, count in _step_outcomes(progress).items():
        IMPORT_CONTACTS.labels(provider=provider, step=step, outcome=outcome_name).inc(count)


def _people_imports(team_id: int, run_id: UUID, step: str) -> list[PeopleImportPlan]:
    run = _runs(team_id).get(id=run_id)
    plans = run.progress.get(step, {}).get("people_imports", [])
    return [PeopleImportPlan(**plan, provider=run.provider, step=step) for plan in plans]


def _stored_plan(plan: PeopleImportPlan) -> dict[str, Any]:
    # A worker on the previous release can't load a plan with keys it doesn't know, so the labels stay out.
    return {key: value for key, value in asdict(plan).items() if key not in ("provider", "step")}


def close_stale_runs() -> int:
    """End runs whose workflow is gone, in every team. A timed-out workflow can't clear its own key."""
    stale = list(
        ProviderImportRun.objects.unscoped()
        .filter(status__in=ACTIVE_IMPORT_STATUSES, created_at__lt=timezone.now() - STALE_RUN_AGE)
        .values_list("team_id", "id")
    )
    for team_id, run_id in stale:
        _close_stale_run(team_id, run_id)
    _discard_contacts_of_ended_runs()
    return len(stale)


def _discard_contacts_of_ended_runs() -> None:
    # Every hour until the delete succeeds, whatever state the run is in or even when it no longer exists. Only a
    # run that can still be importing keeps its contacts.
    try:
        staged = staged_contact_imports()
    except Exception:
        STAGED_CONTACTS_CLEANUP_FAILED.inc()
        logger.exception("Failed to list the contacts provider imports stored")
        return
    run_ids_by_team: dict[int, list[str]] = {}
    for team_id, run_id in staged:
        if _is_uuid(run_id):
            run_ids_by_team.setdefault(team_id, []).append(run_id)
    active = {
        (team_id, str(run_id))
        for team_id, run_ids in run_ids_by_team.items()
        for run_id in ProviderImportRun.objects.unscoped()
        .filter(team_id=team_id, id__in=run_ids, status__in=ACTIVE_IMPORT_STATUSES)
        .values_list("id", flat=True)
    }
    for team_id, run_id in staged - active:
        try:
            discard_staged_contacts(team_id, run_id)
        except Exception:
            STAGED_CONTACTS_CLEANUP_FAILED.inc()
            logger.exception("Failed to delete the contacts a provider import stored", extra={"run_id": run_id})


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


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
    labels = {spec.key: spec.label for spec in provider.steps}
    for spec in provider.steps:
        missing = [labels[key] for key in spec.needs if key not in steps]
        if spec.key in steps and missing:
            raise InvalidImportSteps(f"{spec.label} needs {', '.join(missing)} selected too.")
    return [key for key in known if key in steps]


def _resolve_settings(provider: ImportProvider, settings: Mapping[str, str]) -> dict[str, str]:
    specs = {spec.key: spec for spec in provider.settings}
    if unknown := sorted(set(settings) - set(specs)):
        raise InvalidImportSettings(f"{provider.label} has no setting named {', '.join(unknown)}.")
    resolved: dict[str, str] = {}
    for key, spec in specs.items():
        value = settings.get(key, spec.default)
        if value is None:
            raise InvalidImportSettings(f"Choose a value for {spec.label}.")
        if value not in {choice.value for choice in spec.choices}:
            raise InvalidImportSettings(f"{value} isn't a valid value for {spec.label}.")
        resolved[key] = value
    return resolved


def _continue_failed_steps(
    team_id: int,
    provider_key: str,
    progress: dict[str, dict[str, Any]],
    settings: Mapping[str, str],
    key_id: str | None,
) -> None:
    for step_progress in progress.values():
        step_progress["key_id"] = key_id
    latest = _runs(team_id).filter(provider=provider_key).order_by("-created_at").first()
    # A checkpoint only makes sense for the settings that wrote it, such as the region it was reading.
    if latest is None or latest.status != ProviderImportStatus.FAILED or latest.settings != settings:
        return
    for step, step_progress in progress.items():
        previous = latest.progress.get(step, {})
        # A cursor from another key can point into another account, so a new key starts the step over.
        if previous.get("key_id") == key_id:
            step_progress["checkpoint"] = previous.get("checkpoint")


def _key_id(api_key: str | None) -> str | None:
    if not api_key:
        return None
    return hmac.new(django_settings.SECRET_KEY.encode(), api_key.encode(), hashlib.sha256).hexdigest()[:16]


def _fail_stale_runs(team_id: int) -> None:
    stale_ids = list(
        _runs(team_id)
        .filter(status__in=ACTIVE_IMPORT_STATUSES, created_at__lt=timezone.now() - STALE_RUN_AGE)
        .values_list("id", flat=True)
    )
    for run_id in stale_ids:
        _close_stale_run(team_id, run_id)


def _close_stale_run(team_id: int, run_id: UUID) -> None:
    try:
        discard_staged_contacts(team_id, str(run_id))
    except Exception:
        # A run that never closes would block every later import, so it closes anyway.
        logger.exception("Failed to delete the contacts a provider import stored", extra={"run_id": str(run_id)})
    _close_run(team_id, run_id)


def _close_run(team_id: int, run_id: UUID) -> None:
    unreported_steps: list[str] = []
    with transaction.atomic():
        run = _runs(team_id).select_for_update().get(id=run_id)
        if run.status not in ACTIVE_IMPORT_STATUSES:
            return
        for step in run.steps:
            progress = run.progress.setdefault(step, _new_step_progress())
            if progress.get("people_imports") and "people_import" not in progress:
                # The workflow ended before it sent the step's contacts, so their cohorts can't finish.
                unreported_steps.append(step)
                for plan in progress["people_imports"]:
                    fail_contacts_cohort(team_id, plan["cohort_id"])
                progress.update(
                    status=ImportStepStatus.FAILED.value,
                    last_error=PEOPLE_IMPORT_FAILED_MESSAGE,
                    error_class=PEOPLE_IMPORT_FAILED_CLASS,
                )
            if progress["status"] != ImportStepStatus.COMPLETED:
                progress["status"] = ImportStepStatus.FAILED
                progress.setdefault("error_class", STEP_NOT_FINISHED_CLASS)
        completed = all(run.progress[step]["status"] == ImportStepStatus.COMPLETED for step in run.steps)
        run.status = ProviderImportStatus.COMPLETED if completed else ProviderImportStatus.FAILED
        run.finished_at = timezone.now()
        run.temporary_api_key = None
        run.save(update_fields=["progress", "status", "finished_at", "temporary_api_key"])

    for step in unreported_steps:
        _count_contacts(run.provider, step, run.progress[step])
    IMPORT_RUNS.labels(provider=run.provider, status=run.status).inc()
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
        if saved.error is None:
            progress["processed"] += page.processed
            progress["imported"] += saved.imported
            _add_warnings(progress, saved.warnings)
            _add_counts(progress, saved.counts)
            _add_items(progress, saved.items)
            if saved.people_imports:
                progress["people_imports"] = progress.get("people_imports", []) + [
                    _stored_plan(replace(plan, created_by_id=run.created_by_id)) for plan in saved.people_imports
                ]
            progress["checkpoint"] = page.checkpoint
            if page.checkpoint is None:
                _mark_completed(progress)
            run.save(update_fields=["progress"])
    if saved.error is not None:
        raise ImportStepError(saved.error)


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
    progress.pop("error_class", None)


def _step_outcomes(progress: Mapping[str, Any]) -> dict[str, int]:
    """How many records a step imported, skipped and failed. A contacts step counts what capture accepted."""
    people_import = progress.get("people_import", {})
    counts = progress.get("counts", {})
    if people_import:
        if people_import.get("sent") is not None:
            to_send = counts.get("people_to_send", people_import["sent"])
            return {
                "imported": people_import["sent"],
                "skipped": max(progress.get("processed", 0) - to_send, 0),
                "failed": counts.get("not_sent", 0),
            }
        if people_import.get("people"):
            return {
                "imported": people_import["found"],
                "skipped": max(progress.get("processed", 0) - people_import["people"], 0),
                "failed": people_import["people"] - people_import["found"],
            }
    if progress.get("people_imports"):
        # The contacts were stored, but sending them never reported back.
        to_send = counts.get("people_to_send", 0)
        return {"imported": 0, "skipped": max(progress.get("processed", 0) - to_send, 0), "failed": to_send}
    imported, failed = progress.get("imported", 0), counts.get("failed", 0)
    return {
        "imported": imported,
        "skipped": max(progress.get("processed", 0) - imported - failed, 0),
        "failed": failed,
    }


def _report_finished(run: ProviderImportRun) -> None:
    """One event per run, attributed to the person who started it. It carries no contact data or error message."""
    try:
        team = Team.objects.get(id=run.team_id)
        failed = run.status != ProviderImportStatus.COMPLETED
        progress = {step: run.progress.get(step, {}) for step in run.steps}
        properties: dict[str, Any] = {
            "source": run.provider,
            "provider": run.provider,
            "stage": "failed" if failed else "completed",
            "dry_run": False,
            "steps": run.steps,
            "counts": {step: _step_outcomes(step_progress) for step, step_progress in progress.items()},
            "duration_seconds": int((run.finished_at - run.created_at).total_seconds()) if run.finished_at else None,
            "retried_chunks": sum(
                step_progress.get("people_import", {}).get("retried_chunks", 0) for step_progress in progress.values()
            ),
        }
        if failed:
            properties["error_class"] = next(
                (
                    step_progress["error_class"]
                    for step_progress in progress.values()
                    if step_progress.get("error_class")
                ),
                STEP_NOT_FINISHED_CLASS,
            )
        user = User.objects.filter(id=run.created_by_id).first()
        if user is None or not user.distinct_id:
            report_team_action(team, "workflows import run", properties)
        else:
            # The starter may have switched to another organization since.
            report_user_action(user, "workflows import run", properties, team=team, organization=team.organization)
    except Exception:
        logger.exception("Failed to report the provider import outcome")
