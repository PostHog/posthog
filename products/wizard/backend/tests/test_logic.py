from datetime import UTC, datetime

import pytest

from products.wizard.backend.facade.api import WizardSessionAPI
from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardTaskDTO
from products.wizard.backend.facade.enums import RunPhase, TaskStatus


def _input(team_id: int, **overrides) -> UpsertWizardSessionInput:
    params: dict = {
        "team_id": team_id,
        "session_id": "onboarding-nextjs-2026-05-19T10:00:00Z",
        "workflow_id": "onboarding",
        "skill_id": "nextjs",
        "started_at": datetime(2026, 5, 19, 10, 0, 0, tzinfo=UTC),
        "run_phase": RunPhase.RUNNING,
        "tasks": (WizardTaskDTO(id="1", title="Install SDK", status=TaskStatus.IN_PROGRESS),),
        "event_plan": None,
        "error": None,
    }
    params.update(overrides)
    return UpsertWizardSessionInput(**params)


@pytest.mark.django_db
def test_upsert_creates_new_session(team):
    dto = WizardSessionAPI.upsert(_input(team.id))

    assert dto.session_id == "onboarding-nextjs-2026-05-19T10:00:00Z"
    assert dto.team_id == team.id
    assert dto.run_phase == RunPhase.RUNNING
    assert len(dto.tasks) == 1
    assert dto.tasks[0].status == TaskStatus.IN_PROGRESS


@pytest.mark.django_db
def test_upsert_with_same_session_id_replaces_state(team):
    WizardSessionAPI.upsert(_input(team.id))

    updated = WizardSessionAPI.upsert(
        _input(
            team.id,
            run_phase=RunPhase.COMPLETED,
            tasks=(WizardTaskDTO(id="1", title="Install SDK", status=TaskStatus.COMPLETED),),
        )
    )

    assert updated.run_phase == RunPhase.COMPLETED
    assert updated.tasks[0].status == TaskStatus.COMPLETED
    assert len(WizardSessionAPI.list_for_team(team.id)) == 1


@pytest.mark.django_db
def test_upsert_with_different_session_id_creates_new_row(team):
    WizardSessionAPI.upsert(_input(team.id, session_id="run-1"))
    WizardSessionAPI.upsert(_input(team.id, session_id="run-2"))

    assert len(WizardSessionAPI.list_for_team(team.id)) == 2


@pytest.mark.django_db
def test_get_session_returns_matching_row(team):
    WizardSessionAPI.upsert(_input(team.id, session_id="run-1"))

    found = WizardSessionAPI.get(team.id, "run-1")
    assert found is not None
    assert found.session_id == "run-1"


@pytest.mark.django_db
def test_get_session_returns_none_when_missing(team):
    assert WizardSessionAPI.get(team.id, "missing") is None


@pytest.mark.django_db
def test_get_latest_returns_most_recent_for_workflow_skill_pair(team):
    WizardSessionAPI.upsert(
        _input(
            team.id,
            session_id="onboarding-nextjs-09:00",
            started_at=datetime(2026, 5, 19, 9, 0, 0, tzinfo=UTC),
        )
    )
    WizardSessionAPI.upsert(
        _input(
            team.id,
            session_id="onboarding-nextjs-11:00",
            started_at=datetime(2026, 5, 19, 11, 0, 0, tzinfo=UTC),
        )
    )

    latest = WizardSessionAPI.get_latest(team.id, "onboarding", "nextjs")
    assert latest is not None
    assert latest.session_id == "onboarding-nextjs-11:00"


@pytest.mark.django_db
def test_get_latest_ignores_other_workflow_skill_pairs(team):
    WizardSessionAPI.upsert(
        _input(team.id, session_id="onboarding-nextjs-1", workflow_id="onboarding", skill_id="nextjs")
    )
    WizardSessionAPI.upsert(
        _input(team.id, session_id="migration-amplitude-1", workflow_id="migration", skill_id="amplitude")
    )

    latest = WizardSessionAPI.get_latest(team.id, "onboarding", "nextjs")
    assert latest is not None
    assert latest.session_id == "onboarding-nextjs-1"


@pytest.mark.django_db
def test_get_latest_returns_none_when_no_match(team):
    assert WizardSessionAPI.get_latest(team.id, "missing", "missing") is None


@pytest.mark.django_db
def test_list_for_team_returns_sessions_ordered_by_started_at_desc(team):
    WizardSessionAPI.upsert(
        _input(
            team.id,
            session_id="run-early",
            started_at=datetime(2026, 5, 19, 9, 0, 0, tzinfo=UTC),
        )
    )
    WizardSessionAPI.upsert(
        _input(
            team.id,
            session_id="run-late",
            started_at=datetime(2026, 5, 19, 19, 0, 0, tzinfo=UTC),
        )
    )

    sessions = WizardSessionAPI.list_for_team(team.id)
    assert [s.session_id for s in sessions] == ["run-late", "run-early"]
