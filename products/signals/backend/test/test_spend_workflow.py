import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.signals.backend.spend import (
    SignalMetadataChange,
    SignalSpendPublication,
    SignalSpendSummary,
    SignalSpendUpdate,
    submit_signal_metadata_updates,
)
from products.signals.backend.temporal.spend import UpdateSignalSpendWorkflow
from products.signals.backend.temporal.summary import (
    SignalReportSummaryWorkflow,
    check_report_task_settlement_activity,
    publish_report_spend_activity,
)
from products.signals.backend.temporal.types import SignalReportSummaryWorkflowInputs
from products.tasks.backend.facade.agents import MultiTurnSession
from products.tasks.backend.models import Task


@workflow.defn
class SettlingTask:
    def __init__(self) -> None:
        self.completed = False

    @workflow.signal
    def complete_task(self, status: str, error: str | None) -> None:
        self.completed = True

    @workflow.run
    async def run(self, input: SignalSpendUpdate) -> None:
        await workflow.wait_condition(lambda: self.completed)
        await workflow.execute_activity(
            "publish_task_spend",
            input,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@workflow.defn
class ResearchAndSettle:
    @workflow.run
    async def run(self, input: SignalReportSummaryWorkflowInputs) -> str:
        await workflow.execute_activity("research_and_end_session", input, start_to_close_timeout=timedelta(minutes=1))
        await SignalReportSummaryWorkflow()._wait_for_task_settlement(input)
        await workflow.execute_activity(
            publish_report_spend_activity,
            input,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), maximum_attempts=2),
        )
        return "research retained"


