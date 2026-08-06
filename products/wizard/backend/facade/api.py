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

from products.wizard.backend import metrics
from products.wizard.backend.facade.contracts import (
    UpsertWizardRepositoryDetectionInput,
    UpsertWizardSessionInput,
    WizardRepositoryDetectionDTO,
    WizardSessionDTO,
)
from products.wizard.backend.logic import pubsub, repository_detections, sessions


def upsert(params: UpsertWizardSessionInput) -> tuple[WizardSessionDTO, bool]:
    """Returns `(dto, created)` so callers can pick 201 vs 200."""
    return sessions.upsert_session(params)


def upsert_wizard_repository_detection(
    params: UpsertWizardRepositoryDetectionInput,
) -> tuple[WizardRepositoryDetectionDTO, bool]:
    """Returns `(dto, created)` so callers can pick 201 vs 200."""
    return repository_detections.upsert_wizard_repository_detection(params)


def record_wizard_repository_detection_run(
    *,
    team_id: int,
    repository: str,
    kind: str,
    task_run_id: str,
    created_by_id: int | None = None,
) -> WizardRepositoryDetectionDTO:
    """Stamp a triggered cloud scan's run id onto the (repository, kind) row, keeping any
    previous report/error readable while the scan runs."""
    return repository_detections.record_wizard_repository_detection_run(
        team_id=team_id,
        repository=repository,
        kind=kind,
        task_run_id=task_run_id,
        created_by_id=created_by_id,
    )


def get_wizard_repository_detection(team_id: int, repository: str, kind: str) -> WizardRepositoryDetectionDTO | None:
    """The (repository, kind) detection row, or None."""
    return repository_detections.get_wizard_repository_detection(team_id, repository, kind)


def list_wizard_repository_detections(
    team_id: int, *, kind: str | None = None, limit: int = 200
) -> list[WizardRepositoryDetectionDTO]:
    """The team's detection rows, most recently updated first."""
    return repository_detections.list_wizard_repository_detections(team_id, kind=kind, limit=limit)


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
