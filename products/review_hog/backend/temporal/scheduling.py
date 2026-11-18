import json
from dataclasses import replace
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from products.review_hog.backend.reviewer.constants import REVIEW_MODE_FLASH, REVIEW_MODE_FULL
from products.review_hog.backend.temporal.types import (
    TRIGGER_AUTOMATIC,
    CompleteJoinedStamphogRequestsInput,
    ReviewPRQueueInputs,
    ReviewPRWorkflowInputs,
    SilentStamphogRequest,
    resolve_pr_workflow_id,
)

SILENT_STAMPHOG_PATCH = "reviewhog-silent-stamphog-2026-11"
STAMPHOG_REPORT_AFTER_TURN_PATCH = "reviewhog-stamphog-report-after-turn-2026-11"
STAMPHOG_JOINED_REQUESTS_PATCH = "reviewhog-stamphog-joined-requests-2026-11"


async def request_silent_stamphog(request: ReviewPRWorkflowInputs, head_sha: str) -> None:
    """Ask stamphog for a silent review of a head that `request` marked ready. Best effort.

    The activity reads the coverage that the head's automatic turn recorded earlier, for an event that
    came after that turn started.
    """
    if request.pr_number is None:
        return
    try:
        await workflow.execute_activity(
            "start_silent_stamphog_activity",
            SilentStamphogRequest(
                team_id=request.team_id, repository=request.repository, pr_number=request.pr_number, head_sha=head_sha
            ),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
    except ActivityError:
        workflow.logger.warning("Could not ask stamphog for a silent review")


class ReviewRequestQueue:
    def __init__(self, active: ReviewPRWorkflowInputs | None = None) -> None:
        self.active = active
        self.pending: dict[str, ReviewPRWorkflowInputs] = {}
        self.joined_refusals: dict[str, ReviewPRWorkflowInputs] = {}

    @staticmethod
    def _key(request: ReviewPRWorkflowInputs) -> str:
        if request.stamphog_review_run_id is not None:
            return f"stamphog:{request.stamphog_review_run_id}"
        return TRIGGER_AUTOMATIC if request.trigger_source == TRIGGER_AUTOMATIC else request.review_mode

    def _same_turn(self, request: ReviewPRWorkflowInputs) -> bool:
        active = self.active
        return active is not None and (
            request.review_mode == active.review_mode
            and request.requested_head_sha == active.requested_head_sha
            and request.publish == active.publish
            and request.acting_user_id == active.acting_user_id
            and request.resolve_comments == active.resolve_comments
            and (request.trigger_source == TRIGGER_AUTOMATIC) == (active.trigger_source == TRIGGER_AUTOMATIC)
        )

    def _join_refusal(self, request: ReviewPRWorkflowInputs) -> bool:
        if (
            request.stamphog_review_run_id is not None
            and request.requested_head_sha is not None
            and request.review_mode == REVIEW_MODE_FULL
            and self._same_turn(request)
        ):
            self.joined_refusals[request.stamphog_review_run_id] = request
            return True
        return False

    def add(self, request: ReviewPRWorkflowInputs) -> None:
        if self.active is not None:
            if (
                request.team_id != self.active.team_id
                or request.repository.lower() != self.active.repository.lower()
                or request.pr_number != self.active.pr_number
                or request.head_branch != self.active.head_branch
            ):
                return
            if self._join_refusal(request):
                return
            if request.stamphog_review_run_id is None and self._same_turn(request):
                # The running turn reviews this head, but its own request can predate the PR being ready.
                if request.marks_ready:
                    self.active = replace(self.active, marks_ready=True)
                return
        key = self._key(request)
        waiting = self.pending.get(key)
        # A later request for the same head replaces the waiting one, but the PR stays ready for review.
        if waiting is not None and waiting.requested_head_sha == request.requested_head_sha and waiting.marks_ready:
            request = replace(request, marks_ready=True)
        self.pending[key] = request

    def requested_heads(self) -> dict[str, list[str | None]]:
        """The heads the active request and the waiting requests ask for. None is a request for the live head."""
        return {
            "active": [self.active.requested_head_sha] if self.active is not None else [],
            "pending": [request.requested_head_sha for request in self.pending.values()],
        }

    def take(self) -> ReviewPRWorkflowInputs:
        # Explicit requests take precedence over another automatic follow-up.
        keys = (
            REVIEW_MODE_FULL,
            *(key for key in self.pending if key.startswith("stamphog:")),
            REVIEW_MODE_FLASH,
            TRIGGER_AUTOMATIC,
        )
        key = next(key for key in keys if key in self.pending)
        self.active = self.pending.pop(key)
        for key, request in list(self.pending.items()):
            if self._join_refusal(request):
                del self.pending[key]
        return self.active

    def retry_joined(self, requests: list[ReviewPRWorkflowInputs]) -> None:
        for request in requests:
            self.pending[self._key(request)] = request


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

    # Read by the status provider for stamphog, because a waiting request exists only in this state.
    @workflow.query
    def requested_heads(self) -> dict[str, list[str | None]]:
        return self._requests.requested_heads()

    async def _complete_joined_refusals(self, request: ReviewPRWorkflowInputs, report_id: str | None) -> None:
        while self._requests.joined_refusals:
            joined = list(self._requests.joined_refusals.values())
            self._requests.joined_refusals.clear()
            completed = False
            if report_id and request.queue_turn_id is not None and request.requested_head_sha is not None:
                completed = await workflow.execute_activity(
                    "complete_joined_stamphog_requests_activity",
                    CompleteJoinedStamphogRequestsInput(
                        team_id=request.team_id,
                        report_id=report_id,
                        queue_turn_id=request.queue_turn_id,
                        head_sha=request.requested_head_sha,
                        request_ids=[
                            item.stamphog_review_run_id for item in joined if item.stamphog_review_run_id is not None
                        ],
                    ),
                    result_type=bool,
                    start_to_close_timeout=timedelta(seconds=30),
                )
            if not completed:
                self._requests.retry_joined(joined)

    async def _answer_ready_event(self, request: ReviewPRWorkflowInputs, *, turn_succeeded: bool) -> None:
        """Ask stamphog about the head of a ready event once the turn for it ended.

        The activity queues the silent review for a head recorded clean and reports every other head as
        unreviewed. A ready event can join the running turn, so the active request decides, not `request`.
        A waiting request that a newer head replaces is not answered: its head is stale, stamphog acts on
        the live head, and the newer event answers for itself.

        A queue whose history predates the patch keeps its old commands: only a ready event that joined a
        successful turn was answered here, and the turn answered for its own ready event.
        """
        active = self._requests.active
        if request.answered_by_queue:
            if active is not None and active.marks_ready and active.requested_head_sha is not None:
                await request_silent_stamphog(active, active.requested_head_sha)
            return
        if (
            turn_succeeded
            and workflow.patched(SILENT_STAMPHOG_PATCH)
            and active is not None
            and active.marks_ready
            and not request.marks_ready
            and request.requested_head_sha is not None
        ):
            await request_silent_stamphog(request, request.requested_head_sha)

    @workflow.run
    async def run(self, inputs: ReviewPRQueueInputs) -> str:
        result = ""
        while self._requests.pending:
            request = self._requests.take()
            if workflow.patched(STAMPHOG_JOINED_REQUESTS_PATCH):
                request = replace(request, queue_turn_id=str(workflow.uuid4()))
            while await workflow.execute_activity(
                review_resolution_running_activity,
                request,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_interval=timedelta(minutes=1)),
            ):
                await workflow.sleep(timedelta(seconds=15))
            # The patch decides once for the queue's life, because a queue that replays turns from before it
            # must keep the commands of those turns.
            if workflow.patched(STAMPHOG_REPORT_AFTER_TURN_PATCH):
                request = replace(request, answered_by_queue=True)
            try:
                result = await workflow.execute_child_workflow(
                    "review-pr",
                    request,
                    id=f"{workflow.info().workflow_id}/turn",
                    result_type=str,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                await self._answer_ready_event(request, turn_succeeded=True)
                await self._complete_joined_refusals(request, result)
            except ChildWorkflowError:
                await self._answer_ready_event(request, turn_succeeded=False)
                await self._complete_joined_refusals(request, None)
                if not self._requests.pending:
                    raise
                workflow.logger.exception("Review failed; processing the next requested review")
            self._requests.active = None
            if self._requests.pending and workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(ReviewPRQueueInputs(requests=list(self._requests.pending.values())))
        return result
