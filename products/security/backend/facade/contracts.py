"""Contract types for security."""

from pydantic.dataclasses import dataclass

from .enums import Outcome, Surface


@dataclass(frozen=True)
class SubjectInput:
    """Everything a call site knows about a request. Leave a field unset when it is unknown."""

    email: str | None = None
    user_uuid: str | None = None
    organization_ids: tuple[str, ...] = ()
    ip: str | None = None


@dataclass(frozen=True)
class Decision:
    surface: Surface
    outcome: Outcome
    rule_id: str | None = None
    target_type: str | None = None
