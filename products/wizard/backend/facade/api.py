"""
Facade for wizard.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardSessionDTO
from products.wizard.backend.logic import sessions


def upsert(params: UpsertWizardSessionInput) -> WizardSessionDTO:
    return sessions.upsert_session(params)


def get(team_id: int, session_id: str) -> WizardSessionDTO | None:
    return sessions.get_session(team_id, session_id)


def get_latest(team_id: int, workflow_id: str, skill_id: str) -> WizardSessionDTO | None:
    return sessions.get_latest_session(team_id, workflow_id, skill_id)


def list_for_team(
    team_id: int,
    workflow_id: str | None = None,
    skill_id: str | None = None,
) -> list[WizardSessionDTO]:
    return sessions.list_sessions(team_id, workflow_id=workflow_id, skill_id=skill_id)
