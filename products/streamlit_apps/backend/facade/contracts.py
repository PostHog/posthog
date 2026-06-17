from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class AppVersionContract:
    id: UUID
    version_number: int
    zip_file: str
    zip_hash: str
    snapshot_id: str | None
    created_by_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class AppSandboxContract:
    status: str
    restart_count: int
    last_error: str
    started_at: datetime | None
    last_activity_at: datetime | None
    version_number: int | None


@dataclass(frozen=True)
class AppContract:
    id: UUID
    short_id: str
    name: str
    description: str
    cpu_cores: float
    memory_gb: float
    is_active: bool
    active_version: AppVersionContract | None
    sandbox: AppSandboxContract | None
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConnectInfoContract:
    url: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class CreateAppInput:
    name: str
    description: str = ""
    cpu_cores: float = 0.5
    memory_gb: float = 1


@dataclass(frozen=True)
class UpdateAppInput:
    name: str | None = None
    description: str | None = None
    cpu_cores: float | None = None
    memory_gb: float | None = None
