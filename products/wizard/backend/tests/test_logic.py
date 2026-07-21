from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from django.test import override_settings

from posthog.models import Team

from products.event_definitions.backend.models import EventDefinition
from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardTaskDTO
from products.wizard.backend.facade.enums import RunPhase, TaskStatus
from products.wizard.backend.metrics import WIZARD_SESSIONS_FINISHED_TOTAL
from products.wizard.backend.tasks.tasks import sync_wizard_event_definitions

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
@patch("products.wizard.backend.logic.sessions.sync_wizard_event_definitions.delay")
def test_upsert_with_same_session_id_replaces_state(_mock_sync, team):
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
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_completed_transition_creates_event_definitions_once(team, django_capture_on_commit_callbacks):
    event_plan = {"events": [{"name": "checkout_started", "description": "A checkout was started"}]}
    wizard_facade.upsert(_input(team.id, event_plan=event_plan))

    with django_capture_on_commit_callbacks(execute=True):
        completed_session, _ = wizard_facade.upsert(_input(team.id, run_phase=RunPhase.COMPLETED))
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
    assert completed_session.event_plan == event_plan
    assert EventDefinition.objects.filter(team=team, name="checkout_started").count() == 1
    assert not EventDefinition.objects.filter(name="completed_push_only").exists()


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_completed_transition_creates_enterprise_description(team, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
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


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
@pytest.mark.parametrize("event_name", ["", "$pageview", " $pageview ", "x" * 401])
def test_completed_transition_skips_invalid_event_names(team, django_capture_on_commit_callbacks, event_name):
    with django_capture_on_commit_callbacks(execute=True):
        wizard_facade.upsert(
            _input(team.id, run_phase=RunPhase.COMPLETED, event_plan={"events": [{"name": event_name}]})
        )

    assert not EventDefinition.objects.filter(team=team).exists()


@pytest.mark.django_db
@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_completed_transition_caps_valid_unique_event_definitions(team, django_capture_on_commit_callbacks):
    invalid_and_duplicate_events = [{"name": ""} for _ in range(50)] + [
        {"name": " planned_event_0 "},
        {"name": "planned_event_0"},
    ]
    with django_capture_on_commit_callbacks(execute=True):
        wizard_facade.upsert(
            _input(
                team.id,
                run_phase=RunPhase.COMPLETED,
                event_plan={
                    "events": invalid_and_duplicate_events + [{"name": f"planned_event_{index}"} for index in range(51)]
                },
            )
        )

    assert EventDefinition.objects.filter(team=team).count() == 50
    assert EventDefinition.objects.filter(team=team, name="planned_event_0").count() == 1
    assert not EventDefinition.objects.filter(team=team, name="planned_event_50").exists()


@pytest.mark.django_db
@patch(
    "products.wizard.backend.logic.sessions.sync_wizard_event_definitions.delay",
    side_effect=RuntimeError("task dispatch failed"),
)
def test_event_definition_dispatch_failure_does_not_break_completed_upsert(
    _mock_sync, team, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        session, created = wizard_facade.upsert(
            _input(team.id, run_phase=RunPhase.COMPLETED, event_plan={"events": [{"name": "checkout_started"}]})
        )

    assert created is True
    assert session.run_phase == RunPhase.COMPLETED


@pytest.mark.django_db
def test_event_definition_task_recovers_after_transient_failure(team):
    with patch("products.wizard.backend.logic.sessions.sync_wizard_event_definitions.delay"):
        session, _ = wizard_facade.upsert(
            _input(team.id, run_phase=RunPhase.COMPLETED, event_plan={"events": [{"name": "checkout_started"}]})
        )

    with (
        patch(
            "products.wizard.backend.tasks.tasks.create_placeholder_event_definitions",
            side_effect=RuntimeError("definition write failed"),
        ),
        pytest.raises(RuntimeError, match="definition write failed"),
    ):
        sync_wizard_event_definitions.run(team.id, session.session_id)

    sync_wizard_event_definitions.run(team.id, session.session_id)

    assert EventDefinition.objects.filter(team=team, name="checkout_started").exists()


@pytest.mark.django_db
def test_event_definition_task_uses_latest_completed_session_state(team):
    with patch("products.wizard.backend.logic.sessions.sync_wizard_event_definitions.delay"):
        session, _ = wizard_facade.upsert(
            _input(team.id, run_phase=RunPhase.COMPLETED, event_plan={"events": [{"name": "stale_completed_plan"}]})
        )
    wizard_facade.upsert(_input(team.id, run_phase=RunPhase.RUNNING, event_plan=None))

    sync_wizard_event_definitions.run(team.id, session.session_id)

    assert not EventDefinition.objects.filter(team=team, name="stale_completed_plan").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("is_legacy", [False, True])
def test_event_definition_task_reuses_definition_from_sibling_environment(team, is_legacy):
    sibling_team = Team.objects.create(
        organization=team.organization,
        project=team.project,
        name="Sibling environment",
    )
    existing_definition = EventDefinition.objects.create(
        team=team,
        project=None if is_legacy else team.project,
        name="checkout_started",
        created_at=None,
        last_seen_at=None,
    )
    with patch("products.wizard.backend.logic.sessions.sync_wizard_event_definitions.delay"):
        session, _ = wizard_facade.upsert(
            _input(
                sibling_team.id,
                run_phase=RunPhase.COMPLETED,
                event_plan={"events": [{"name": "checkout_started", "description": "A checkout was started"}]},
            )
        )

    sync_wizard_event_definitions.run(sibling_team.id, session.session_id)

    assert EventDefinition.objects.filter(name="checkout_started").count() == 1
    enterprise_definition = EnterpriseEventDefinition.objects.get(pk=existing_definition.pk)
    assert enterprise_definition.description == "A checkout was started"


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
@patch("products.wizard.backend.logic.sessions.sync_wizard_event_definitions.delay")
def test_upsert_counts_a_terminal_transition_exactly_once(_mock_sync, team):
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
