from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from products.live_debugger.backend.models import LiveDebuggerProgram
from products.live_debugger.backend.temporal.activities import (
    InstallProgramInput,
    PollProgramEventsInput,
    UninstallProgramInput,
    install_program_activity,
    poll_program_events_activity,
    uninstall_program_activity,
)


def _make_heartbeater():
    """Return a no-op async context manager to replace Heartbeater in tests."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=cm)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.django_db(transaction=True)
class TestInstallProgramActivity:
    @pytest.mark.asyncio
    async def test_creates_program_and_returns_id(self, team):
        program_id = await install_program_activity(
            InstallProgramInput(
                team_id=team.id,
                code="trace foo() {}",
                description="Test program",
            )
        )

        program = await LiveDebuggerProgram.objects.aget(id=program_id)
        assert program.team_id == team.id
        assert program.code == "trace foo() {}"
        assert program.description == "Test program"
        assert program.status == LiveDebuggerProgram.Status.INSTALLED

    @pytest.mark.asyncio
    async def test_returns_string_id(self, team):
        program_id = await install_program_activity(
            InstallProgramInput(team_id=team.id, code="x", description="")
        )
        assert isinstance(program_id, str)

    @pytest.mark.asyncio
    async def test_default_status_is_installed(self, team):
        program_id = await install_program_activity(
            InstallProgramInput(team_id=team.id, code="x", description="")
        )
        program = await LiveDebuggerProgram.objects.aget(id=program_id)
        assert program.status == LiveDebuggerProgram.Status.INSTALLED


@pytest.mark.django_db(transaction=True)
class TestPollProgramEventsActivity:
    def _make_events(self, n: int) -> list[dict]:
        return [
            {
                "id": f"evt-{i}",
                "timestamp": "2026-01-01T00:00:00",
                "program_id": "prog-1",
                "probe_id": None,
                "line_number": 10,
                "filename": "foo.py",
                "function_name": "bar",
                "locals": {},
                "stack_trace": [],
            }
            for i in range(n)
        ]

    @pytest.mark.asyncio
    async def test_returns_when_min_events_reached(self, team):
        program = await LiveDebuggerProgram.objects.acreate(
            team=team, code="x", description=""
        )
        events = self._make_events(5)

        mock_event_objects = []
        for e in events:
            m = MagicMock()
            m.to_json.return_value = e
            mock_event_objects.append(m)

        with (
            patch(
                "products.live_debugger.backend.temporal.activities.Heartbeater",
                return_value=_make_heartbeater(),
            ),
            patch(
                "products.live_debugger.backend.models.LiveDebuggerProgram.get_program_events",
                return_value=mock_event_objects,
            ),
        ):
            result = await poll_program_events_activity(
                PollProgramEventsInput(
                    team_id=team.id,
                    program_id=str(program.id),
                    min_events=5,
                    max_duration_seconds=300,
                    poll_interval_seconds=0,
                )
            )

        assert result.timed_out is False
        assert result.event_count == 5
        assert len(result.events) == 5

    @pytest.mark.asyncio
    async def test_returns_timed_out_when_duration_exceeded(self, team):
        program = await LiveDebuggerProgram.objects.acreate(
            team=team, code="x", description=""
        )
        events = self._make_events(2)
        mock_event_objects = [MagicMock(to_json=MagicMock(return_value=e)) for e in events]

        with (
            patch(
                "products.live_debugger.backend.temporal.activities.Heartbeater",
                return_value=_make_heartbeater(),
            ),
            patch(
                "products.live_debugger.backend.models.LiveDebuggerProgram.get_program_events",
                return_value=mock_event_objects,
            ),
        ):
            result = await poll_program_events_activity(
                PollProgramEventsInput(
                    team_id=team.id,
                    program_id=str(program.id),
                    min_events=100,
                    max_duration_seconds=0,  # immediate timeout
                    poll_interval_seconds=0,
                )
            )

        assert result.timed_out is True
        assert result.event_count == 2

    @pytest.mark.asyncio
    async def test_polls_multiple_times_until_enough_events(self, team):
        program = await LiveDebuggerProgram.objects.acreate(
            team=team, code="x", description=""
        )
        # First two calls return 2 events, third returns 5 (enough)
        few = [MagicMock(to_json=MagicMock(return_value={})) for _ in range(2)]
        enough = [MagicMock(to_json=MagicMock(return_value={})) for _ in range(5)]

        with (
            patch(
                "products.live_debugger.backend.temporal.activities.Heartbeater",
                return_value=_make_heartbeater(),
            ),
            patch(
                "products.live_debugger.backend.models.LiveDebuggerProgram.get_program_events",
                side_effect=[few, few, enough],
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await poll_program_events_activity(
                PollProgramEventsInput(
                    team_id=team.id,
                    program_id=str(program.id),
                    min_events=5,
                    max_duration_seconds=300,
                    poll_interval_seconds=1,
                )
            )

        assert result.timed_out is False
        assert result.event_count == 5


@pytest.mark.django_db(transaction=True)
class TestUninstallProgramActivity:
    @pytest.mark.asyncio
    async def test_sets_status_to_uninstalled(self, team):
        program = await LiveDebuggerProgram.objects.acreate(
            team=team, code="x", description=""
        )
        assert program.status == LiveDebuggerProgram.Status.INSTALLED

        await uninstall_program_activity(
            UninstallProgramInput(team_id=team.id, program_id=str(program.id))
        )

        await program.arefresh_from_db()
        assert program.status == LiveDebuggerProgram.Status.UNINSTALLED

    @pytest.mark.asyncio
    async def test_is_idempotent(self, team):
        program = await LiveDebuggerProgram.objects.acreate(
            team=team,
            code="x",
            description="",
            status=LiveDebuggerProgram.Status.UNINSTALLED,
        )

        # Should not raise
        await uninstall_program_activity(
            UninstallProgramInput(team_id=team.id, program_id=str(program.id))
        )

        await program.arefresh_from_db()
        assert program.status == LiveDebuggerProgram.Status.UNINSTALLED

    @pytest.mark.asyncio
    async def test_does_not_affect_other_teams_program(self, team, organization):
        other_team = await organization.teams.acreate(name="Other")
        program = await LiveDebuggerProgram.objects.acreate(
            team=other_team, code="x", description=""
        )

        # Uninstall with wrong team_id — should be a no-op
        await uninstall_program_activity(
            UninstallProgramInput(team_id=team.id, program_id=str(program.id))
        )

        await program.arefresh_from_db()
        assert program.status == LiveDebuggerProgram.Status.INSTALLED
