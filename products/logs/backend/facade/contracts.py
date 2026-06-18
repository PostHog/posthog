"""Contract types for logs.

Stable, framework-free frozen dataclasses that define what this product exposes to the
rest of the codebase. No Django imports.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant — same
shape and ``is_dataclass()`` compatibility, but with runtime validation on
construction, so a malformed mapper or caller surfaces at the facade boundary instead
of producing a bad payload downstream.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TeamLogsConfig:
    """A team's logs configuration (env-scoped, keyed by team_id)."""

    logs_distinct_id_attribute_key: str


@dataclass(frozen=True)
class LogsUserBasicInfo:
    """Lightweight creator info — only what the saved-views / alerts UIs render.

    Logs-scoped name (not the shared ``UserBasicInfo``) so the generated OpenAPI
    component doesn't collide with other products' identically-named contracts.
    """

    id: int
    first_name: str
    email: str


@dataclass(frozen=True)
class LogsView:
    """A saved logs view."""

    id: UUID
    short_id: str
    name: str
    filters: dict
    pinned: bool
    created_at: datetime
    updated_at: datetime
    created_by: LogsUserBasicInfo | None
