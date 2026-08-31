from datetime import datetime

from products.wizard.backend.logic.workers.contracts import WizardWorkerResourceUsage


def worker_resource_usage_to_record(resource_usage: WizardWorkerResourceUsage) -> dict[str, object]:
    return {
        "version": resource_usage.version,
        "cpu_cores": resource_usage.cpu_cores,
        "memory_gb": resource_usage.memory_gb,
        "disk_size_gb": resource_usage.disk_size_gb,
        "ttl_seconds": resource_usage.ttl_seconds,
        "ttl_expires_at": resource_usage.ttl_expires_at.isoformat(),
        "provider_cpu_usage_usec": resource_usage.provider_cpu_usage_usec,
        "provider_billed_cpu_usage_usec": resource_usage.provider_billed_cpu_usage_usec,
        "provider_usage_measured_at": (
            resource_usage.provider_usage_measured_at.isoformat()
            if resource_usage.provider_usage_measured_at is not None
            else None
        ),
    }


def worker_resource_usage_from_record(value: object) -> WizardWorkerResourceUsage:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Invalid Wizard Worker resource usage")

    cpu_cores = _positive_number(value.get("cpu_cores"))
    memory_gb = _positive_number(value.get("memory_gb"))
    disk_size_gb = _positive_number(value.get("disk_size_gb"))
    ttl_seconds = _positive_integer(value.get("ttl_seconds"))
    ttl_expires_at = _datetime(value.get("ttl_expires_at"))

    provider_cpu_usage_usec = _optional_nonnegative_integer(value.get("provider_cpu_usage_usec"))
    provider_billed_cpu_usage_usec = _optional_nonnegative_integer(value.get("provider_billed_cpu_usage_usec"))
    provider_usage_measured_at = _optional_datetime(value.get("provider_usage_measured_at"))

    return WizardWorkerResourceUsage(
        cpu_cores=cpu_cores,
        memory_gb=memory_gb,
        disk_size_gb=disk_size_gb,
        ttl_seconds=ttl_seconds,
        ttl_expires_at=ttl_expires_at,
        provider_cpu_usage_usec=provider_cpu_usage_usec,
        provider_billed_cpu_usage_usec=provider_billed_cpu_usage_usec,
        provider_usage_measured_at=provider_usage_measured_at,
    )


def _positive_number(value: object) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise ValueError("Invalid Wizard Worker resource usage")

    return float(value)


def _positive_integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("Invalid Wizard Worker resource usage")

    return value


def _optional_nonnegative_integer(value: object) -> int | None:
    if value is None:
        return None

    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Invalid Wizard Worker resource usage")

    return value


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Invalid Wizard Worker resource usage")

    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Invalid Wizard Worker resource usage") from error


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)
