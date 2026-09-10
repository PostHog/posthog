from datetime import timedelta

import pytest

from django.utils import timezone

from products.wizard.backend.logic.workers import store
from products.wizard.backend.logic.workers.contracts import (
    WizardWorkerProvisioning,
    WizardWorkerResourceUsage,
    WizardWorkerUsageMeasurement,
)
from products.wizard.backend.models import WizardRun, WizardWorker


@pytest.mark.django_db
@pytest.mark.parametrize("late_sample", [True, False])
def test_cleanup_retries_preserve_saved_usage_and_original_end_time(team, late_sample: bool) -> None:
    now = timezone.now()
    run = WizardRun.objects.for_team(team.id).create(team_id=team.id, workspace={}, program={})
    store.record_provisioned_worker(
        team.id,
        run.id,
        WizardWorkerProvisioning(
            sandbox_id="sb-usage",
            resource_usage=WizardWorkerResourceUsage(
                cpu_cores=2,
                memory_gb=4,
                disk_size_gb=16,
                ttl_seconds=4500,
                ttl_expires_at=now + timedelta(seconds=4500),
            ),
        ),
    )
    store.record_usage(
        team.id, run.id, WizardWorkerUsageMeasurement(cpu_usage_usec=100, billed_cpu_usage_usec=200, measured_at=now)
    )
    store.mark_cleaned(team.id, run.id)
    worker = WizardWorker.objects.for_team(team.id).get(run_id=run.id)
    cleaned_at = worker.cleaned_at

    sample = (
        WizardWorkerUsageMeasurement(
            cpu_usage_usec=150, billed_cpu_usage_usec=None, measured_at=now + timedelta(seconds=1)
        )
        if late_sample
        else WizardWorkerUsageMeasurement(
            cpu_usage_usec=50, billed_cpu_usage_usec=100, measured_at=now - timedelta(seconds=1)
        )
    )
    store.record_usage(team.id, run.id, sample)
    store.mark_cleanup_pending(team.id, run.id)
    store.mark_cleaned(team.id, run.id)

    worker.refresh_from_db()
    assert worker.resource_usage["provider_cpu_usage_usec"] == (150 if late_sample else 100)
    assert worker.resource_usage["provider_billed_cpu_usage_usec"] == 200
    assert worker.cleaned_at == cleaned_at
    assert worker.cleanup_status == "cleaned"
