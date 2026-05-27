"""
Facade for wizard.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from __future__ import annotations

from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardSessionDTO
from products.wizard.backend.logic import sessions


def upsert(params: UpsertWizardSessionInput) -> tuple[WizardSessionDTO, bool]:
    """Upsert a session and report whether the row was newly created.

    Returns `(dto, created)` so consumers can distinguish 201 from 200 in
    their response semantics, and so retry-aware clients can short-circuit
    after the first successful write.
    """
    return sessions.upsert_session(params)


def get(team_id: int, session_id: str) -> WizardSessionDTO | None:
    return sessions.get_session(team_id, session_id)


def get_latest(team_id: int, workflow_id: str, skill_id: str) -> WizardSessionDTO | None:
    return sessions.get_latest_session(team_id, workflow_id, skill_id)


def list_for_team(
    team_id: int,
    workflow_id: str | None = None,
    skill_id: str | None = None,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> list[WizardSessionDTO]:
    """List sessions for a team, ordered by started_at desc.

    `offset`/`limit` are applied at the SQL layer; callers should pass a
    bounded `limit` for any user-facing list endpoint so the read cost stays
    bounded regardless of per-team row count.
    """
    return sessions.list_sessions(
        team_id,
        workflow_id=workflow_id,
        skill_id=skill_id,
        offset=offset,
        limit=limit,
    )