@pytest.mark.asyncio
@pytest.mark.parametrize("publication_fails", [False, True])
async def test_spend_updates_retry_and_serialize_updates_arriving_during_and_after_a_write(
    publication_fails: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    queue = f"spend-test-{uuid4()}"
    driver = str(uuid4())
    write_started, release_write = asyncio.Event(), asyncio.Event()
    confirmation_started, release_confirmation = asyncio.Event(), asyncio.Event()
    confirmation_finished = asyncio.Event()
    writes_before_confirmation: list[int] = []
    latest_spend = 1
    stored: list[int] = []
    changes: list[SignalMetadataChange] = []
    attempts = 0
    expected_initial = [2] if publication_fails else [1, 2]

    @activity.defn(name="update_signal_spend_activity")
    async def write_metadata(input: SignalSpendUpdate) -> SignalSpendPublication:
        nonlocal attempts
        assert (input.team_id, input.signal_id) == (1, driver)
        attempts += 1
        if attempts == 1:
            raise ApplicationError("Kafka delivery failed")
        spend = latest_spend
        if attempts == 2:
            write_started.set()
            await release_write.wait()
        if publication_fails:
            raise ApplicationError("Kafka delivery failed permanently", non_retryable=True)
        if confirmation_started.is_set() and not confirmation_finished.is_set():
            writes_before_confirmation.append(spend)
        stored.append(spend)
        changes.extend(input.changes)
        return SignalSpendPublication(
            signal=input, summary=SignalSpendSummary(total_spend=spend, failed_stages=[]), versions={}
        )

    confirmation_attempts = 0

    @activity.defn(name="confirm_signal_spend_activity")
    async def confirm_metadata(input: SignalSpendPublication) -> None:
        nonlocal confirmation_attempts
        confirmation_attempts += 1
        if confirmation_attempts == 1:
            confirmation_started.set()
            await release_confirmation.wait()
            raise ApplicationError("ClickHouse ingestion delayed", type="SignalSpendNotVisible")
        confirmation_finished.set()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[UpdateSignalSpendWorkflow],
            activities=[write_metadata, confirm_metadata],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with (
                override_settings(VIDEO_EXPORT_TASK_QUEUE=queue),
                patch("posthog.temporal.common.client.async_connect", new=AsyncMock(return_value=env.client)),
            ):
                await submit_signal_metadata_updates(team_id=1, signal_ids=[driver])
                await asyncio.wait_for(write_started.wait(), timeout=30)
                handle = env.client.get_workflow_handle(f"signal-spend-1-{driver}")
                latest_spend = 2
                await submit_signal_metadata_updates(team_id=1, signal_ids=[driver])
                release_write.set()
                if publication_fails:
                    with pytest.raises(WorkflowFailureError):
                        await asyncio.wait_for(handle.result(), timeout=30)
                    assert stored == []
                    publication_fails = False
                    await submit_signal_metadata_updates(team_id=1, signal_ids=[driver])
                await asyncio.wait_for(handle.result(), timeout=30)
                assert stored == expected_initial
                assert confirmation_attempts == 0

                latest_spend = 3
                change = SignalMetadataChange(report_id="new-report", expected_report_id="old-report")
                await submit_signal_metadata_updates(team_id=1, signal_ids=[driver], change=change)
                await asyncio.wait_for(confirmation_started.wait(), timeout=30)
                latest_spend = 4
                await submit_signal_metadata_updates(team_id=1, signal_ids=[driver])
                await handle.signal("refresh")
                release_confirmation.set()
                await asyncio.wait_for(handle.result(), timeout=30)
                assert stored[-2:] == [3, 4]
                assert changes == [change]
                assert confirmation_attempts == 2
                assert writes_before_confirmation == []

                latest_spend = 5
                await submit_signal_metadata_updates(team_id=1, signal_ids=[driver])
                await asyncio.wait_for(handle.result(), timeout=30)
                assert stored[-1] == 5
                assert confirmation_attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("publication_fails", [False, True])
async def test_research_releases_shared_slot_before_waiting_for_task_settlement(
    publication_fails: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    queue = f"settlement-test-{uuid4()}"
    task_queue = f"task-test-{uuid4()}"
    task_workflow_id = str(uuid4())
    signal_id = str(uuid4())
    researches = 0
    published = False
    confirmations = 0

    @activity.defn(name="publish_task_spend")
    async def publish_task_spend(input: SignalSpendUpdate) -> None:
        await submit_signal_metadata_updates(team_id=input.team_id, signal_ids=[input.signal_id])

    @activity.defn(name="research_and_end_session")
    async def research_and_end_session(input: SignalReportSummaryWorkflowInputs) -> None:
        nonlocal researches
        researches += 1
        session = MultiTurnSession(
            task=MagicMock(origin_product=Task.OriginProduct.SIGNAL_REPORT),
            task_run=MagicMock(),
            _workflow_handle=env.client.get_workflow_handle(task_workflow_id),
        )
        await session.end()

    @activity.defn(name="update_signal_spend_activity")
    async def write_metadata(input: SignalSpendUpdate) -> SignalSpendPublication:
        nonlocal published
        if publication_fails:
            raise ApplicationError("Kafka unavailable", non_retryable=True)
        published = True
        return SignalSpendPublication(
            signal=input, summary=SignalSpendSummary(total_spend=4, failed_stages=[]), versions={}
        )

    @activity.defn(name="confirm_signal_spend_activity")
    async def confirm_metadata(input: SignalSpendPublication) -> None:
        nonlocal confirmations
        confirmations += 1

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with (
            Worker(
                env.client,
                task_queue=queue,
                workflows=[ResearchAndSettle, UpdateSignalSpendWorkflow],
                activities=[
                    research_and_end_session,
                    check_report_task_settlement_activity,
                    publish_report_spend_activity,
                    write_metadata,
                    confirm_metadata,
                ],
                max_concurrent_activities=1,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ),
            Worker(
                env.client,
                task_queue=task_queue,
                workflows=[SettlingTask],
                activities=[publish_task_spend],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ),
        ):
            with (
                override_settings(VIDEO_EXPORT_TASK_QUEUE=queue),
                patch("posthog.temporal.common.client.async_connect", new=AsyncMock(return_value=env.client)),
                patch(
                    "products.signals.backend.temporal.summary.async_connect", new=AsyncMock(return_value=env.client)
                ),
                patch("products.signals.backend.temporal.summary.SignalSpend") as spend_model,
                patch("products.signals.backend.temporal.summary.finish_report_spend"),
                patch(
                    "products.signals.backend.temporal.summary.get_task_run",
                    return_value=SimpleNamespace(workflow_id=task_workflow_id),
                ),
            ):
                spend_model.objects.for_team.return_value.filter.return_value.values_list.return_value = [uuid4()]
                await env.client.start_workflow(
                    SettlingTask.run,
                    SignalSpendUpdate(team_id=1, signal_id=signal_id),
                    id=task_workflow_id,
                    task_queue=task_queue,
                )
                result = await asyncio.wait_for(
                    env.client.execute_workflow(
                        ResearchAndSettle.run,
                        SignalReportSummaryWorkflowInputs(team_id=1, report_id=str(uuid4()), signal_id=signal_id),
                        id=str(uuid4()),
                        task_queue=queue,
                    ),
                    timeout=30,
                )
                assert result == "research retained"
                assert researches == 1
                handle = env.client.get_workflow_handle(f"signal-spend-1-{signal_id}")
                if publication_fails:
                    with pytest.raises(WorkflowFailureError):
                        await asyncio.wait_for(handle.result(), timeout=30)
                else:
                    await asyncio.wait_for(handle.result(), timeout=30)
                assert published is not publication_fails
                assert confirmations == 0
