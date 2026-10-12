import uuid
import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.review_hog.backend.temporal.scheduling import ReviewPRQueueWorkflow, ReviewRequestQueue
from products.review_hog.backend.temporal.types import ReviewPRQueueInputs, ReviewPRWorkflowInputs


@workflow.defn(name="review-pr")
class ScheduledReviewStub:
    @workflow.run
    async def run(self, inputs: ReviewPRWorkflowInputs) -> str:
        return await workflow.execute_activity(
            "record_scheduled_review",
            inputs,
            result_type=str,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_first", [False, True])
async def test_pushes_coalesce_and_full_requests_survive_an_active_flash_review(fail_first: bool) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    reviews: list[ReviewPRWorkflowInputs] = []
    first = ReviewPRWorkflowInputs(
        team_id=1,
        user_id=1,
        owner="PostHog",
        repo="posthog",
        pr_number=7,
        review_mode="flash",
        trigger_source="automatic",
        requested_head_sha="a",
        publish=True,
    )

    @activity.defn(name="record_scheduled_review")
    async def record(inputs: ReviewPRWorkflowInputs) -> str:
        reviews.append(inputs)
        if inputs.requested_head_sha == "a":
            entered.set()
            await release.wait()
            if fail_first:
                raise ApplicationError("Review unavailable", non_retryable=True)
        return "report"

    @activity.defn(name="review_resolution_running_activity")
    async def resolution_running(inputs: ReviewPRWorkflowInputs) -> bool:
        return False

    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[ReviewPRQueueWorkflow, ScheduledReviewStub],
            activities=[record, resolution_running],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                ReviewPRQueueWorkflow.run,
                ReviewPRQueueInputs(requests=[first]),
                id=queue,
                task_queue=queue,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                start_signal="request_review",
                start_signal_args=[first],
            )
            await asyncio.wait_for(entered.wait(), timeout=10)
            for request in (
                first,
                replace(first, requested_head_sha="b"),
                replace(first, requested_head_sha="c"),
                replace(first, review_mode="full", trigger_source="ui", requested_head_sha="c"),
            ):
                await env.client.start_workflow(
                    ReviewPRQueueWorkflow.run,
                    ReviewPRQueueInputs(requests=[request]),
                    id=queue,
                    task_queue=queue,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    start_signal="request_review",
                    start_signal_args=[request],
                )
            release.set()
            assert await handle.result() == "report"

    completed = [(review.review_mode, review.requested_head_sha) for review in reviews]
    assert completed[-2:] == [("full", "c"), ("flash", "c")]
    assert all(item == ("flash", "a") for item in completed[:-2])
    assert len(completed) == (4 if fail_first else 3)


@pytest.mark.asyncio
async def test_automatic_review_waits_for_resolution_before_starting() -> None:
    probes = 0
    reviewed = False
    request = ReviewPRWorkflowInputs(team_id=1, user_id=1, owner="o", repo="r", pr_number=7)

    @activity.defn(name="review_resolution_running_activity")
    async def resolution_running(inputs: ReviewPRWorkflowInputs) -> bool:
        nonlocal probes
        probes += 1
        assert not reviewed
        return probes == 1

    @activity.defn(name="record_scheduled_review")
    async def record(inputs: ReviewPRWorkflowInputs) -> str:
        nonlocal reviewed
        reviewed = True
        return "report"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[ReviewPRQueueWorkflow, ScheduledReviewStub],
            activities=[record, resolution_running],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            assert (
                await env.client.execute_workflow(
                    ReviewPRQueueWorkflow.run, ReviewPRQueueInputs(requests=[request]), id=queue, task_queue=queue
                )
                == "report"
            )
    assert reviewed
    assert probes == 2


@pytest.mark.parametrize("resolve_comments,expect_pending", [(False, False), (None, True)])
def test_a_repeated_full_request_waits_when_it_changes_comment_resolution(
    resolve_comments: bool | None, expect_pending: bool
) -> None:
    active = ReviewPRWorkflowInputs(
        team_id=1,
        user_id=1,
        owner="PostHog",
        repo="posthog",
        pr_number=7,
        review_mode="full",
        trigger_source="ui",
        requested_head_sha="a",
        publish=True,
        acting_user_id=1,
        resolve_comments=False,
    )
    request = replace(active, resolve_comments=resolve_comments)
    queue = ReviewRequestQueue(active=active)

    queue.add(request)

    assert queue.pending == ({"full": request} if expect_pending else {})
