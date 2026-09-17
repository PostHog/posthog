from datetime import datetime
from typing import Literal

from posthog.dataclasses import frozen


@frozen
class WizardWorkerResourceUsage:
    cpu_cores: float
    memory_gb: float
    disk_size_gb: float
    ttl_seconds: int
    ttl_expires_at: datetime
    provider_cpu_usage_usec: int | None = None
    provider_billed_cpu_usage_usec: int | None = None
    provider_usage_measured_at: datetime | None = None
    version: Literal[1] = 1


@frozen
class WizardWorkerProvisioning:
    sandbox_id: str
    resource_usage: WizardWorkerResourceUsage


@frozen
class WizardWorkerUsageMeasurement:
    cpu_usage_usec: int | None
    billed_cpu_usage_usec: int | None
    measured_at: datetime


@frozen
class WizardWorkerTelemetry:
    resource_usage: WizardWorkerResourceUsage
    lifetime_seconds: float


@frozen
class SignedRepositoryCommit:
    repository: str
    branch: str
    commit_shas: tuple[str, ...]


@frozen
class RepositoryPullRequest:
    repository: str
    number: int
    url: str
    head_branch: str
    base_branch: str
