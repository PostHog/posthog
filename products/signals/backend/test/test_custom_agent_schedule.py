from __future__ import annotations

import random

import pytest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.client import Schedule, ScheduleAlreadyRunningError, ScheduleRange, ScheduleUpdateInput
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team

from products.signals.backend.custom_agent import AgentScheduleSpec, CustomSignalAgent, ScheduleAgentResult
from products.signals.backend.custom_agent.schemas import AgentScheduleError
from products.signals.backend.temporal import custom_agent as wrapper
from products.signals.backend.temporal.custom_agent import (
    _calendar_spec,
    _schedule_id_for,
    aschedule_agent,
    aunschedule_agent,
)


class _ScheduleTestAgent(CustomSignalAgent):
    @classmethod
    def identifier(cls) -> tuple[str, str]:
        return ("signals", "schedule_test")

    async def run(self) -> bool:
        return False


# ── In-memory fake Temporal client ───────────────────────────────────────────────
#
# The schedule launchers only talk to the Temporal client + the schedule helpers in
# posthog/temporal/common/schedule.py. We back those helpers with a dict so the real
# helper wiring (create/update/delete/describe) is exercised without a server.


class _FakeScheduleHandle:
    def __init__(self, store: dict[str, Schedule], schedule_id: str) -> None:
        self._store = store
        self._schedule_id = schedule_id

    async def describe(self):
        if self._schedule_id not in self._store:
            raise RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
        return type("Desc", (), {"schedule": self._store[self._schedule_id]})()

    async def update(self, *, updater):
        update = await updater(ScheduleUpdateInput(description=None))  # type: ignore[arg-type]
        self._store[self._schedule_id] = update.schedule

    async def delete(self) -> None:
        if self._schedule_id not in self._store:
            raise RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
        del self._store[self._schedule_id]


class _FakeClient:
    def __init__(self, store: dict[str, Schedule]) -> None:
        self._store = store

    def get_schedule_handle(self, schedule_id: str) -> _FakeScheduleHandle:
        return _FakeScheduleHandle(self._store, schedule_id)

    async def create_schedule(self, *, id, schedule, trigger_immediately=False, search_attributes=None):
        self._store[id] = schedule
        return self.get_schedule_handle(id)


@pytest_asyncio.fixture
async def fake_temporal():
    store: dict[str, Schedule] = {}
    with patch.object(wrapper, "async_connect", return_value=_FakeClient(store)):
        yield store


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"CustomAgentScheduleOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"CustomAgentScheduleTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


# ── AgentScheduleSpec validation (pure) ──────────────────────────────────────────


def test_agent_schedule_spec_requires_a_calendar_field():
    with pytest.raises(AgentScheduleError):
        AgentScheduleSpec()
    with pytest.raises(AgentScheduleError):
        AgentScheduleSpec(timezone="UTC")  # timezone alone isn't a calendar field
    with pytest.raises(AgentScheduleError):
        AgentScheduleSpec(hour=[])  # empty list is not a "set" field (would match every value)
    with pytest.raises(AgentScheduleError):
        AgentScheduleSpec(hour=[], minute=[])  # all-empty is still empty


@pytest.mark.parametrize(
    "kwargs",
    [
        {"minute": 60},
        {"hour": 24},
        {"hour": -1},
        {"day_of_month": 0},
        {"day_of_month": 32},
        {"month": 13},
        {"day_of_week": 7},
        {"hour": [0, 23, 24]},
    ],
)
def test_agent_schedule_spec_rejects_out_of_range(kwargs):
    with pytest.raises(AgentScheduleError):
        AgentScheduleSpec(**kwargs)


def test_agent_schedule_spec_rejects_blank_timezone():
    with pytest.raises(AgentScheduleError):
        AgentScheduleSpec(hour=9, timezone="  ")


@pytest.mark.parametrize("tz", ["PST", "Europe/Atlantis", "utc/typo", "Not A Zone"])
def test_agent_schedule_spec_rejects_invalid_timezone(tz):
    with pytest.raises(AgentScheduleError):
        AgentScheduleSpec(hour=9, timezone=tz)


def test_agent_schedule_spec_values_for_canonicalizes():
    # int, single-element list, duplicates, and unsorted lists all collapse to the same
    # canonical (sorted, de-duplicated) value list.
    assert AgentScheduleSpec(hour=9).values_for("hour") == [9]
    assert AgentScheduleSpec(hour=[9]).values_for("hour") == [9]
    assert AgentScheduleSpec(hour=[9, 9]).values_for("hour") == [9]
    assert AgentScheduleSpec(day_of_week=[5, 3, 1]).values_for("day_of_week") == [1, 3, 5]
    assert AgentScheduleSpec(hour=9).values_for("minute") == []


# ── _calendar_spec mapping ───────────────────────────────────────────────────────


def test_calendar_spec_maps_set_fields_only():
    spec = AgentScheduleSpec(hour=9, minute=0, day_of_week=[1, 5], timezone="US/Pacific")
    calendar = _calendar_spec(spec)

    assert list(calendar.hour) == [ScheduleRange(start=9, end=9)]
    assert list(calendar.minute) == [ScheduleRange(start=0, end=0)]
    assert list(calendar.day_of_week) == [ScheduleRange(start=1, end=1), ScheduleRange(start=5, end=5)]


# ── schedule id format ───────────────────────────────────────────────────────────


