"""Public contracts for credential-free staged task execution."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from posthog.dataclasses import frozen


@frozen
class StagedRepositoryBinding:
    repository: str
    base_sha: str
    base_branch: str
    github_integration_id: int
    github_installation_id: str
    grant_version: str


@frozen
class StagedCapabilityManifest:
    version: int
    phase: Literal["analysis", "execution"]
    mcp_scope_preset: str
    disabled_tools: tuple[str, ...]


@frozen
class CreateStagedTaskInput:
    team_id: int
    caller_id: UUID
    actor_id: int
    idempotency_key: str
    origin_product: str
    title: str
    description: str
    analysis_manifest: StagedCapabilityManifest
    repository: StagedRepositoryBinding | None
    output_schema: dict[str, object] | None


@frozen
class CreatedStagedTask:
    staged_run_id: UUID
    task_id: UUID
    analysis_run_id: UUID


@frozen
class AdvanceStagedTaskInput:
    team_id: int
    caller_id: UUID
    staged_run_id: UUID
    idempotency_key: str
    execution_manifest: StagedCapabilityManifest


@frozen
class AdvancedStagedTask:
    staged_run_id: UUID
    task_id: UUID
    analysis_run_id: UUID
    execution_run_id: UUID


class InvalidStagedTaskBindingError(ValueError):
    """Raised when a caller cannot act on the requested staged lifecycle."""


def create_staged_task(input: CreateStagedTaskInput) -> CreatedStagedTask:
    from products.tasks.backend.logic.services.staged_task_runs import create_staged_task_run

    return create_staged_task_run(input)


def advance_staged_task(input: AdvanceStagedTaskInput) -> AdvancedStagedTask:
    from products.tasks.backend.logic.services.staged_task_runs import advance_staged_task_run

    return advance_staged_task_run(input)


def cancel_staged_task(*, team_id: int, caller_id: UUID, staged_run_id: UUID) -> bool:
    from products.tasks.backend.logic.services.staged_task_runs import cancel_staged_task_run

    return cancel_staged_task_run(team_id=team_id, caller_id=caller_id, staged_run_id=staged_run_id)
