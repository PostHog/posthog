from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async

from products.wizard.backend.facade import api as wizard_facade
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


async def _drain(generator, max_events: int):
    """Pull up to max_events from the async generator, stopping early on _StopStream."""
    events = []
    try:
        for _ in range(max_events):
            events.append(await anext(generator))
    except (_StopStream, StopAsyncIteration):
        pass
    return events


def _patch_subscribe(pubsub_mock):
    """Patch the facade's pubsub subscribe to yield the given mock."""
    return patch(
        "products.wizard.backend.facade.api.pubsub.subscribe",
        return_value=MagicMock(
            __enter__=MagicMock(return_value=pubsub_mock),
            __exit__=MagicMock(return_value=False),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_emits_initial_state_when_session_exists(team):
    await sync_to_async(wizard_facade.upsert)(_input(team.id))

    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = _StopStream()

    with _patch_subscribe(pubsub_mock):
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="onboarding", skill_id="nextjs")
        events = await _drain(gen, max_events=2)

    assert len(events) == 1
    assert events[0].startswith(b"data: ")
    assert b'"session_id":"onboarding-nextjs-2026-05-19T10:00:00Z"' in events[0]
    assert events[0].endswith(b"\n\n")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_skips_initial_event_when_no_session(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = _StopStream()

    with _patch_subscribe(pubsub_mock):
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = await _drain(gen, max_events=2)

    assert events == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_forwards_pubsub_messages(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = [
        {"type": "message", "data": b'{"session_id":"a"}'},
        {"type": "message", "data": b'{"session_id":"b"}'},
        _StopStream(),
    ]

    with _patch_subscribe(pubsub_mock):
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = await _drain(gen, max_events=5)

    assert events == [
        b'data: {"session_id":"a"}\n\n',
        b'data: {"session_id":"b"}\n\n',
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_emits_heartbeat_when_idle(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message.side_effect = [None, None, _StopStream()]

    # Force the heartbeat threshold to be zero so any idle tick emits one.
    with (
        _patch_subscribe(pubsub_mock),
        patch("products.wizard.backend.presentation.views.SSE_HEARTBEAT_INTERVAL_SECONDS", 0.0),
    ):
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = await _drain(gen, max_events=4)

    assert events == [b": ping\n\n", b": ping\n\n"]
