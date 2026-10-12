import uuid

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.stamphog.backend.temporal.activities import StamphogReviewInput
from products.stamphog.backend.temporal.constants import STAMPHOG_BOT_REVIEW_MAX_POLLS
from products.stamphog.backend.temporal.workflow import StamphogReviewWorkflow


def _stub_activities(calls: list[str], in_flight_polls: int) -> list:
    def stub(name: str, result: dict):
        @activity.defn(name=name)
        async def run(input: StamphogReviewInput) -> dict:
            calls.append(name)
            return result

        return run

    @activity.defn(name="list_in_flight_reviewer_bots")
    async def list_in_flight(input: StamphogReviewInput) -> dict:
        calls.append("list_in_flight_reviewer_bots")
        polls = calls.count("list_in_flight_reviewer_bots")
        return {"in_flight": ["PostHog Review"] if polls <= in_flight_polls else []}

    return [
        list_in_flight,
        stub("dismiss_stale_approvals", {}),
        stub("signal_review_started", {}),
        # No sandbox id, so the workflow skips the checkout and the sandbox review.
        stub("start_review_sandbox", {"sandbox_id": ""}),
        stub("fetch_review_context", {}),
        stub("refuse_on_pre_gates", {"refused": False}),
        stub("refresh_review_evidence", {}),
        stub("post_verdict", {"verdict": "approved"}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "in_flight_polls, refreshed",
    [
        pytest.param(0, False, id="nothing-in-flight"),
        pytest.param(2, True, id="reviewer-finishes-within-the-budget"),
        pytest.param(STAMPHOG_BOT_REVIEW_MAX_POLLS, True, id="budget-runs-out"),
    ],
)
async def test_evidence_is_read_again_after_waiting_for_reviewers(in_flight_polls: int, refreshed: bool) -> None:
    # The context fetch runs before the wait. A review posted during the wait must reach the engine,
    # so the evidence is read again after the last poll and before the verdict.
    calls: list[str] = []
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[StamphogReviewWorkflow],
            activities=_stub_activities(calls, in_flight_polls),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                StamphogReviewWorkflow.run,
                StamphogReviewInput(review_run_id=str(uuid.uuid4()), team_id=1),
                id=queue,
                task_queue=queue,
            )

    review_steps = [name for name in calls if name in ("list_in_flight_reviewer_bots", "refresh_review_evidence")]
    expected_polls = min(in_flight_polls + 1, STAMPHOG_BOT_REVIEW_MAX_POLLS)
    assert review_steps == ["list_in_flight_reviewer_bots"] * expected_polls + (
        ["refresh_review_evidence"] if refreshed else []
    )
    assert calls[-1] == "post_verdict"
