from products.wizard.backend.logic.workers.contracts import WizardWorkerTelemetry
from products.wizard.backend.observability.contracts import WizardWorkerUsageObservation


def worker_usage_observation(telemetry: WizardWorkerTelemetry) -> WizardWorkerUsageObservation:
    resource_usage = telemetry.resource_usage

    return WizardWorkerUsageObservation(
        lifetime_seconds=telemetry.lifetime_seconds,
        cpu_cores=resource_usage.cpu_cores,
        memory_gb=resource_usage.memory_gb,
        disk_size_gb=resource_usage.disk_size_gb,
        cpu_usage_seconds=(
            resource_usage.provider_cpu_usage_usec / 1_000_000
            if resource_usage.provider_cpu_usage_usec is not None
            else None
        ),
        billed_cpu_usage_seconds=(
            resource_usage.provider_billed_cpu_usage_usec / 1_000_000
            if resource_usage.provider_billed_cpu_usage_usec is not None
            else None
        ),
        allocated_cpu_core_seconds=resource_usage.cpu_cores * telemetry.lifetime_seconds,
        allocated_memory_gb_seconds=resource_usage.memory_gb * telemetry.lifetime_seconds,
        allocated_disk_gb_seconds=resource_usage.disk_size_gb * telemetry.lifetime_seconds,
    )
