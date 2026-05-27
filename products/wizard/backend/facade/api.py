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

from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardSessionDTO
from products.wizard.backend.logic import pubsub, sessions


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
