from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from asgiref.sync import sync_to_async

from posthog.models import Team
from posthog.temporal.ai.live_investigation.schemas import (
    LiveInvestigationBrief,
    StartLiveInvestigationArgs,
)

from products.live_debugger.backend.facade.api import (
    MAX_CHAIN_DEPTH,
    ChainDepthExceeded,
    ParentInvestigationNotFound,
    start_live_investigation,
)
from products.live_debugger.backend.models import LiveDebuggerProgram, LiveInvestigation


def _brief() -> LiveInvestigationBrief:
    return LiveInvestigationBrief(
        hypothesis="Session cache is stale after refresh.",
        what_to_look_for=["session_id non-null but user_id null"],
        instrumentation_rationale="Probe auth.refresh because that's where the cache invalidation happens.",
        signal_summary="Anomaly alert on login_failed spike",
    )


def _args(parent_id: UUID | None = None) -> StartLiveInvestigationArgs:
    return StartLiveInvestigationArgs(
        hogtrace_code="trace auth.refresh() {}",
        brief=_brief(),
        min_events=10,
        max_duration_minutes=60,
        parent_investigation_id=parent_id,
    )


@pytest.mark.django_db(transaction=True)
class TestStartLiveInvestigation:
    @pytest.mark.asyncio
    async def test_creates_program_and_investigation_and_starts_workflow(self, team):
        with patch(
            "products.live_debugger.backend.facade.api.async_connect",
            new_callable=AsyncMock,
        ) as mock_connect:
            mock_client = AsyncMock()
            mock_connect.return_value = mock_client

            investigation_id = await start_live_investigation(
                team=team,
                signal_source_type="anomaly_alert",
                signal_source_id="alert-check-123",
                args=_args(),
            )

        investigation = await LiveInvestigation.objects.select_related("program").aget(id=investigation_id)
        assert investigation.team_id == team.id
        assert investigation.status == LiveInvestigation.Status.WATCHING
        assert investigation.min_events == 10
        assert investigation.max_duration_seconds == 60 * 60
        assert investigation.signal_source_type == "anomaly_alert"
        assert investigation.signal_source_id == "alert-check-123"
        assert investigation.chain_depth == 0
        assert investigation.parent_id is None
        assert investigation.workflow_id.startswith("live-investigation-")
        assert investigation.brief["hypothesis"] == "Session cache is stale after refresh."

        program = investigation.program
        assert program.team_id == team.id
        assert program.code == "trace auth.refresh() {}"
        assert program.status == LiveDebuggerProgram.Status.INSTALLED

        mock_client.start_workflow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chain_depth_incremented_for_child(self, team):
        with patch(
            "products.live_debugger.backend.facade.api.async_connect",
            new_callable=AsyncMock,
        ) as mock_connect:
            mock_connect.return_value = AsyncMock()
            root_id = await start_live_investigation(
                team=team,
                signal_source_type="anomaly_alert",
                signal_source_id="alert-1",
                args=_args(),
            )
            child_id = await start_live_investigation(
                team=team,
                signal_source_type="anomaly_alert",
                signal_source_id="alert-1",
                args=_args(parent_id=UUID(root_id)),
            )

        child = await LiveInvestigation.objects.aget(id=child_id)
        assert child.chain_depth == 1
        assert str(child.parent_id) == root_id

    @pytest.mark.asyncio
    async def test_refuses_child_past_max_chain_depth(self, team):
        with patch(
            "products.live_debugger.backend.facade.api.async_connect",
            new_callable=AsyncMock,
        ) as mock_connect:
            mock_connect.return_value = AsyncMock()
            current_parent: UUID | None = None
            # Spawn up to MAX_CHAIN_DEPTH children (depth 0 → 1 → 2 → 3).
            for _ in range(MAX_CHAIN_DEPTH + 1):
                inv_id = await start_live_investigation(
                    team=team,
                    signal_source_type="anomaly_alert",
                    signal_source_id="alert-1",
                    args=_args(parent_id=current_parent),
                )
                current_parent = UUID(inv_id)

            # The next attempt should hit the cap.
            with pytest.raises(ChainDepthExceeded):
                await start_live_investigation(
                    team=team,
                    signal_source_type="anomaly_alert",
                    signal_source_id="alert-1",
                    args=_args(parent_id=current_parent),
                )

    @pytest.mark.asyncio
    async def test_refuses_parent_from_other_team(self, team):
        other_team = await sync_to_async(_make_other_team, thread_sensitive=False)(team)

        with patch(
            "products.live_debugger.backend.facade.api.async_connect",
            new_callable=AsyncMock,
        ) as mock_connect:
            mock_connect.return_value = AsyncMock()
            parent_id = await start_live_investigation(
                team=other_team,
                signal_source_type="anomaly_alert",
                signal_source_id="alert-1",
                args=_args(),
            )

            with pytest.raises(ParentInvestigationNotFound):
                await start_live_investigation(
                    team=team,
                    signal_source_type="anomaly_alert",
                    signal_source_id="alert-1",
                    args=_args(parent_id=UUID(parent_id)),
                )


def _make_other_team(team) -> Team:
    return Team.objects.create(organization=team.organization, name="Other")
