import uuid
from datetime import timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSpikeEvent
from products.error_tracking.backend.temporal.spike_event_cleanup.activities import cleanup_spike_events_activity
from products.error_tracking.backend.temporal.spike_event_cleanup.types import (
    SpikeEventCleanupInputs,
    SpikeEventCleanupResult,
)
from products.error_tracking.backend.temporal.spike_event_cleanup.workflow import ErrorTrackingSpikeEventCleanupWorkflow


class TestSpikeEventCleanupActivity(BaseTest):
    def _create_spike_event(self, detected_at_days_ago: int) -> ErrorTrackingSpikeEvent:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        return ErrorTrackingSpikeEvent.objects.create(
            team=self.team,
            issue=issue,
            detected_at=timezone.now() - timedelta(days=detected_at_days_ago),
            computed_baseline=5.0,
            current_bucket_value=100,
        )

    def test_deletes_spike_events_older_than_retention(self) -> None:
        old_spike = self._create_spike_event(detected_at_days_ago=31)
        recent_spike = self._create_spike_event(detected_at_days_ago=5)

        with patch("products.error_tracking.backend.temporal.spike_event_cleanup.activities.close_old_connections"):
            result = cleanup_spike_events_activity(SpikeEventCleanupInputs())

        assert result == SpikeEventCleanupResult(deleted_count=1)
        assert not ErrorTrackingSpikeEvent.objects.filter(id=old_spike.id).exists()
        assert ErrorTrackingSpikeEvent.objects.filter(id=recent_spike.id).exists()

    def test_respects_custom_retention(self) -> None:
        self._create_spike_event(detected_at_days_ago=15)
        self._create_spike_event(detected_at_days_ago=5)

        with patch("products.error_tracking.backend.temporal.spike_event_cleanup.activities.close_old_connections"):
            result = cleanup_spike_events_activity(SpikeEventCleanupInputs(days_old=10))

        assert result == SpikeEventCleanupResult(deleted_count=1)
        assert ErrorTrackingSpikeEvent.objects.count() == 1


async def _run_workflow_with_mock_activity(
    inputs: SpikeEventCleanupInputs | None,
    activity_result: SpikeEventCleanupResult,
) -> tuple[SpikeEventCleanupResult, SpikeEventCleanupInputs]:
    captured: dict[str, SpikeEventCleanupInputs] = {}

    @activity.defn(name="cleanup_spike_events_activity")
    async def mock_activity(activity_inputs: SpikeEventCleanupInputs) -> SpikeEventCleanupResult:
        captured["inputs"] = activity_inputs
        return activity_result

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingSpikeEventCleanupWorkflow],
            activities=[mock_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ErrorTrackingSpikeEventCleanupWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return result, captured["inputs"]


class TestSpikeEventCleanupWorkflow:
    @freeze_time("2026-01-31T00:00:00Z")
    def test_parse_defaults_match_dagster_config(self) -> None:
        assert ErrorTrackingSpikeEventCleanupWorkflow.parse_inputs([]) == SpikeEventCleanupInputs(days_old=30)

    @pytest.mark.asyncio
    async def test_workflow_calls_activity_with_defaults(self) -> None:
        expected = SpikeEventCleanupResult(deleted_count=1)

        result, activity_inputs = await _run_workflow_with_mock_activity(None, expected)

        assert result == expected
        assert activity_inputs == SpikeEventCleanupInputs()

    @pytest.mark.asyncio
    async def test_workflow_forwards_inputs(self) -> None:
        inputs = SpikeEventCleanupInputs(days_old=10)
        expected = SpikeEventCleanupResult(deleted_count=3)

        result, activity_inputs = await _run_workflow_with_mock_activity(inputs, expected)

        assert result == expected
        assert activity_inputs == inputs
