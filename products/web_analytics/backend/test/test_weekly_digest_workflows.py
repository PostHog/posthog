import uuid
import asyncio
import dataclasses

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.web_analytics.backend.temporal.weekly_digest.types import (
    WA_DIGEST_THRESHOLD_EXCEEDED_TYPE,
    DigestBatchInput,
    DigestBatchResult,
    WAWeeklyDigestInput,
)
from products.web_analytics.backend.temporal.weekly_digest.workflows import WAWeeklyDigestWorkflow


def _empty_batch_result(batch_size: int) -> DigestBatchResult:
    return DigestBatchResult(batch_size=batch_size, orgs_processed=batch_size)


@pytest.mark.asyncio
async def test_wa_weekly_digest_skips_batch_fanout_when_no_batches_but_still_pushes_metrics() -> None:
    """An empty discovery result short-circuits the batch fan-out, but we still
    push the (zero-count) metrics so staleness alerts on `last_run_timestamp`
    can detect a worker that quietly stopped finding work to do.
    """

    @activity.defn(name="wa-digest-get-org-batches")
    async def _get_batches(input: WAWeeklyDigestInput) -> list[list[str]]:
        return []

    @activity.defn(name="wa-digest-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        raise AssertionError("should not be called when there are no batches")

    metric_pushes: list[tuple[dict, bool]] = []

    @activity.defn(name="wa-digest-push-metrics")
    async def _push_metrics(totals_dict: dict, success: bool) -> None:
        metric_pushes.append((totals_dict, success))

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WAWeeklyDigestWorkflow],
            activities=[_get_batches, _run_batch, _push_metrics],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WAWeeklyDigestWorkflow.run,
                WAWeeklyDigestInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["orgs"] == 0
    assert result["batches"] == 0
    assert result["emails_sent"] == 0
    assert len(metric_pushes) == 1, "metrics push must happen even on an empty run"
    assert metric_pushes[0][1] is True, "an empty run is still a successful run"


@dataclasses.dataclass
class _ConcurrencyTracker:
    in_flight: int = 0
    max_in_flight: int = 0
    seen_orgs: set[str] = dataclasses.field(default_factory=set)


