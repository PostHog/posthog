"""
Contract types for endpoints.

Stable, framework-free frozen dataclasses that define what this product
exposes to the rest of the codebase. No Django imports.

Pydantic dataclasses (not stdlib) so structural mistakes from mappers or
internal callers surface at the facade boundary with a ValidationError
instead of producing a malformed payload downstream.
"""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class EndpointInfo:
    """An endpoint (team-scoped, name-addressed). Version-specific data lives on EndpointVersionInfo."""

    id: UUID
    team_id: int
    name: str
    is_active: bool
    current_version: int
    derived_from_insight: str | None
    created_at: datetime
    updated_at: datetime
    last_executed_at: datetime | None


@dataclass(frozen=True)
class EndpointVersionInfo:
    """An immutable query snapshot for one endpoint version."""

    id: UUID
    endpoint_id: UUID
    version: int
    query: dict
    description: str
    data_freshness_seconds: int
    is_active: bool
    is_materialized: bool
    created_at: datetime
    last_executed_at: datetime | None
