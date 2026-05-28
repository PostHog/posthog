from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
        "session_id": "onboarding-nextjs-2026-05-19T10-00-00Z",
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
    finally:
        # Close the generator so its `async with` runs cleanup (closes the
        # Redis subscription). Without this, leaked subscriptions would pass
        # the tests silently.
        await generator.aclose()
    return events


def _async_subscribe_cm(pubsub_mock):
    """Build an async context manager that yields the given pubsub mock.

    Tracks enter/exit calls on the returned tuple `(cm_factory, exit_marker)`
    so tests can assert cleanup ran.
    """
    exit_marker = MagicMock(name="exit_marker")

    @asynccontextmanager
    async def _cm(team_id, workflow_id, skill_id):
        try:
            yield pubsub_mock
        finally:
            exit_marker(team_id, workflow_id, skill_id)

    return _cm, exit_marker


def _patch_subscribe(pubsub_mock):
    """Patch the facade's `subscribe_to_updates` async context manager.

    Returns the patch object plus a sentinel that records cleanup so tests
    can confirm the Redis subscription's `__aexit__` ran.
    """
    cm_factory, exit_marker = _async_subscribe_cm(pubsub_mock)
    return (
        patch(
            "products.wizard.backend.presentation.views.wizard_facade.subscribe_to_updates",
            cm_factory,
        ),
        exit_marker,
    )


def _async_get_message(side_effects):
    return AsyncMock(side_effect=side_effects)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_emits_initial_state_when_session_exists(team):
    await sync_to_async(wizard_facade.upsert)(_input(team.id))

    pubsub_mock = MagicMock()
    pubsub_mock.get_message = _async_get_message([_StopStream()])

    patcher, exit_marker = _patch_subscribe(pubsub_mock)
    with patcher:
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="onboarding", skill_id="nextjs")
        events = await _drain(gen, max_events=2)

    assert len(events) == 1
    assert events[0].startswith(b"data: ")
    assert b'"session_id":"onboarding-nextjs-2026-05-19T10-00-00Z"' in events[0]
    assert events[0].endswith(b"\n\n")
    # Cleanup must run — otherwise we'd leak Redis subscriptions on every
    # client disconnect.
    exit_marker.assert_called_once_with(team.id, "onboarding", "nextjs")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_skips_initial_event_when_no_session(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message = _async_get_message([_StopStream()])

    patcher, exit_marker = _patch_subscribe(pubsub_mock)
    with patcher:
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = await _drain(gen, max_events=2)

    assert events == []
    exit_marker.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_forwards_pubsub_messages(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message = _async_get_message(
        [
            {"type": "message", "data": b'{"session_id":"a"}'},
            {"type": "message", "data": b'{"session_id":"b"}'},
            _StopStream(),
        ]
    )

    patcher, exit_marker = _patch_subscribe(pubsub_mock)
    with patcher:
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = await _drain(gen, max_events=5)

    assert events == [
        b'data: {"session_id":"a"}\n\n',
        b'data: {"session_id":"b"}\n\n',
    ]
    exit_marker.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_emits_heartbeat_when_idle(team):
    pubsub_mock = MagicMock()
    pubsub_mock.get_message = _async_get_message([None, None, _StopStream()])

    patcher, exit_marker = _patch_subscribe(pubsub_mock)
    # Force heartbeat threshold to zero so any idle tick emits one.
    with (
        patcher,
        patch("products.wizard.backend.presentation.views.SSE_HEARTBEAT_INTERVAL_SECONDS", 0.0),
    ):
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = await _drain(gen, max_events=4)

    assert events == [b": ping\n\n", b": ping\n\n"]
    exit_marker.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_terminates_on_max_duration(team):
    """SSE_MAX_DURATION_SECONDS=0 -> first loop tick emits `event: end` and exits."""
    pubsub_mock = MagicMock()
    pubsub_mock.get_message = _async_get_message([None] * 10)

    patcher, exit_marker = _patch_subscribe(pubsub_mock)
    with (
        patcher,
        patch("products.wizard.backend.presentation.views.SSE_MAX_DURATION_SECONDS", 0),
    ):
        gen = _wizard_session_event_stream(team_id=team.id, workflow_id="missing", skill_id="missing")
        events = await _drain(gen, max_events=5)

    # Generator emits `event: end` then returns — clean close, no leaked
    # subscription.
    assert events == [b"event: end\ndata: reconnect\n\n"]
    exit_marker.assert_called_once()