def test_schedule_id_format():
    assert _schedule_id_for(_ScheduleTestAgent, 42) == "signals-custom-agent:42:signals:schedule_test"


# ── aschedule_agent / aunschedule_agent ──────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_schedule_agent_creates_then_is_idempotent(ateam, fake_temporal):
    spec = AgentScheduleSpec(hour=9, minute=0, timezone="UTC")

    result = await aschedule_agent(_ScheduleTestAgent, ateam, "do the thing", spec, paused=True)
    assert result is ScheduleAgentResult.CREATED

    schedule_id = _schedule_id_for(_ScheduleTestAgent, ateam.id)
    assert schedule_id in fake_temporal
    created = fake_temporal[schedule_id]

    # The action starts the shared workflow with a scheduled input.
    workflow_input = created.action.args[0]
    assert workflow_input.scheduled is True
    assert workflow_input.run_id == "scheduled"
    assert workflow_input.initial_prompt == "do the thing"
    assert workflow_input.product == "signals"
    assert workflow_input.type == "schedule_test"
    assert created.state.paused is True
    assert created.spec.time_zone_name == "UTC"
    assert list(created.spec.calendars[0].hour) == [ScheduleRange(start=9, end=9)]

    # Identical re-invocation is a no-op.
    again = await aschedule_agent(_ScheduleTestAgent, ateam, "do the thing", spec, paused=True)
    assert again is ScheduleAgentResult.ALREADY_PRESENT


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_schedule_agent_updates_on_changed_argument(ateam, fake_temporal):
    spec = AgentScheduleSpec(hour=9, timezone="UTC")
    assert await aschedule_agent(_ScheduleTestAgent, ateam, "first", spec) is ScheduleAgentResult.CREATED

    # Changed prompt → UPDATED, and the stored input reflects it.
    assert await aschedule_agent(_ScheduleTestAgent, ateam, "second", spec) is ScheduleAgentResult.UPDATED
    stored = fake_temporal[_schedule_id_for(_ScheduleTestAgent, ateam.id)]
    assert stored.action.args[0].initial_prompt == "second"

    # Changed schedule → UPDATED.
    new_spec = AgentScheduleSpec(hour=10, timezone="UTC")
    assert await aschedule_agent(_ScheduleTestAgent, ateam, "second", new_spec) is ScheduleAgentResult.UPDATED
    stored = fake_temporal[_schedule_id_for(_ScheduleTestAgent, ateam.id)]
    assert list(stored.spec.calendars[0].hour) == [ScheduleRange(start=10, end=10)]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_unschedule_agent_returns_whether_present(ateam, fake_temporal):
    # Nothing scheduled yet.
    assert await aunschedule_agent(_ScheduleTestAgent, ateam) is False

    await aschedule_agent(_ScheduleTestAgent, ateam, "x", AgentScheduleSpec(hour=1, timezone="UTC"))
    assert await aunschedule_agent(_ScheduleTestAgent, ateam) is True
    assert _schedule_id_for(_ScheduleTestAgent, ateam.id) not in fake_temporal
    # Deleting again reports absence.
    assert await aunschedule_agent(_ScheduleTestAgent, ateam) is False


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_schedule_agent_equivalent_calendar_is_already_present(ateam, fake_temporal):
    # int vs single-element list, and reordered/duplicate lists, are the same schedule.
    assert (
        await aschedule_agent(_ScheduleTestAgent, ateam, "x", AgentScheduleSpec(hour=9, day_of_week=[1, 5]))
        is ScheduleAgentResult.CREATED
    )
    assert (
        await aschedule_agent(_ScheduleTestAgent, ateam, "x", AgentScheduleSpec(hour=[9], day_of_week=[5, 1, 5]))
        is ScheduleAgentResult.ALREADY_PRESENT
    )


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_schedule_agent_handles_creation_race(ateam, fake_temporal):
    # Simulate losing a creation race: describe sees nothing, but create raises
    # ScheduleAlreadyRunningError (a concurrent caller won and stored an identical
    # schedule). The call must fall through to compare-and-return, not blow up.
    spec = AgentScheduleSpec(hour=9, timezone="UTC")
    schedule_id = _schedule_id_for(_ScheduleTestAgent, ateam.id)

    real_a_create = wrapper.a_create_schedule

    async def racing_create(client, sid, schedule):
        # The "winner" stored the schedule; we then raise as the loser.
        await real_a_create(client, sid, schedule)
        raise ScheduleAlreadyRunningError()

    with patch.object(wrapper, "a_create_schedule", side_effect=racing_create):
        result = await aschedule_agent(_ScheduleTestAgent, ateam, "x", spec)

    # The winner stored an identical config, so the loser resolves to ALREADY_PRESENT.
    assert result is ScheduleAgentResult.ALREADY_PRESENT
    assert schedule_id in fake_temporal


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_schedule_agent_refuses_without_ai_consent(fake_temporal):
    org = await sync_to_async(Organization.objects.create)(
        name=f"NoConsentOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=False,
    )
    team = await sync_to_async(Team.objects.create)(organization=org, name="no-consent")
    try:
        with pytest.raises(wrapper.AIDataProcessingNotApprovedError):
            await aschedule_agent(_ScheduleTestAgent, team, "x", AgentScheduleSpec(hour=1, timezone="UTC"))
        assert fake_temporal == {}
    finally:
        await sync_to_async(team.delete)()
        await sync_to_async(org.delete)()
