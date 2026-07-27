"""
Contract types for foundry.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.

Uses ``pydantic.dataclasses.dataclass`` rather than the stdlib
variant — same syntax, same ``is_dataclass()`` compatibility (so
``DataclassSerializer`` keeps working), but with runtime type
validation on construction.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import BetEventKind, BetState, BetVerdict


@dataclass(frozen=True)
class BetDTO:
    id: UUID
    slug: str
    hypothesis: str
    success_metric: dict[str, Any]
    guardrails: list[dict[str, Any]]
    budget: dict[str, Any]
    exposure_plan: dict[str, Any]
    sources: list[dict[str, Any]]
    ttl: datetime | None
    state: BetState
    verdict: BetVerdict | None
    iteration: int
    feature_flag_id: int | None
    feature_flag_key: str | None
    experiment_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BetEventDTO:
    id: UUID
    bet_id: UUID
    kind: BetEventKind
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class CreateBetInput:
    team_id: int
    slug: str
    hypothesis: str
    success_metric: dict[str, Any]
    guardrails: list[dict[str, Any]]
    budget: dict[str, Any]
    exposure_plan: dict[str, Any]
    sources: list[dict[str, Any]]
    ttl: datetime | None = None
