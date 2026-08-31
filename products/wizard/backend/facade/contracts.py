"""
Contract types for wizard.

Frozen dataclasses that define what this product exposes.
No Django imports. Used by facade as inputs/outputs.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from posthog.dataclasses import frozen

from .enums import (
    WizardRunArtifactType,
    WizardRunEnvironment,
    WizardRunStage,
    WizardRunStatus,
    WizardSessionRunPhase,
    WizardSessionTaskStatus,
)


@dataclass(frozen=True)
class WizardTaskDTO:
    id: str
    title: str
    status: WizardSessionTaskStatus


@dataclass(frozen=True)
class WizardSessionUserDTO:
    id: int
    first_name: str
    email: str


@dataclass(frozen=True)
class WizardSessionDTO:
    session_id: str
    team_id: int
    workflow_id: str
    skill_id: str
    started_at: datetime
    run_phase: WizardSessionRunPhase
    tasks: tuple[WizardTaskDTO, ...]
    event_plan: dict[str, Any] | None
    error: dict[str, Any] | None
    pending_input: dict[str, Any] | None
    handoff_text: str | None
    created_by: WizardSessionUserDTO | None
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
    run_phase: WizardSessionRunPhase
    tasks: tuple[WizardTaskDTO, ...]
    event_plan: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    pending_input: dict[str, Any] | None = None
    handoff_text: str | None = None


@dataclass(frozen=True)
class UpsertWizardSessionInput:
    team_id: int
    session_id: str
    workflow_id: str
    skill_id: str
    started_at: datetime
    run_phase: WizardSessionRunPhase
    tasks: tuple[WizardTaskDTO, ...]
    event_plan: dict[str, Any] | None
    error: dict[str, Any] | None
    pending_input: dict[str, Any] | None
    handoff_text: str | None = None
    # Set on create only, never overwritten on later pushes for the same run.
    created_by_id: int | None = None


@frozen
class LocalFolderWorkspace:
    project_name: str
    type: Literal["local_folder"] = "local_folder"


@frozen
class GitRepositoryWorkspace:
    repository: str
    type: Literal["git_repository"] = "git_repository"


type WizardWorkspace = LocalFolderWorkspace | GitRepositoryWorkspace


@frozen
class WizardProgram:
    id: str
    name: str
    description: str
    wizard_version: str
    command: tuple[str, ...]
    tags: tuple[str, ...]
    required_programs: tuple[str, ...]
    supported_environments: tuple[WizardRunEnvironment, ...]


@frozen
class WizardRegistry:
    programs: tuple[WizardProgram, ...]
    version: Literal[1] = 1


@frozen
class CreateWizardRunInput:
    team_id: int
    created_by_id: int
    environment: WizardRunEnvironment
    workspace: WizardWorkspace
    program_id: str
    wizard_version: str | None = None
    idempotency_key: str | None = None


@frozen
class WizardRunCreationResult:
    run: "WizardRunDTO"
    created: bool


@frozen
class WizardRunDTO:
    id: UUID
    team_id: int
    created_by_id: int | None
    environment: WizardRunEnvironment
    workspace: WizardWorkspace
    program: WizardProgram
    status: WizardRunStatus
    error_code: str | None
    error_message: str | None
    stage: WizardRunStage | None
    created_at: datetime
    updated_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    deadline_at: datetime | None


@frozen
class ListWizardRunsInput:
    team_id: int
    offset: int
    limit: int


@frozen
class WizardRunPage:
    results: tuple[WizardRunDTO, ...]
    count: int


@frozen
class CreatePullRequestArtifactInput:
    team_id: int
    run_id: UUID
    url: str
    number: int
    repository: str
    head_branch: str
    base_branch: str


@frozen
class WizardRunGitDiffArtifactDTO:
    id: UUID
    team_id: int
    run_id: UUID
    artifact_type: Literal[WizardRunArtifactType.GIT_DIFF]
    size_bytes: int
    content_hash: str
    additions: int | None
    removals: int | None
    created_at: datetime


@frozen
class WizardRunPullRequestArtifactDTO:
    id: UUID
    team_id: int
    run_id: UUID
    artifact_type: Literal[WizardRunArtifactType.PULL_REQUEST]
    url: str
    number: int
    repository: str
    head_branch: str
    base_branch: str
    created_at: datetime


type WizardRunArtifactDTO = WizardRunGitDiffArtifactDTO | WizardRunPullRequestArtifactDTO
