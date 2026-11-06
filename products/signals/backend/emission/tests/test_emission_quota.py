from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models import Organization, Team

from products.signals.backend.emission.conversations_coordinator import (
    EmitConversationsSignalsInputs,
    emit_conversations_signals_activity,
)
from products.signals.backend.emission.emit_signals import EmitSignalsActivityInputs, emit_data_import_signals_activity

from ee.billing.quota_limiting import QuotaResource


@pytest.fixture(params=["legacy_limited", "spend_limited", "spend_allowed"])
def quota_case(request):
    spend_billing = request.param.startswith("spend")
    team = Team(
        id=7,
        api_token="test-token",
        organization=Organization(
            usage={"signals_spend_credits": {"billing_start_date": "2000-01-01"}} if spend_billing else {}
        ),
    )
    resource = QuotaResource.SIGNALS_SPEND_CREDITS if spend_billing else QuotaResource.SIGNALS_CREDITS
    return team, resource, request.param.endswith("limited")


@pytest.mark.asyncio
async def test_warehouse_checks_quota_before_consuming_records(quota_case):
    team, resource, limited = quota_case
    config = MagicMock()
    config.record_fetcher.return_value = []
    module = "products.signals.backend.emission.emit_signals"
    with (
        patch(f"{module}.Heartbeater"),
        patch(f"{module}.get_signal_config", return_value=config),
        patch(f"{module}._fetch_schema_and_team", AsyncMock(return_value=(MagicMock(), team))),
        patch(f"{module}.is_team_signals_quota_limited", return_value=limited) as gate,
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

    gate.assert_called_once_with(team.api_token, resource)
    if limited:
        assert result == {"status": "skipped", "reason": "quota_limited", "signals_emitted": 0}
        config.record_fetcher.assert_not_called()
        pipeline.assert_not_awaited()
    else:
        assert result == {"status": "success"}
        config.record_fetcher.assert_called_once()
        pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_conversations_checks_quota_before_consuming_records(quota_case):
    team, resource, limited = quota_case
    config = MagicMock()
    config.record_fetcher.return_value = []
    module = "products.signals.backend.emission.conversations_coordinator"
    with (
        patch(f"{module}.Heartbeater"),
        patch(f"{module}.get_signal_config", return_value=config),
        patch(f"{module}.Team.objects.select_related") as teams,
        patch(f"{module}.is_team_signals_quota_limited", return_value=limited) as gate,
        patch(f"{module}.afetch_source_config", AsyncMock(return_value={})),
        patch(f"{module}.run_signal_pipeline", AsyncMock(return_value={"status": "success"})) as pipeline,
    ):
        teams.return_value.aget = AsyncMock(return_value=team)
        result = await emit_conversations_signals_activity(EmitConversationsSignalsInputs(team_id=team.id))

    gate.assert_called_once_with(team.api_token, resource)
    if limited:
        assert result == {"status": "skipped", "reason": "quota_limited", "signals_emitted": 0}
        config.record_fetcher.assert_not_called()
        pipeline.assert_not_awaited()
    else:
        assert result == {"status": "success"}
        config.record_fetcher.assert_called_once()
        pipeline.assert_awaited_once()