@pytest.mark.asyncio
@pytest.mark.parametrize("org_count,batch_size,max_concurrent", [(50, 5, 4), (500, 25, 8)])
async def test_wa_weekly_digest_respects_concurrency_cap(org_count: int, batch_size: int, max_concurrent: int) -> None:
    org_ids = [f"org-{i}" for i in range(org_count)]
    expected_batches = [org_ids[i : i + batch_size] for i in range(0, org_count, batch_size)]

    tracker = _ConcurrencyTracker()
    state_lock = asyncio.Lock()

    @activity.defn(name="wa-digest-get-org-batches")
    async def _get_batches(input: WAWeeklyDigestInput) -> list[list[str]]:
        return expected_batches

    @activity.defn(name="wa-digest-run-batch")
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
        return _empty_batch_result(len(input.org_ids))

    metric_pushes: list[tuple[dict, bool]] = []

    @activity.defn(name="wa-digest-push-metrics")
    async def _push_metrics(totals_dict: dict, success: bool) -> None:
        metric_pushes.append((totals_dict, success))

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WAWeeklyDigestWorkflow],
            activities=[_get_batches, _run_batch, _push_metrics],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            max_concurrent_activities=org_count,
        ):
            await env.client.execute_workflow(
                WAWeeklyDigestWorkflow.run,
                WAWeeklyDigestInput(
                    dry_run=True,
                    batch_size=batch_size,
                    max_concurrent=max_concurrent,
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert tracker.seen_orgs == set(org_ids)
    assert tracker.max_in_flight <= max_concurrent, (
        f"workflow scheduled {tracker.max_in_flight} batches concurrently "
        f"but max_concurrent={max_concurrent} — semaphore fan-out guard is missing"
    )
    assert len(metric_pushes) == 1
    assert metric_pushes[0][1] is True


@pytest.mark.asyncio
async def test_wa_weekly_digest_threshold_exceeded_raises_and_pushes_failure_metric() -> None:
    org_ids = [f"org-{i}" for i in range(20)]
    batches = [org_ids]

    @activity.defn(name="wa-digest-get-org-batches")
    async def _get_batches(input: WAWeeklyDigestInput) -> list[list[str]]:
        return batches

    @activity.defn(name="wa-digest-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        # Half the orgs fail — well above the 0.2 default threshold.
        return DigestBatchResult(
            batch_size=len(input.org_ids),
            orgs_processed=len(input.org_ids) // 2,
            orgs_failed=len(input.org_ids) // 2,
        )

    metric_pushes: list[tuple[dict, bool]] = []

    @activity.defn(name="wa-digest-push-metrics")
    async def _push_metrics(totals_dict: dict, success: bool) -> None:
        metric_pushes.append((totals_dict, success))

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WAWeeklyDigestWorkflow],
            activities=[_get_batches, _run_batch, _push_metrics],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(Exception) as exc_info:
                await env.client.execute_workflow(
                    WAWeeklyDigestWorkflow.run,
                    WAWeeklyDigestInput(dry_run=True),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                )

    # Workflow raises ApplicationError(type=WADigestThresholdExceeded). Temporal
    # wraps it in WorkflowFailureError; the cause carries the ApplicationError.
    cause = exc_info.value.__cause__
    assert cause is not None and getattr(cause, "type", None) == WA_DIGEST_THRESHOLD_EXCEEDED_TYPE, (
        f"Expected ApplicationError type={WA_DIGEST_THRESHOLD_EXCEEDED_TYPE}, got {type(cause).__name__}: {cause}"
    )
    assert len(metric_pushes) == 1
    assert metric_pushes[0][1] is False, "metrics push should report success=False when threshold is exceeded"


@pytest.mark.asyncio
async def test_wa_weekly_digest_aggregates_totals_across_batches() -> None:
    batches_input = [["org-a", "org-b"], ["org-c"]]

    @activity.defn(name="wa-digest-get-org-batches")
    async def _get_batches(input: WAWeeklyDigestInput) -> list[list[str]]:
        return batches_input

    @activity.defn(name="wa-digest-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        return DigestBatchResult(
            batch_size=len(input.org_ids),
            orgs_processed=len(input.org_ids),
            emails_sent=len(input.org_ids) * 3,
            emails_skipped_optout=len(input.org_ids),
            build_duration=0.5,
            send_duration=0.25,
        )

    @activity.defn(name="wa-digest-push-metrics")
    async def _push_metrics(totals_dict: dict, success: bool) -> None:
        return None

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WAWeeklyDigestWorkflow],
            activities=[_get_batches, _run_batch, _push_metrics],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WAWeeklyDigestWorkflow.run,
                WAWeeklyDigestInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["orgs"] == 3
    assert result["batches"] == 2
    assert result["emails_sent"] == 9  # (2 + 1) * 3
    assert result["failed_batches"] == 0


@pytest.mark.asyncio
async def test_wa_weekly_digest_does_not_raise_when_only_skipped() -> None:
    # Regression guard: legitimate pre-processing skips (no targeted members,
    # no teams) must not trip the threshold. Only orgs_failed counts.
    org_ids = [f"org-{i}" for i in range(20)]
    batches = [org_ids]

    @activity.defn(name="wa-digest-get-org-batches")
    async def _get_batches(input: WAWeeklyDigestInput) -> list[list[str]]:
        return batches

    @activity.defn(name="wa-digest-run-batch")
    async def _run_batch(input: DigestBatchInput) -> DigestBatchResult:
        return DigestBatchResult(
            batch_size=len(input.org_ids),
            orgs_skipped=len(input.org_ids),
        )

    metric_pushes: list[tuple[dict, bool]] = []

    @activity.defn(name="wa-digest-push-metrics")
    async def _push_metrics(totals_dict: dict, success: bool) -> None:
        metric_pushes.append((totals_dict, success))

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WAWeeklyDigestWorkflow],
            activities=[_get_batches, _run_batch, _push_metrics],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WAWeeklyDigestWorkflow.run,
                WAWeeklyDigestInput(dry_run=True),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result["orgs"] == 20
    assert metric_pushes[0][1] is True, "all-skipped is not a failure — success metric should be True"
