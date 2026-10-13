import logging
from time import monotonic

from django.db.models import Q
from django.utils import timezone

from posthog.dataclasses import frozen

from products.wizard.backend.facade.enums import (
    WizardRunDispatchStatus,
    WizardRunErrorCode,
    WizardRunStatus,
    WizardWorkerCleanupStatus,
)
from products.wizard.backend.facade.errors import IllegalStatusTransitionError, WizardRunNotFoundError
from products.wizard.backend.logic.reconciliation.config import (
    RECONCILIATION_BATCH_SIZE,
    RECONCILIATION_DISPATCH_TIME_BUDGET_SECONDS,
)
from products.wizard.backend.logic.runs import cancellation, lifecycle
from products.wizard.backend.logic.runs.config import WORKER_CLEANUP_MAX_ATTEMPTS
from products.wizard.backend.logic.runs.dispatch import dispatch_created_cloud_wizard_run_to_temporal_worker
from products.wizard.backend.logic.runs.errors import WizardRunDispatchError, WizardWorkerCleanupError
from products.wizard.backend.logic.workers import lifecycle as worker_lifecycle
from products.wizard.backend.models import WizardRun, WizardWorker
from products.wizard.backend.observability.service import wizard_observability

logger = logging.getLogger(__name__)


@frozen
class ReconciliationSummary:
    scanned: int
    reconciled: int
    failed: int
    batch_limit_reached: bool


def _summary(scanned: int, reconciled: int) -> ReconciliationSummary:
    return ReconciliationSummary(
        scanned=scanned,
        reconciled=reconciled,
        failed=scanned - reconciled,
        batch_limit_reached=scanned == RECONCILIATION_BATCH_SIZE,
    )


def reconcile_pending_dispatches() -> ReconciliationSummary:
    pending = list(
        WizardRun.objects.unscoped()
        .filter(
            status=WizardRunStatus.CREATED.value,
            dispatch_status=WizardRunDispatchStatus.PENDING.value,
        )
        .filter(Q(dispatch_next_attempt_at__isnull=True) | Q(dispatch_next_attempt_at__lte=timezone.now()))
        .order_by("dispatch_next_attempt_at", "created_at")
        .values_list("team_id", "id")[:RECONCILIATION_BATCH_SIZE]
    )

    reconciled = 0
    scanned = 0
    started_at = monotonic()
    for team_id, run_id in pending:
        if scanned > 0 and monotonic() - started_at >= RECONCILIATION_DISPATCH_TIME_BUDGET_SECONDS:
            break
        scanned += 1
        try:
            dispatch_created_cloud_wizard_run_to_temporal_worker(team_id, run_id)
        except WizardRunDispatchError as error:
            logger.exception(
                "wizard_run_redispatch_failed",
                extra={"team_id": team_id, "run_id": str(run_id), "exhausted": error.exhausted},
            )
            if error.exhausted:
                try:
                    lifecycle.fail_run(team_id, run_id, error_code=WizardRunErrorCode.DISPATCH_FAILED.value)
                except (IllegalStatusTransitionError, WizardRunNotFoundError, ValueError):
                    logger.exception(
                        "wizard_run_dispatch_exhaustion_failed",
                        extra={"team_id": team_id, "run_id": str(run_id)},
                    )
            continue
        except (WizardRunNotFoundError, ValueError):
            logger.exception("wizard_run_redispatch_failed", extra={"team_id": team_id, "run_id": str(run_id)})
            continue
        reconciled += 1

    return ReconciliationSummary(
        scanned=scanned,
        reconciled=reconciled,
        failed=scanned - reconciled,
        batch_limit_reached=scanned == RECONCILIATION_BATCH_SIZE,
    )


def reconcile_pending_cancellations() -> ReconciliationSummary:
    pending = list(
        WizardRun.objects.unscoped()
        .filter(
            status__in=(WizardRunStatus.CANCELLED.value, WizardRunStatus.FAILED.value),
            cancellation_requested_at__isnull=False,
            cancellation_dispatched_at__isnull=True,
        )
        .values_list("team_id", "id")[:RECONCILIATION_BATCH_SIZE]
    )

    reconciled = 0
    for team_id, run_id in pending:
        try:
            reconciled += cancellation.dispatch_cancellation(team_id, run_id)
        except (WizardRunNotFoundError, ValueError):
            logger.exception(
                "wizard_run_cancellation_reconciliation_failed",
                extra={"team_id": team_id, "run_id": str(run_id)},
            )

    return _summary(len(pending), reconciled)


def reconcile_expired_runs() -> ReconciliationSummary:
    expired = list(
        WizardRun.objects.unscoped()
        .filter(
            status__in=(WizardRunStatus.CREATED.value, WizardRunStatus.RUNNING.value),
            deadline_at__lte=timezone.now(),
        )
        .values_list("team_id", "id", "workflow_id")[:RECONCILIATION_BATCH_SIZE]
    )

    reconciled = 0
    for team_id, run_id, workflow_id in expired:
        try:
            run = lifecycle.fail_run(team_id, run_id, error_code=WizardRunErrorCode.TIMEOUT)
        except (IllegalStatusTransitionError, WizardRunNotFoundError, ValueError):
            logger.exception("wizard_run_expiration_failed", extra={"team_id": team_id, "run_id": str(run_id)})
            continue
        wizard_observability.run_past_deadline(run)
        if workflow_id is not None:
            lifecycle.request_cloud_run_cancellation(team_id, run_id)
        reconciled += 1

    return _summary(len(expired), reconciled)


def reconcile_pending_worker_cleanup() -> ReconciliationSummary:
    now = timezone.now()
    pending = list(
        WizardWorker.objects.unscoped()
        .filter(
            cleanup_status__in=(
                WizardWorkerCleanupStatus.ACTIVE.value,
                WizardWorkerCleanupStatus.PENDING.value,
            ),
            cleanup_attempts__lt=WORKER_CLEANUP_MAX_ATTEMPTS,
            sandbox_id__isnull=False,
        )
        .filter(
            Q(
                run__status__in=(
                    WizardRunStatus.COMPLETED.value,
                    WizardRunStatus.FAILED.value,
                    WizardRunStatus.CANCELLED.value,
                )
            )
            | Q(run__deadline_at__lte=now)
        )
        .values_list("team_id", "run_id", "sandbox_id")[:RECONCILIATION_BATCH_SIZE]
    )

    reconciled = 0
    for team_id, run_id, sandbox_id in pending:
        if sandbox_id is None:
            continue
        try:
            worker_lifecycle.cleanup_worker(team_id, run_id, sandbox_id)
        except WizardWorkerCleanupError:
            logger.exception("wizard_worker_reconciliation_failed", extra={"team_id": team_id, "run_id": str(run_id)})
            continue
        reconciled += 1

    return _summary(len(pending), reconciled)
