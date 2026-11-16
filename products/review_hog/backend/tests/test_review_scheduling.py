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
from products.review_hog.backend.temporal.types import (
    ReviewPRQueueInputs,
    ReviewPRWorkflowInputs,
    SilentStamphogRequest,
)


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
        trigger_action="opened",
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
                replace(first, requested_head_sha="b", trigger_action="synchronize"),
                replace(first, requested_head_sha="c", trigger_action="ready_for_review"),
                replace(first, review_mode="full", trigger_source="ui", requested_head_sha="c", trigger_action=None),
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
            # Stamphog reads the waiting heads from this query, because they exist only in the queue.
            heads = await handle.query("requested_heads")
            assert (heads["active"], sorted(heads["pending"])) == (["a"], ["c", "c"])
            release.set()
            assert await handle.result() == "report"

    completed = [(review.review_mode, review.requested_head_sha, review.trigger_action) for review in reviews]
    assert completed[-2:] == [("full", "c", None), ("flash", "c", "ready_for_review")]
    assert all(item == ("flash", "a", "opened") for item in completed[:-2])
    assert len(completed) == (4 if fail_first else 3)


@pytest.mark.asyncio
async def test_a_ready_event_for_the_running_turns_head_starts_silent_stamphog_once_the_turn_ends() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    reviews: list[ReviewPRWorkflowInputs] = []
    silent_requests: list[SilentStamphogRequest] = []
    draft_opened = ReviewPRWorkflowInputs(
        team_id=1,
        user_id=1,
        owner="PostHog",
        repo="posthog",
        pr_number=7,
        review_mode="flash",
        trigger_source="automatic",
        requested_head_sha="a",
        trigger_action="opened",
        publish=True,
    )
    marked_ready = replace(draft_opened, trigger_action="ready_for_review", marks_ready=True)

    @activity.defn(name="record_scheduled_review")
    async def record(inputs: ReviewPRWorkflowInputs) -> str:
        reviews.append(inputs)
        entered.set()
        await release.wait()
        return "report"

    @activity.defn(name="review_resolution_running_activity")
    async def resolution_running(inputs: ReviewPRWorkflowInputs) -> bool:
        return False

    @activity.defn(name="start_silent_stamphog_activity")
    async def start_silent_stamphog(request: SilentStamphogRequest) -> None:
        silent_requests.append(request)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[ReviewPRQueueWorkflow, ScheduledReviewStub],
            activities=[record, resolution_running, start_silent_stamphog],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                ReviewPRQueueWorkflow.run,
                ReviewPRQueueInputs(requests=[draft_opened]),
                id=queue,
                task_queue=queue,
            )
            await asyncio.wait_for(entered.wait(), timeout=10)
            await handle.signal("request_review", marked_ready)
            release.set()
            assert await handle.result() == "report"

    assert reviews == [draft_opened]
    assert silent_requests == [
        SilentStamphogRequest(team_id=1, repository="PostHog/posthog", pr_number=7, head_sha="a")
    ]


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


def test_a_later_request_for_the_same_waiting_head_keeps_the_pr_ready() -> None:
    running = ReviewPRWorkflowInputs(
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
    marked_ready = replace(running, requested_head_sha="b", trigger_action="ready_for_review", marks_ready=True)
    same_head_push = replace(marked_ready, trigger_action="synchronize", marks_ready=False)
    queue = ReviewRequestQueue(active=running)

    queue.add(marked_ready)
    queue.add(same_head_push)

    assert queue.pending == {"automatic": replace(same_head_push, marks_ready=True)}
