from datetime import timedelta

import pytest
from unittest import mock

from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

from posthog.temporal.logs_alerting.schedule import create_logs_alert_check_schedule


@pytest.mark.asyncio
async def test_logs_alert_schedule_has_bounded_inputs_and_explicit_recovery_policy() -> None:
    captured = []
    with (
        mock.patch("posthog.temporal.logs_alerting.schedule.settings.CLOUD_DEPLOYMENT", "EU"),
        mock.patch("posthog.temporal.logs_alerting.schedule.a_schedule_exists", new=mock.AsyncMock(return_value=False)),
        mock.patch(
            "posthog.temporal.logs_alerting.schedule.a_create_schedule",
            new=mock.AsyncMock(side_effect=lambda client, schedule_id, schedule, **kwargs: captured.append(schedule)),
        ),
    ):
        await create_logs_alert_check_schedule(mock.MagicMock())

    schedule = captured[0]
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.args == [{"max_alerts_per_run": 300, "region": "eu"}]
    assert schedule.action.execution_timeout == timedelta(minutes=10)
    assert schedule.action.retry_policy is not None
    assert schedule.action.retry_policy.maximum_attempts == 1
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == timedelta(minutes=1)
    assert schedule.policy.pause_on_failure is False
