from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from parameterized import parameterized

from products.event_definitions.backend.models import EventDefinition
from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardTaskDTO
from products.wizard.backend.facade.enums import RunPhase, TaskStatus
from products.wizard.backend.metrics import WIZARD_SESSIONS_FINISHED_TOTAL

from ee.models.event_definition import EnterpriseEventDefinition


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
    dto, created = wizard_facade.upsert(_input(team.id))

    assert created is True
    assert dto.session_id == "onboarding-nextjs-2026-05-19T10:00:00Z"
    assert dto.team_id == team.id
    assert dto.run_phase == RunPhase.RUNNING
    assert len(dto.tasks) == 1
    assert dto.tasks[0].status == TaskStatus.IN_PROGRESS


@pytest.mark.django_db
def test_upsert_with_same_session_id_replaces_state(team):
    _, first_created = wizard_facade.upsert(_input(team.id))
    assert first_created is True

    updated, second_created = wizard_facade.upsert(
        _input(
            team.id,
            run_phase=RunPhase.COMPLETED,
            tasks=(WizardTaskDTO(id="1", title="Install SDK", status=TaskStatus.COMPLETED),),
        )
    )

    assert second_created is False
    assert updated.run_phase == RunPhase.COMPLETED
    assert updated.tasks[0].status == TaskStatus.COMPLETED
    assert len(wizard_facade.list_for_team(team.id, limit=100)) == 1


@pytest.mark.django_db
def test_completed_transition_creates_event_definitions_once(team):
    event_plan = {"events": [{"name": "checkout_started", "description": "A checkout was started"}]}
    wizard_facade.upsert(_input(team.id, event_plan=event_plan))

    wizard_facade.upsert(_input(team.id, run_phase=RunPhase.COMPLETED, event_plan=event_plan))
    wizard_facade.upsert(
        _input(
            team.id,
            run_phase=RunPhase.COMPLETED,
            event_plan={"events": [{"name": "completed_push_only"}]},
        )
    )

    event_definition = EventDefinition.objects.get(team=team, project_id=team.project_id, name="checkout_started")
    assert event_definition.created_at is None
    assert event_definition.last_seen_at is None
    assert EventDefinition.objects.filter(team=team, name="checkout_started").count() == 1
    assert not EventDefinition.objects.filter(name="completed_push_only").exists()


@pytest.mark.django_db
def test_completed_transition_creates_enterprise_description(team):
    wizard_facade.upsert(
        _input(
            team.id,
            run_phase=RunPhase.COMPLETED,
            event_plan={"events": [{"name": "subscription_started", "description": "A subscription was started"}]},
        )
    )

    event_definition = EnterpriseEventDefinition.objects.get(
        team=team, project_id=team.project_id, name="subscription_started"
    )
    assert event_definition.description == "A subscription was started"


@parameterized.expand(
    [
        ("empty", ""),
        ("posthog", "$pageview"),
        ("too_long", "x" * 401),
    ]
)
@pytest.mark.django_db
def test_completed_transition_skips_invalid_event_names(_label, event_name, team):
    wizard_facade.upsert(_input(team.id, run_phase=RunPhase.COMPLETED, event_plan={"events": [{"name": event_name}]}))

    assert not EventDefinition.objects.filter(team=team).exists()


@pytest.mark.django_db
def test_completed_transition_caps_event_definitions(team):
    wizard_facade.upsert(
        _input(
            team.id,
            run_phase=RunPhase.COMPLETED,
            event_plan={"events": [{"name": f"planned_event_{index}"} for index in range(51)]},
        )
    )

    assert EventDefinition.objects.filter(team=team).count() == 50
    assert not EventDefinition.objects.filter(team=team, name="planned_event_50").exists()


@pytest.mark.django_db
@patch(
    "products.wizard.backend.logic.sessions.create_placeholder_event_definition",
    side_effect=RuntimeError("definition write failed"),
)
def test_event_definition_failure_does_not_break_completed_upsert(_mock_create_definition, team):
    session, created = wizard_facade.upsert(
        _input(team.id, run_phase=RunPhase.COMPLETED, event_plan={"events": [{"name": "checkout_started"}]})
    )

    assert created is True
    assert session.run_phase == RunPhase.COMPLETED


