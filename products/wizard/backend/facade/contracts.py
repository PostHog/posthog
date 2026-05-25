"""
Contract types for wizard.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .enums import RunPhase, TaskStatus

STALE_AFTER = timedelta(minutes=10)


@dataclass(frozen=True)
class WizardTaskDTO:
    id: str
    title: str
    status: TaskStatus


@dataclass(frozen=True)
class WizardSessionDTO:
    session_id: str
    team_id: int
    workflow_id: str
    skill_id: str
    started_at: datetime
    run_phase: RunPhase
    tasks: tuple[WizardTaskDTO, ...]
    event_plan: dict[str, Any] | None
    error: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    is_stale: bool


@dataclass(frozen=True)
class UpsertWizardSessionRequest:
    """What the wizard CLI POSTs. team_id is derived from the URL, not the body."""

    session_id: str
    workflow_id: str
    skill_id: str
    started_at: datetime
    run_phase: RunPhase
    tasks: tuple[WizardTaskDTO, ...]
    event_plan: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class UpsertWizardSessionInput:
    team_id: int
    session_id: str
    workflow_id: str
    skill_id: str
    started_at: datetime
    run_phase: RunPhase
    tasks: tuple[WizardTaskDTO, ...]
    event_plan: dict[str, Any] | None
    error: dict[str, Any] | None
