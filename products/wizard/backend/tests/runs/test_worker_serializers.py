from datetime import UTC, datetime

import pytest

from products.wizard.backend.logic.workers.contracts import WizardWorkerResourceUsage
from products.wizard.backend.logic.workers.serializers import (
    worker_resource_usage_from_record,
    worker_resource_usage_to_record,
)


def test_worker_resource_usage_round_trip() -> None:
    resource_usage = WizardWorkerResourceUsage(
        cpu_cores=2,
        memory_gb=4,
        disk_size_gb=16,
        ttl_seconds=4500,
        ttl_expires_at=datetime(2026, 8, 24, 15, 0, tzinfo=UTC),
        provider_cpu_usage_usec=120,
        provider_billed_cpu_usage_usec=240,
        provider_usage_measured_at=datetime(2026, 8, 24, 14, 30, tzinfo=UTC),
    )

    assert worker_resource_usage_from_record(worker_resource_usage_to_record(resource_usage)) == resource_usage


@pytest.mark.parametrize(
    "record",
    (
        None,
        {},
        {"version": 2},
        {
            "version": 1,
            "cpu_cores": 0,
            "memory_gb": 4,
            "disk_size_gb": 16,
            "ttl_seconds": 4500,
            "ttl_expires_at": "2026-08-24T15:00:00+00:00",
        },
    ),
)
def test_worker_resource_usage_rejects_invalid_records(record: object) -> None:
    with pytest.raises(ValueError, match="Invalid Wizard Worker resource usage"):
        worker_resource_usage_from_record(record)
