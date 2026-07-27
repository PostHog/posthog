"""
Contract types for foundry.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.

Uses ``pydantic.dataclasses.dataclass`` rather than the stdlib
variant — same syntax, same ``is_dataclass()`` compatibility (so
``DataclassSerializer`` keeps working), but with runtime type
validation on construction.
"""

from dataclasses import field
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import BetEventKind, BetState, BetVerdict, ExecutionMode, NodeStatus


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
    execution_mode: ExecutionMode
    run_config: dict[str, Any]
    memory_repo_url: str | None
    feature_flag_id: int | None
    feature_flag_key: str | None
    experiment_id: int | None
    created_by_id: int | None
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
class BetNodeDTO:
    id: UUID
    bet_id: UUID
    parent_id: UUID | None
    node_id: str
    status: NodeStatus
    runner: str
    depth: int
    max_cost: float | None
    max_depth: int | None
    max_children: int | None
    cost_so_far: float
    sandbox_external_id: str | None
    created_at: datetime
    updated_at: datetime


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
    execution_mode: ExecutionMode = ExecutionMode.EXTERNAL
    run_config: dict[str, Any] = field(default_factory=dict)
    memory_repo_url: str | None = None
