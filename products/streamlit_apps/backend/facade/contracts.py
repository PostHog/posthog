"""
Contract types for streamlit_apps.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
syntax, same ``is_dataclass()`` compatibility (so ``DataclassSerializer`` keeps
working), but with runtime validation on construction. See
``products/visual_review/backend/facade/contracts.py`` for the pattern this mirrors.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class StreamlitAppUserInfo:
    """Lightweight user info for display purposes. Mirrors core UserBasicSerializer."""

    id: int
    uuid: UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: dict | None
    role_at_organization: str | None


@dataclass(frozen=True)
class AppVersionContract:
    id: UUID
    version_number: int
    zip_hash: str
    snapshot_id: str | None
    created_by: StreamlitAppUserInfo | None
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
    status: str
    active_version: AppVersionContract | None
    sandbox: AppSandboxContract | None
    created_by: StreamlitAppUserInfo | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConnectInfoContract:
    url: str
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class StreamlitConnectInfo:
    """Iframe connection info returned by the connect_info action."""

    iframe_url: str
    expires_in: int


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
