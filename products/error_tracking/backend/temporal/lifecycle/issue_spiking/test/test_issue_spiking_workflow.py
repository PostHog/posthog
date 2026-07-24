import json
import uuid
import dataclasses

import pytest
from posthog.test.base import BaseTest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSpikeEvent
from products.error_tracking.backend.temporal.lifecycle.issue_spiking.activities import (
    persist_issue_spiking_event_activity,
)
from products.error_tracking.backend.temporal.lifecycle.issue_spiking.types import (
    IssueSpikingSnapshot,
    IssueSpikingWorkflowInputs,
    IssueSpikingWorkflowResult,
    SpikeEventPersistenceResult,
)
from products.error_tracking.backend.temporal.lifecycle.issue_spiking.workflow import ErrorTrackingIssueSpikingWorkflow
from products.error_tracking.backend.temporal.lifecycle.types import SpikeEventPersistenceStatus


def _inputs(
    fingerprint: str = "inserted", *, team_id: int = 1, issue_id: str | None = None
) -> IssueSpikingWorkflowInputs:
    return IssueSpikingWorkflowInputs(
        notification_id=str(uuid.uuid4()),
        team_id=team_id,
        issue_id=issue_id or str(uuid.uuid4()),
        issue=IssueSpikingSnapshot(
            name="TypeError",
            description="Something failed",
            status="active",
            created_at="2026-07-21T12:00:00Z",
        ),
        fingerprint=fingerprint,
        event_uuid=str(uuid.uuid4()),
        event_timestamp="2026-07-21T12:00:00Z",
        detected_at="2026-07-21T12:05:00Z",
        computed_baseline=2.0,
        current_bucket_value=20.0,
    )


def test_parse_inputs_accepts_cymbal_issue_spiking_notification() -> None:
    inputs = _inputs()
    payload = {
        **dataclasses.asdict(inputs),
        "type": "issue_spiking",
        "event_properties": {"$exception_list": [{"type": "TypeError", "value": "boom"}]},
    }

    assert ErrorTrackingIssueSpikingWorkflow.parse_inputs([json.dumps(payload)]) == inputs


class TestPersistIssueSpikingEventActivity(BaseTest):
    def test_is_idempotent_and_ignores_missing_issues(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        inputs = _inputs(team_id=self.team.id, issue_id=str(issue.id))

        inserted = persist_issue_spiking_event_activity(inputs)
        existing = persist_issue_spiking_event_activity(inputs)
        missing = persist_issue_spiking_event_activity(
            dataclasses.replace(inputs, notification_id=str(uuid.uuid4()), issue_id=str(uuid.uuid4()))
        )

        assert inserted == SpikeEventPersistenceResult(status=SpikeEventPersistenceStatus.INSERTED)
        assert existing == SpikeEventPersistenceResult(status=SpikeEventPersistenceStatus.ALREADY_PERSISTED)
        assert missing == SpikeEventPersistenceResult(status=SpikeEventPersistenceStatus.MISSING_ISSUE)
        assert ErrorTrackingSpikeEvent.objects.filter(id=inputs.notification_id, team=self.team).exists()


@pytest.mark.asyncio
async def test_notifies_after_idempotent_persistence_and_ignores_missing_issues() -> None:
    emitted_events: list[str] = []
    emitted_signals: list[str] = []

    @activity.defn(name="persist_issue_spiking_event_activity")
    async def persist(inputs: IssueSpikingWorkflowInputs) -> SpikeEventPersistenceResult:
        status = {
            "inserted": SpikeEventPersistenceStatus.INSERTED,
            "existing": SpikeEventPersistenceStatus.ALREADY_PERSISTED,
            "missing": SpikeEventPersistenceStatus.MISSING_ISSUE,
        }[inputs.fingerprint]
        return SpikeEventPersistenceResult(status=status)

    @activity.defn(name="emit_issue_spiking_internal_event_activity")
    async def emit_event(inputs: IssueSpikingWorkflowInputs) -> None:
        emitted_events.append(inputs.issue_id)

    @activity.defn(name="emit_issue_spiking_signal_activity")
    async def emit_signal(inputs: IssueSpikingWorkflowInputs) -> None:
        emitted_signals.append(inputs.issue_id)

    task_queue = str(uuid.uuid4())
    inputs_by_status = {status: _inputs(status) for status in ("inserted", "existing", "missing")}
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingIssueSpikingWorkflow],
            activities=[persist, emit_event, emit_signal],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            results = {
                status: await environment.client.execute_workflow(
                    ErrorTrackingIssueSpikingWorkflow.run,
                    inputs,
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )
                for status, inputs in inputs_by_status.items()
            }

    assert results == {
        "inserted": IssueSpikingWorkflowResult(persisted=True, notified=True),
        "existing": IssueSpikingWorkflowResult(persisted=True, notified=True),
        "missing": IssueSpikingWorkflowResult(),
    }
    assert emitted_events == [inputs_by_status["inserted"].issue_id, inputs_by_status["existing"].issue_id]
    assert emitted_signals == [inputs_by_status["inserted"].issue_id, inputs_by_status["existing"].issue_id]
