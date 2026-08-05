import uuid
import asyncio
import dataclasses

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.web_analytics.backend.temporal.digest_notification.types import (
    WA_DIGEST_NOTIF_THRESHOLD_EXCEEDED_TYPE,
    DigestBatchInput,
    DigestBatchResult,
    OrgBatchPageInput,
    OrgBatchPageResult,
    WADigestNotificationInput,
)
from products.web_analytics.backend.temporal.digest_notification.workflows import WADigestNotificationWorkflow


def _batch_page(batches: list[list[str]], cursor: str | None = None) -> OrgBatchPageResult:
    return OrgBatchPageResult(batches=batches, cursor=cursor)


@pytest.mark.asyncio
async def test_no_batches_returns_zeroed_summary() -> None:
    @activity.defn(name="wa-digest-notif-get-org-batch-page")
    async def _get_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
        return _batch_page([])

    @activity.defn(name="wa-digest-notif-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        raise AssertionError("should not be called when there are no batches")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WADigestNotificationWorkflow],
            activities=[_get_batch_page, _run_batch],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WADigestNotificationWorkflow.run,
                WADigestNotificationInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["orgs"] == 0
    assert result["batches"] == 0
    assert result["notifications_sent"] == 0
    assert result["control_exposed"] == 0
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_aggregates_totals_across_batches() -> None:
    batches_input = [["org-a", "org-b"], ["org-c"]]

    @activity.defn(name="wa-digest-notif-get-org-batch-page")
    async def _get_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
        return _batch_page(batches_input)

    @activity.defn(name="wa-digest-notif-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        return DigestBatchResult(
            batch_size=len(input.org_ids),
            orgs_processed=len(input.org_ids),
            notifications_sent=len(input.org_ids) * 2,
            control_exposed=len(input.org_ids),
            failed=0,
            build_duration=0.5,
            send_duration=0.25,
        )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WADigestNotificationWorkflow],
            activities=[_get_batch_page, _run_batch],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WADigestNotificationWorkflow.run,
                WADigestNotificationInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["orgs"] == 3
    assert result["batches"] == 2
    assert result["notifications_sent"] == 6  # (2 + 1) * 2
    assert result["control_exposed"] == 3
    assert result["failed_batches"] == 0


@pytest.mark.asyncio
async def test_processes_multiple_discovery_pages() -> None:
    pages_by_cursor = {
        None: _batch_page([["org-a", "org-b"], ["org-c"]], cursor="page-2"),
        "page-2": _batch_page([["org-d"], ["org-e", "org-f"]]),
    }
    seen_cursors: list[str | None] = []
    seen_orgs: set[str] = set()

    @activity.defn(name="wa-digest-notif-get-org-batch-page")
    async def _get_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
        seen_cursors.append(input.cursor)
        return pages_by_cursor[input.cursor]

    @activity.defn(name="wa-digest-notif-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        seen_orgs.update(input.org_ids)
        return DigestBatchResult(
            batch_size=len(input.org_ids),
            orgs_processed=len(input.org_ids),
            notifications_sent=len(input.org_ids),
        )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WADigestNotificationWorkflow],
            activities=[_get_batch_page, _run_batch],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WADigestNotificationWorkflow.run,
                WADigestNotificationInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert seen_cursors == [None, "page-2"]
    assert seen_orgs == {"org-a", "org-b", "org-c", "org-d", "org-e", "org-f"}
    assert result["orgs"] == 6
    assert result["batches"] == 4
    assert result["notifications_sent"] == 6


@dataclasses.dataclass
class _ConcurrencyTracker:
    in_flight: int = 0
    max_in_flight: int = 0
    seen_orgs: set[str] = dataclasses.field(default_factory=set)


