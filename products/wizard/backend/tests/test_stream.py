from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from products.wizard.backend.facade.contracts import UpsertWizardSessionInput, WizardTaskDTO
from products.wizard.backend.facade.enums import RunPhase, TaskStatus
from products.wizard.backend.presentation.views import _wizard_session_event_stream


class _StopStream(Exception):
    """Helper to break the infinite generator after we've collected what we want."""


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


def _drain(generator, max_events: int):
    """Pull up to max_events from generator, stopping early if it raises _StopStream."""
    events = []
    try:
        for _ in range(max_events):
            events.append(next(generator))
    except _StopStream:
        pass
    return events


@pytest.mark.django_db
def test_stream_emits_initial_state_when_session_exists(team):
    from products.wizard.backend.facade import api as wizard_facade

    wizard_facade.upsert(_input(team.id))

    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = _StopStream()

    with patch("products.wizard.backend.presentation.views.subscribe") as subscribe_mock:
        subscribe_mock.return_value.__enter__.return_value = pubsub_mock
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="onboarding", skill_id="nextjs")
        events = _drain(gen, max_events=2)

    assert len(events) == 1
    assert events[0].startswith(b"data: ")
    assert b'"session_id":"onboarding-nextjs-2026-05-19T10:00:00Z"' in events[0]
    assert events[0].endswith(b"\n\n")


@pytest.mark.django_db
def test_stream_skips_initial_event_when_no_session(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = _StopStream()

    with patch("products.wizard.backend.presentation.views.subscribe") as subscribe_mock:
        subscribe_mock.return_value.__enter__.return_value = pubsub_mock
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = _drain(gen, max_events=2)

    assert events == []


@pytest.mark.django_db
def test_stream_forwards_pubsub_messages(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = [
        {"type": "message", "data": b'{"session_id":"a"}'},
        {"type": "message", "data": b'{"session_id":"b"}'},
        _StopStream(),
    ]

    with patch("products.wizard.backend.presentation.views.subscribe") as subscribe_mock:
        subscribe_mock.return_value.__enter__.return_value = pubsub_mock
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = _drain(gen, max_events=5)

    assert events == [
        b'data: {"session_id":"a"}\n\n',
        b'data: {"session_id":"b"}\n\n',
    ]


@pytest.mark.django_db
def test_stream_emits_heartbeat_when_idle(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = [None, None, _StopStream()]

    # Force the heartbeat threshold to be zero so any idle tick emits one.
    with (
        patch("products.wizard.backend.presentation.views.subscribe") as subscribe_mock,
        patch("products.wizard.backend.presentation.views.SSE_HEARTBEAT_INTERVAL_SECONDS", 0.0),
    ):
        subscribe_mock.return_value.__enter__.return_value = pubsub_mock
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = _drain(gen, max_events=4)

    assert events == [b": ping\n\n", b": ping\n\n"]
