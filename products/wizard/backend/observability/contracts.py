from enum import StrEnum

from posthog.dataclasses import frozen


class WizardRunDispatchOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WizardWorkerCleanupOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@frozen
class WizardWorkerUsageObservation:
    lifetime_seconds: float
    cpu_cores: float
    memory_gb: float
    disk_size_gb: float
    cpu_usage_seconds: float | None
    billed_cpu_usage_seconds: float | None
    allocated_cpu_core_seconds: float
    allocated_memory_gb_seconds: float
    allocated_disk_gb_seconds: float
