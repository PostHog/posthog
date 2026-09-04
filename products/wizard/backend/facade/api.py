"""
Facade for wizard.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from products.wizard.backend import metrics
from products.wizard.backend.facade.contracts import (
    CreatePullRequestArtifactInput,
    CreateWizardRunInput,
    ListWizardRunsInput,
    UpsertWizardSessionInput,
    WizardProgram,
    WizardRunArtifactDTO,
    WizardRunCreationResult,
    WizardRunDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunPage,
    WizardRunPullRequestArtifactDTO,
    WizardSessionDTO,
)
from products.wizard.backend.facade.enums import WizardRunStage, WizardRunStatus
from products.wizard.backend.facade.validation import validate_wizard_version as validate_wizard_version_value
from products.wizard.backend.logic import (
    registry as registry_service,
    runs as run_service,
    sessions,
)
from products.wizard.backend.logic.artifacts import service as artifacts
from products.wizard.backend.logic.sessions import pubsub


def upsert(params: UpsertWizardSessionInput) -> tuple[WizardSessionDTO, bool]:
    """Returns `(dto, created)` so callers can pick 201 vs 200."""
    return sessions.upsert_session(params)


def get(team_id: int, session_id: str) -> WizardSessionDTO | None:
    return sessions.get_session(team_id, session_id)


def get_latest(team_id: int, workflow_id: str, skill_id: str | None = None) -> WizardSessionDTO | None:
    return sessions.get_latest_session(team_id, workflow_id, skill_id)


def list_for_team(
    team_id: int,
    workflow_id: str | None = None,
    skill_id: str | None = None,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[WizardSessionDTO]:
    return sessions.list_sessions(
        team_id,
        workflow_id=workflow_id,
        skill_id=skill_id,
        offset=offset,
        limit=limit,
    )


@asynccontextmanager
async def subscribe_to_updates(
    team_id: int,
    workflow_id: str,
    skill_id: str | None = None,
) -> AsyncIterator[Any]:
    async with pubsub.subscribe(team_id, workflow_id, skill_id) as ps:
        yield ps


def serialize_dto(dto: WizardSessionDTO) -> bytes:
    return pubsub.serialize_dto(dto)


def record_latest_session_poll(raw_source: str | None, result: str) -> None:
    metrics.WIZARD_LATEST_SESSION_REQUESTS_TOTAL.labels(
        source=metrics.poll_source_label(raw_source), result=result
    ).inc()


def get_registry(*, distinct_id: str, organization_id: str) -> tuple[WizardProgram, ...]:
    return registry_service.get_registry(distinct_id=distinct_id, organization_id=organization_id)


def create_run(params: CreateWizardRunInput) -> WizardRunDTO:
    return run_service.create_run(params)


def create_run_with_result(params: CreateWizardRunInput) -> WizardRunCreationResult:
    return run_service.create_run_with_result(params)


def get_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    return run_service.get_run(team_id, run_id)


def list_runs(params: ListWizardRunsInput) -> WizardRunPage:
    return run_service.list_runs(params)


def update_run_stage(team_id: int, run_id: UUID, stage: WizardRunStage) -> WizardRunDTO:
    return run_service.update_run_stage(team_id, run_id, stage)


def cancel_run(team_id: int, run_id: UUID) -> WizardRunDTO:
    return run_service.cancel_run(team_id, run_id)


def update_run_status(
    team_id: int,
    run_id: UUID,
    status: WizardRunStatus,
    *,
    error_code: str | None = None,
) -> WizardRunDTO:
    return run_service.transition_run(team_id, run_id, status, error_code=error_code)


def create_git_diff_artifact(team_id: int, run_id: UUID, content: bytes) -> WizardRunGitDiffArtifactDTO | None:
    return artifacts.create_git_diff_artifact(team_id, run_id, content)


def create_pull_request_artifact(params: CreatePullRequestArtifactInput) -> WizardRunPullRequestArtifactDTO:
    return artifacts.create_pull_request_artifact(params)


def list_run_artifacts(team_id: int, run_id: UUID) -> list[WizardRunArtifactDTO]:
    return artifacts.list_run_artifacts(team_id, run_id)


def get_git_diff_artifact_content(team_id: int, run_id: UUID, artifact_id: UUID) -> bytes:
    return artifacts.get_git_diff_artifact_content(team_id, run_id, artifact_id)


def validate_git_repository(repository: str) -> None:
    run_service.validate_git_repository_name(repository)


def validate_wizard_version(wizard_version: object) -> str:
    return validate_wizard_version_value(wizard_version)