@pytest.mark.django_db
def test_upsert_with_different_session_id_creates_new_row(team):
    wizard_facade.upsert(_input(team.id, session_id="run-1"))
    wizard_facade.upsert(_input(team.id, session_id="run-2"))

    assert len(wizard_facade.list_for_team(team.id, limit=100)) == 2


@pytest.mark.django_db
def test_get_session_returns_matching_row(team):
    wizard_facade.upsert(_input(team.id, session_id="run-1"))

    found = wizard_facade.get(team.id, "run-1")
    assert found is not None
    assert found.session_id == "run-1"


@pytest.mark.django_db
def test_get_session_returns_none_when_missing(team):
    assert wizard_facade.get(team.id, "missing") is None


@pytest.mark.django_db
def test_get_latest_returns_most_recent_for_workflow_skill_pair(team):
    wizard_facade.upsert(
        _input(
            team.id,
            session_id="onboarding-nextjs-09:00",
            started_at=datetime(2026, 5, 19, 9, 0, 0, tzinfo=UTC),
        )
    )
    wizard_facade.upsert(
        _input(
            team.id,
            session_id="onboarding-nextjs-11:00",
            started_at=datetime(2026, 5, 19, 11, 0, 0, tzinfo=UTC),
        )
    )

    latest = wizard_facade.get_latest(team.id, "onboarding", "nextjs")
    assert latest is not None
    assert latest.session_id == "onboarding-nextjs-11:00"


@pytest.mark.django_db
def test_get_latest_ignores_other_workflow_skill_pairs(team):
    wizard_facade.upsert(_input(team.id, session_id="onboarding-nextjs-1", workflow_id="onboarding", skill_id="nextjs"))
    wizard_facade.upsert(
        _input(team.id, session_id="migration-amplitude-1", workflow_id="migration", skill_id="amplitude")
    )

    latest = wizard_facade.get_latest(team.id, "onboarding", "nextjs")
    assert latest is not None
    assert latest.session_id == "onboarding-nextjs-1"


@pytest.mark.django_db
def test_get_latest_returns_none_when_no_match(team):
    assert wizard_facade.get_latest(team.id, "missing", "missing") is None


@pytest.mark.django_db
def test_list_for_team_returns_sessions_ordered_by_started_at_desc(team):
    wizard_facade.upsert(
        _input(
            team.id,
            session_id="run-early",
            started_at=datetime(2026, 5, 19, 9, 0, 0, tzinfo=UTC),
        )
    )
    wizard_facade.upsert(
        _input(
            team.id,
            session_id="run-late",
            started_at=datetime(2026, 5, 19, 19, 0, 0, tzinfo=UTC),
        )
    )

    sessions = wizard_facade.list_for_team(team.id, limit=100)
    assert [s.session_id for s in sessions] == ["run-late", "run-early"]


@pytest.mark.django_db
def test_upsert_counts_a_terminal_transition_exactly_once(team):
    counter = WIZARD_SESSIONS_FINISHED_TOTAL.labels(workflow="other", outcome="completed")
    before = counter._value.get()

    wizard_facade.upsert(_input(team.id, run_phase=RunPhase.RUNNING))
    wizard_facade.upsert(_input(team.id, run_phase=RunPhase.COMPLETED))
    wizard_facade.upsert(_input(team.id, run_phase=RunPhase.COMPLETED))

    assert counter._value.get() == before + 1


@pytest.mark.django_db
def test_upsert_counts_a_session_created_already_terminal(team):
    counter = WIZARD_SESSIONS_FINISHED_TOTAL.labels(workflow="other", outcome="error")
    before = counter._value.get()

    wizard_facade.upsert(_input(team.id, run_phase=RunPhase.ERROR, error={"type": "boom", "message": "x"}))

    assert counter._value.get() == before + 1
