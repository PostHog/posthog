import json
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ChildWorkflowError
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.temporal.types import (
    TRIGGER_AUTOMATIC,
    ReviewPRQueueInputs,
    ReviewPRWorkflowInputs,
    resolve_pr_workflow_id,
)


class ReviewRequestQueue:
    def __init__(self, active: ReviewPRWorkflowInputs | None = None) -> None:
        self.active = active
        self.pending: dict[str, ReviewPRWorkflowInputs] = {}

    def add(self, request: ReviewPRWorkflowInputs) -> None:
        if self.active is not None:
            if (
                request.team_id != self.active.team_id
                or request.repository.lower() != self.active.repository.lower()
                or request.pr_number != self.active.pr_number
                or request.head_branch != self.active.head_branch
            ):
                return
            if (
                request.review_mode == self.active.review_mode
                and request.requested_head_sha == self.active.requested_head_sha
                and request.publish == self.active.publish
                and request.acting_user_id == self.active.acting_user_id
                and request.resolve_comments == self.active.resolve_comments
                and (request.trigger_source == TRIGGER_AUTOMATIC) == (self.active.trigger_source == TRIGGER_AUTOMATIC)
            ):
                return
        key = TRIGGER_AUTOMATIC if request.trigger_source == TRIGGER_AUTOMATIC else request.review_mode
        self.pending[key] = request

    def take(self) -> ReviewPRWorkflowInputs:
        # Explicit requests take precedence over another automatic follow-up.
        key = next(key for key in (REVIEW_MODE_FULL, REVIEW_MODE_FLASH, TRIGGER_AUTOMATIC) if key in self.pending)
        self.active = self.pending.pop(key)
        return self.active


@activity.defn
async def review_resolution_running_activity(input: ReviewPRWorkflowInputs) -> bool:
    if input.pr_number is None:
        return False
    client = await async_connect()
    workflow_id = resolve_pr_workflow_id(
        team_id=input.team_id, owner=input.owner, repo=input.repo, pr_number=input.pr_number
    )
    try:
        description = await client.get_workflow_handle(workflow_id).describe()
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return False
        raise
    return description.status == WorkflowExecutionStatus.RUNNING


@workflow.defn(name="review-pr-queue")
class ReviewPRQueueWorkflow:
    @workflow.init
    def __init__(self, inputs: ReviewPRQueueInputs) -> None:
        self._requests = ReviewRequestQueue()
        for request in inputs.requests:
            self._requests.add(request)

    @staticmethod
    def parse_inputs(inputs: list[str]) -> ReviewPRQueueInputs:
        data = json.loads(inputs[0])
        return ReviewPRQueueInputs(requests=[ReviewPRWorkflowInputs(**request) for request in data["requests"]])

    @workflow.signal
    def request_review(self, request: ReviewPRWorkflowInputs) -> None:
        self._requests.add(request)

    @workflow.run
    async def run(self, inputs: ReviewPRQueueInputs) -> str:
        result = ""
        while self._requests.pending:
            request = self._requests.take()
            while await workflow.execute_activity(
                review_resolution_running_activity,
                request,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
            ):
                await workflow.sleep(timedelta(seconds=15))
            try:
                result = await workflow.execute_child_workflow(
                    "review-pr",
                    request,
                    id=f"{workflow.info().workflow_id}/turn",
                    result_type=str,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except ChildWorkflowError:
                if not self._requests.pending:
                    raise
                workflow.logger.exception("Review failed; processing the next requested review")
            self._requests.active = None
            if self._requests.pending and workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(ReviewPRQueueInputs(requests=list(self._requests.pending.values())))
        return result
