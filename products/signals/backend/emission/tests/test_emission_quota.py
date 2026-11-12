from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models import Organization, Team

from products.signals.backend.emission.conversations_coordinator import (
    EmitConversationsSignalsInputs,
    emit_conversations_signals_activity,
)
from products.signals.backend.emission.emit_signals import EmitSignalsActivityInputs, emit_data_import_signals_activity


@pytest.fixture
def team():
    return Team(id=7, api_token="test-token", organization=Organization())


@pytest.mark.asyncio
async def test_warehouse_defers_billing_admission_to_per_signal_pipeline(team):
    config = MagicMock()
    config.record_fetcher.return_value = []
    module = "products.signals.backend.emission.emit_signals"
    with (
        patch(f"{module}.Heartbeater"),
        patch(f"{module}.activity.in_activity", return_value=True),
        patch(f"{module}.activity.info", return_value=SimpleNamespace(attempt=1)),
        patch(f"{module}.get_signal_config", return_value=config),
        patch(f"{module}._fetch_schema_and_team", AsyncMock(return_value=(MagicMock(), team))),
        patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=True) as gate,
        patch(f"{module}.afetch_source_config", AsyncMock(return_value={})),
        patch(f"{module}.get_data_warehouse_table_name", return_value="github.issues"),
        patch(f"{module}.run_signal_pipeline", AsyncMock(return_value={"status": "success"})) as pipeline,
    ):
        result = await emit_data_import_signals_activity(
            EmitSignalsActivityInputs(
                team_id=team.id,
                schema_id=uuid4(),
                source_id=uuid4(),
                job_id="job-x",
                source_type="GitHub",
                schema_name="issues",
                last_synced_at=None,
            )
        )

    gate.assert_not_called()
    assert result == {"status": "success"}
    config.record_fetcher.assert_called_once()
    pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_conversations_defers_billing_admission_to_per_signal_pipeline(team):
    config = MagicMock()
    config.record_fetcher.return_value = []
    module = "products.signals.backend.emission.conversations_coordinator"
    with (
        patch(f"{module}.Heartbeater"),
        patch(f"{module}.activity.in_activity", return_value=True),
        patch(f"{module}.activity.info", return_value=SimpleNamespace(attempt=1)),
        patch(f"{module}.get_signal_config", return_value=config),
        patch(f"{module}.Team.objects.select_related") as teams,
        patch("products.signals.backend.quota.is_team_signals_quota_limited", return_value=True) as gate,
        patch(f"{module}.afetch_source_config", AsyncMock(return_value={})),
        patch(f"{module}.run_signal_pipeline", AsyncMock(return_value={"status": "success"})) as pipeline,
    ):
        teams.return_value.aget = AsyncMock(return_value=team)
        result = await emit_conversations_signals_activity(EmitConversationsSignalsInputs(team_id=team.id))

    gate.assert_not_called()
    assert result == {"status": "success"}
    config.record_fetcher.assert_called_once()
    pipeline.assert_awaited_once()
