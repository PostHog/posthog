from datetime import timedelta

import pytest
from unittest import mock

from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

from posthog.temporal.logs_alerting.schedule import create_logs_alert_check_schedule


@pytest.mark.asyncio
async def test_logs_alert_schedule_bounds_each_run_and_limits_catchup() -> None:
    captured = []
    with (
        mock.patch("posthog.temporal.logs_alerting.schedule.a_schedule_exists", new=mock.AsyncMock(return_value=False)),
        mock.patch(
            "posthog.temporal.logs_alerting.schedule.a_create_schedule",
            new=mock.AsyncMock(side_effect=lambda client, schedule_id, schedule, **kwargs: captured.append(schedule)),
        ),
    ):
        await create_logs_alert_check_schedule(mock.MagicMock())

    schedule = captured[0]
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.args == [{"max_alerts_per_run": 300, "max_concurrent_batches": 5}]
    assert schedule.action.execution_timeout == timedelta(minutes=10)
    assert schedule.policy.overlap is ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == timedelta(minutes=1)
