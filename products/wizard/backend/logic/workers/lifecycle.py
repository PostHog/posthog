import logging
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError

from products.tasks.backend.facade.sandbox import SandboxCleanupError
from products.wizard.backend.facade.errors import WizardRunNotFoundError
from products.wizard.backend.logic.runs import store as run_store
from products.wizard.backend.logic.runs.errors import WizardWorkerCleanupError
from products.wizard.backend.logic.workers import (
    service as cloud_worker,
    store as worker_store,
)
from products.wizard.backend.logic.workers.contracts import WizardWorkerUsageMeasurement
from products.wizard.backend.observability.contracts import WizardWorkerCleanupOutcome
from products.wizard.backend.observability.service import wizard_observability

logger = logging.getLogger(__name__)


def cleanup_worker(team_id: int, run_id: UUID, sandbox_id: str) -> None:
    worker_store.mark_cleanup_pending(team_id, run_id)

    try:
        usage = cloud_worker.measure_worker_usage(sandbox_id)

        if usage is not None:
            _record_worker_usage(team_id, run_id, sandbox_id, usage)
    finally:
        _destroy_worker(team_id, run_id, sandbox_id)

    _report_worker_usage(team_id, run_id)


def _record_worker_usage(
    team_id: int,
    run_id: UUID,
    sandbox_id: str,
    usage: WizardWorkerUsageMeasurement,
) -> None:
    try:
        worker_store.record_usage(team_id, run_id, usage)
    except (DatabaseError, ObjectDoesNotExist, ValueError):
        logger.exception(
            "wizard_worker_usage_recording_failed",
            extra={"team_id": team_id, "run_id": str(run_id), "sandbox_id": sandbox_id},
        )


def _destroy_worker(team_id: int, run_id: UUID, sandbox_id: str) -> None:
    try:
        cloud_worker.destroy_worker(sandbox_id)
    except SandboxCleanupError as error:
        _record_cleanup_failure(team_id, run_id, sandbox_id)
        wizard_observability.worker_cleanup_finished(team_id, run_id, WizardWorkerCleanupOutcome.FAILED)
        raise WizardWorkerCleanupError from error

    worker_store.mark_cleaned(team_id, run_id)
    wizard_observability.worker_cleanup_finished(team_id, run_id, WizardWorkerCleanupOutcome.SUCCEEDED)


def _record_cleanup_failure(team_id: int, run_id: UUID, sandbox_id: str) -> None:
    try:
        worker_store.mark_cleanup_failed(team_id, run_id)
    except DatabaseError:
        logger.exception(
            "wizard_worker_cleanup_failure_recording_failed",
            extra={"team_id": team_id, "run_id": str(run_id), "sandbox_id": sandbox_id},
        )


def _report_worker_usage(team_id: int, run_id: UUID) -> None:
    try:
        run = run_store.get_run(team_id, run_id)
        telemetry = worker_store.get_worker_telemetry(team_id, run_id)
    except (DatabaseError, ObjectDoesNotExist, ValueError, WizardRunNotFoundError):
        logger.exception(
            "wizard_worker_usage_reporting_failed",
            extra={"team_id": team_id, "run_id": str(run_id)},
        )
        return

    wizard_observability.worker_usage_recorded(run, telemetry)
