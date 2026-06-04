from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from posthog.schema import RelevantCommit

from products.signals.backend.report_generation.research import ActionabilityAssessment, PriorityAssessment

if TYPE_CHECKING:
    from products.signals.backend.custom_agent.base import CustomSignalAgent

_IDENTIFIER_PART_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class CustomAgentIdentifierError(ValueError):
    """Raised when a custom agent product/type/run identifier is not safe for routing."""


def validate_identifier_part(value: str, *, field_name: str) -> str:
    """Validate a product/type component used in workflow IDs and routing."""
    normalized = value.strip()
    if not normalized:
        raise CustomAgentIdentifierError(f"{field_name} must not be empty")
    if not _IDENTIFIER_PART_RE.fullmatch(normalized):
        raise CustomAgentIdentifierError(
            f"{field_name} must contain only lowercase letters, numbers, underscores, or hyphens, "
            "and must start with a lowercase letter or number"
        )
    return normalized


def validate_identifier(product: str, type_: str) -> tuple[str, str]:
    return (
        validate_identifier_part(product, field_name="product"),
        validate_identifier_part(type_, field_name="type"),
    )


def validate_run_id(value: str) -> str:
    return validate_identifier_part(value, field_name="id")


def validated_identifier(agent_class: type[CustomSignalAgent]) -> tuple[str, str]:
    """Call ``agent_class.identifier()`` and verify its shape + part syntax."""
    identifier = agent_class.identifier()
    if not isinstance(identifier, tuple) or len(identifier) != 2:
        raise CustomAgentIdentifierError("identifier() must return a (product, type) tuple")
    return validate_identifier(identifier[0], identifier[1])


class ScheduleAgentResult(StrEnum):
    """Outcome of an idempotent ``schedule_agent`` call."""

    CREATED = "created"
    UPDATED = "updated"
    ALREADY_PRESENT = "already_present"


# Inclusive (min, max) bounds for each calendar field. day_of_week is 0=Sunday..6=Saturday,
# matching Temporal's ScheduleRange convention.
_CALENDAR_FIELD_BOUNDS: dict[str, tuple[int, int]] = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "day_of_week": (0, 6),
}


class AgentScheduleError(ValueError):
    """Raised when an ``AgentScheduleSpec`` is empty or has out-of-range fields."""


@dataclass(frozen=True)
class AgentScheduleSpec:
    """Temporal-free structured calendar for recurring custom-agent runs.

    Each set field narrows when the schedule fires; unset (``None``) fields match
    every value (so ``AgentScheduleSpec(hour=9, minute=0)`` fires daily at 09:00).
    Mapped to a Temporal ``ScheduleCalendarSpec`` by the launcher in
    ``temporal/custom_agent.py``. At least one calendar field must be set.
    """

    minute: int | list[int] | None = None
    hour: int | list[int] | None = None
    day_of_month: int | list[int] | None = None
    month: int | list[int] | None = None
    day_of_week: int | list[int] | None = None
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        # Use the canonical values so an empty list (e.g. hour=[]) doesn't count as "set" —
        # it maps to an empty ScheduleCalendarSpec field that matches every value, which
        # would otherwise sneak past this guard and schedule the agent every minute.
        if all(not self.values_for(name) for name in _CALENDAR_FIELD_BOUNDS):
            raise AgentScheduleError("AgentScheduleSpec must set at least one non-empty calendar field")
        if not self.timezone.strip():
            raise AgentScheduleError("timezone must not be empty")
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:
            # Fail at construction with a clear error rather than deferring to an opaque
            # Temporal RPC error when the schedule is created or fires.
            raise AgentScheduleError(f"timezone {self.timezone!r} is not a valid IANA time zone") from exc
        for name, (low, high) in _CALENDAR_FIELD_BOUNDS.items():
            for value in self.values_for(name):
                if value < low or value > high:
                    raise AgentScheduleError(f"{name} value {value} out of range [{low}, {high}]")

    def values_for(self, name: str) -> list[int]:
        """Return the canonical (sorted, de-duplicated) values for a calendar field.

        Returns an empty list when unset. Canonicalizing here means ``hour=9``,
        ``hour=[9]``, ``hour=[9, 9]`` and ``hour=[9, 0]`` vs ``[0, 9]`` all collapse to
        the same effective schedule — so the launcher's idempotency fingerprint and the
        emitted ``ScheduleCalendarSpec`` don't churn on equivalent inputs.
        """
        raw = getattr(self, name)
        if raw is None:
            return []
        values = [raw] if isinstance(raw, int) else list(raw)
        return sorted(set(values))


class CustomAgentAssignee(BaseModel):
    github_login: str = Field(description="GitHub username/login to suggest as reviewer or assignee.")
    github_name: str | None = Field(default=None, description="Optional display name from GitHub.")
    relevant_commits: list[RelevantCommit] = Field(
        default_factory=list,
        description="Optional commit evidence explaining why this assignee is relevant.",
    )

    @field_validator("github_login")
    @classmethod
    def normalize_github_login(cls, value: str) -> str:
        normalized = value.strip().lower().lstrip("@")
        if not normalized:
            raise ValueError("github_login must not be empty")
        return normalized


@dataclass(frozen=True)
class CustomAgentRunHandle:
    workflow_id: str
    run_id: str
    started: bool
    """True if this call started the workflow; False if a workflow with the same id was already running."""


@dataclass
class CustomAgentWorkflowInput:
    team_id: int
    agent_path: str
    product: str
    type: str
    run_id: str
    initial_prompt: str
    repository: str | None
    model: str | None = None
    scheduled: bool = False
    """True when this run was launched by a Temporal schedule rather than a one-off `run_agent` call."""


@dataclass
class CustomAgentWorkflowOutput:
    report_ids: list[str]
    repository: str | None
    task_id: str | None


@dataclass(frozen=True)
class CustomAgentFinalReport:
    title: str
    description: str
    actionability: ActionabilityAssessment
    assignees: list[CustomAgentAssignee]
    priority: PriorityAssessment | None