@pytest.mark.asyncio
@pytest.mark.parametrize("org_count,batch_size,max_concurrent", [(50, 5, 4)])
async def test_respects_concurrency_cap(org_count: int, batch_size: int, max_concurrent: int) -> None:
    org_ids = [f"org-{i}" for i in range(org_count)]
    expected_batches = [org_ids[i : i + batch_size] for i in range(0, org_count, batch_size)]

    tracker = _ConcurrencyTracker()
    state_lock = asyncio.Lock()

    @activity.defn(name="wa-digest-notif-get-org-batch-page")
    async def _get_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
        return _batch_page(expected_batches)

    @activity.defn(name="wa-digest-notif-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        async with state_lock:
            tracker.in_flight += 1
            tracker.max_in_flight = max(tracker.max_in_flight, tracker.in_flight)
            tracker.seen_orgs.update(input.org_ids)
        try:
            await asyncio.sleep(0.01)
        finally:
            async with state_lock:
                tracker.in_flight -= 1
        return DigestBatchResult(batch_size=len(input.org_ids), orgs_processed=len(input.org_ids))

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WADigestNotificationWorkflow],
            activities=[_get_batch_page, _run_batch],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            max_concurrent_activities=org_count,
        ):
            await env.client.execute_workflow(
                WADigestNotificationWorkflow.run,
                WADigestNotificationInput(dry_run=True, batch_size=batch_size, max_concurrent=max_concurrent),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert tracker.seen_orgs == set(org_ids)
    assert tracker.max_in_flight <= max_concurrent, (
        f"workflow scheduled {tracker.max_in_flight} batches concurrently "
        f"but max_concurrent={max_concurrent} — semaphore fan-out guard is missing"
    )


@pytest.mark.asyncio
async def test_isolates_failing_batch() -> None:
    batches_input = [["org-a", "org-b"], ["org-c"]]

    @activity.defn(name="wa-digest-notif-get-org-batch-page")
    async def _get_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
        return _batch_page(batches_input)

    @activity.defn(name="wa-digest-notif-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        if "org-c" in input.org_ids:
            raise RuntimeError("batch blew up")
        return DigestBatchResult(
            batch_size=len(input.org_ids),
            orgs_processed=len(input.org_ids),
            notifications_sent=len(input.org_ids),
        )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WADigestNotificationWorkflow],
            activities=[_get_batch_page, _run_batch],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WADigestNotificationWorkflow.run,
                WADigestNotificationInput(dry_run=True, failure_threshold=0.5),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["failed_batches"] == 1
    assert result["notifications_sent"] == 2


@pytest.mark.asyncio
async def test_does_not_raise_when_only_skipped() -> None:
    org_ids = [f"org-{i}" for i in range(20)]
    batches = [org_ids]

    @activity.defn(name="wa-digest-notif-get-org-batch-page")
    async def _get_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
        return _batch_page(batches)

    @activity.defn(name="wa-digest-notif-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        return DigestBatchResult(batch_size=len(input.org_ids), orgs_skipped=len(input.org_ids))

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WADigestNotificationWorkflow],
            activities=[_get_batch_page, _run_batch],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WADigestNotificationWorkflow.run,
                WADigestNotificationInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["orgs"] == 20
    assert result["notifications_sent"] == 0


@pytest.mark.asyncio
async def test_threshold_exceeded_raises_application_error() -> None:
    org_ids = [f"org-{i}" for i in range(20)]
    batches = [org_ids]

    @activity.defn(name="wa-digest-notif-get-org-batch-page")
    async def _get_batch_page(input: OrgBatchPageInput) -> OrgBatchPageResult:
        return _batch_page(batches)

    @activity.defn(name="wa-digest-notif-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        return DigestBatchResult(
            batch_size=len(input.org_ids),
            orgs_processed=len(input.org_ids) // 2,
            orgs_failed=len(input.org_ids) // 2,
        )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WADigestNotificationWorkflow],
            activities=[_get_batch_page, _run_batch],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(Exception) as exc_info:
                await env.client.execute_workflow(
                    WADigestNotificationWorkflow.run,
                    WADigestNotificationInput(dry_run=True),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

    cause = exc_info.value.__cause__
    assert cause is not None and getattr(cause, "type", None) == WA_DIGEST_NOTIF_THRESHOLD_EXCEEDED_TYPE, (
        f"Expected ApplicationError type={WA_DIGEST_NOTIF_THRESHOLD_EXCEEDED_TYPE}, got {type(cause).__name__}: {cause}"
    )
