from dataclasses import replace
from uuid import UUID

from django.db.models import Case, CharField, F, Value, When
from django.utils import timezone

from products.wizard.backend.facade.enums import WizardWorkerCleanupStatus
from products.wizard.backend.logic.runs.config import WORKER_CLEANUP_MAX_ATTEMPTS
from products.wizard.backend.logic.workers.contracts import (
    WizardWorkerProvisioning,
    WizardWorkerTelemetry,
    WizardWorkerUsageMeasurement,
)
from products.wizard.backend.logic.workers.serializers import (
    record_to_worker_resource_usage,
    worker_resource_usage_to_record,
)
from products.wizard.backend.models import WizardWorker


def get_sandbox_id(team_id: int, run_id: UUID) -> str | None:
    worker = WizardWorker.objects.for_team(team_id).filter(run_id=run_id).only("sandbox_id").first()
    return worker.sandbox_id if worker is not None else None


def record_provisioned_worker(team_id: int, run_id: UUID, provisioning: WizardWorkerProvisioning) -> None:
    WizardWorker.objects.for_team(team_id).update_or_create(
        team_id=team_id,
        run_id=run_id,
        defaults={
            "sandbox_id": provisioning.sandbox_id,
            "resource_usage": worker_resource_usage_to_record(provisioning.resource_usage),
            "cleanup_status": WizardWorkerCleanupStatus.ACTIVE.value,
            "cleanup_error": None,
        },
    )


def record_usage(team_id: int, run_id: UUID, usage: WizardWorkerUsageMeasurement) -> None:
    worker = WizardWorker.objects.for_team(team_id).only("resource_usage").get(run_id=run_id)
    resource_usage = record_to_worker_resource_usage(worker.resource_usage)

    updated_resource_usage = replace(
        resource_usage,
        provider_cpu_usage_usec=usage.cpu_usage_usec,
        provider_billed_cpu_usage_usec=usage.billed_cpu_usage_usec,
        provider_usage_measured_at=usage.measured_at,
    )

    WizardWorker.objects.for_team(team_id).filter(run_id=run_id).update(
        resource_usage=worker_resource_usage_to_record(updated_resource_usage)
    )


def mark_cleanup_pending(team_id: int, run_id: UUID) -> None:
    WizardWorker.objects.for_team(team_id).filter(run_id=run_id).update(
        cleanup_status=WizardWorkerCleanupStatus.PENDING.value,
        cleanup_attempts=F("cleanup_attempts") + 1,
        cleanup_error=None,
    )


def mark_cleanup_failed(team_id: int, run_id: UUID) -> None:
    WizardWorker.objects.for_team(team_id).filter(run_id=run_id).update(
        cleanup_status=Case(
            When(
                cleanup_attempts__gte=WORKER_CLEANUP_MAX_ATTEMPTS,
                then=Value(WizardWorkerCleanupStatus.FAILED.value),
            ),
            default=Value(WizardWorkerCleanupStatus.PENDING.value),
            output_field=CharField(),
        ),
        cleanup_error="Wizard Worker cleanup failed.",
    )


def mark_cleaned(team_id: int, run_id: UUID) -> None:
    WizardWorker.objects.for_team(team_id).filter(run_id=run_id).update(
        cleanup_status=WizardWorkerCleanupStatus.CLEANED.value,
        cleanup_error=None,
        cleaned_at=timezone.now(),
    )


def get_worker_telemetry(team_id: int, run_id: UUID) -> WizardWorkerTelemetry:
    worker = (
        WizardWorker.objects.for_team(team_id).only("created_at", "cleaned_at", "resource_usage").get(run_id=run_id)
    )

    if worker.cleaned_at is None:
        raise ValueError("Wizard Worker has not been cleaned up")

    return WizardWorkerTelemetry(
        resource_usage=record_to_worker_resource_usage(worker.resource_usage),
        lifetime_seconds=max((worker.cleaned_at - worker.created_at).total_seconds(), 0),
    )
