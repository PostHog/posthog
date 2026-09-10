"""Contract types for security."""

from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import Surface


@dataclass(frozen=True)
class SubjectInput:
    """Everything a caller knows about a request. Leave a field unset when it is unknown."""

    email: str | None = None
    user_uuid: str | None = None
    organization_ids: tuple[str, ...] = ()
    team_ids: tuple[int, ...] = ()
    ip: str | None = None


@dataclass(frozen=True)
class SurfaceDecision:
    surface: Surface
    blocked: bool
    rule_id: UUID | None = None
