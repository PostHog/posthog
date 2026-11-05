import uuid

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.stamphog.backend.temporal.activities import StamphogReviewInput
from products.stamphog.backend.temporal.constants import STAMPHOG_ATTESTATION_MAX_POLLS, STAMPHOG_BOT_REVIEW_MAX_POLLS
from products.stamphog.backend.temporal.workflow import StamphogReviewWorkflow


def _stub_activities(
    calls: list[str],
    in_flight_polls: int,
    reviews_completed: bool,
    verdict: dict | None = None,
    rereview_fails: bool = False,
    attestation_reported_on_poll: int | None = None,
    failed_poll_attempts: int = 0,
) -> list:
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
        in_flight = polls <= in_flight_polls
        return {
            "in_flight": ["PostHog Review"] if in_flight else [],
            "reviews_completed": reviews_completed and not in_flight,
        }

    @activity.defn(name="rereview_after_external_review_finished")
    async def rereview(input: StamphogReviewInput) -> dict:
        calls.append("rereview_after_external_review_finished")
        if rereview_fails:
            raise RuntimeError("broker unreachable")
        return {"requested": True}

    @activity.defn(name="poll_pending_attestations")
    async def poll(input: StamphogReviewInput) -> dict:
        calls.append("poll_pending_attestations")
        polls = calls.count("poll_pending_attestations")
        if polls <= failed_poll_attempts:
            raise RuntimeError("github unreachable")
        return {"done": attestation_reported_on_poll is not None and polls >= attestation_reported_on_poll}

    return [
        list_in_flight,
        rereview,
        poll,
        stub("dismiss_stale_approvals", {}),
        stub("signal_review_started", {}),
        # No sandbox id, so the workflow skips the checkout and the sandbox review.
        stub("start_review_sandbox", {"sandbox_id": ""}),
        stub("fetch_review_context", {}),
        stub("refuse_on_pre_gates", {"refused": False}),
        stub("refresh_review_evidence", {}),
        stub("post_verdict", verdict or {"verdict": "approved"}),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "in_flight_polls, reviews_completed, refreshed",
    [
        pytest.param(0, False, False, id="nothing-in-flight"),
        # The engine counts the completed review, so it must also see the threads that review left.
        pytest.param(0, True, True, id="review-completed-before-the-first-poll"),
        pytest.param(2, False, True, id="reviewer-finishes-within-the-budget"),
        pytest.param(STAMPHOG_BOT_REVIEW_MAX_POLLS, False, True, id="budget-runs-out"),
    ],
)
async def test_evidence_is_read_again_after_waiting_for_reviewers(
    in_flight_polls: int, reviews_completed: bool, refreshed: bool
) -> None:
    # The context fetch runs before the wait. A review posted during the wait must reach the engine,
    # so the evidence is read again after the last poll and before the verdict.
    calls: list[str] = []
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[StamphogReviewWorkflow],
            activities=_stub_activities(calls, in_flight_polls, reviews_completed),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "waited_on_external_review, rereview_fails, expected_attempts",
    [
        pytest.param(False, False, 0, id="no-external-review-to-wait-for"),
        pytest.param(True, False, 1, id="dispatches-once"),
        pytest.param(True, True, 3, id="retries-a-failed-dispatch"),
    ],
)
async def test_wait_on_an_external_review_dispatches_the_rereview_in_its_own_activity(
    waited_on_external_review: bool, rereview_fails: bool, expected_attempts: int
) -> None:
    calls: list[str] = []
    verdict = {"verdict": "wait", "waited_on_external_review": waited_on_external_review}
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[StamphogReviewWorkflow],
            activities=_stub_activities(calls, 0, False, verdict=verdict, rereview_fails=rereview_fails),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                StamphogReviewWorkflow.run,
                StamphogReviewInput(review_run_id=str(uuid.uuid4()), team_id=1),
                id=queue,
                task_queue=queue,
            )

    assert result == {"status": "completed", "verdict": "wait"}
    assert calls.count("rereview_after_external_review_finished") == expected_attempts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "waits_on_attestations, reported_on_poll, failed_poll_attempts, expected_polls",
    [
        pytest.param(False, None, 0, 0, id="nothing-to-wait-for"),
        pytest.param(True, 3, 0, 3, id="stops-once-reported"),
        pytest.param(True, None, 0, STAMPHOG_ATTESTATION_MAX_POLLS, id="budget-runs-out"),
        # The first poll fails all three of its attempts, and the next timer's poll sees the result.
        pytest.param(True, 4, 3, 4, id="failed-poll-keeps-polling"),
    ],
)
async def test_wait_on_an_attestation_polls_until_it_reports(
    waits_on_attestations: bool, reported_on_poll: int | None, failed_poll_attempts: int, expected_polls: int
) -> None:
    # A WAIT on a CI result has no webhook to wake it, so the workflow polls from a durable timer.
    calls: list[str] = []
    verdict = {"verdict": "wait", "waited_on_external_review": False, "waits_on_attestations": waits_on_attestations}
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[StamphogReviewWorkflow],
            activities=_stub_activities(
                calls,
                0,
                False,
                verdict=verdict,
                attestation_reported_on_poll=reported_on_poll,
                failed_poll_attempts=failed_poll_attempts,
            ),
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                StamphogReviewWorkflow.run,
                StamphogReviewInput(review_run_id=str(uuid.uuid4()), team_id=1),
                id=queue,
                task_queue=queue,
            )

    assert result == {"status": "completed", "verdict": "wait"}
    assert calls.count("poll_pending_attestations") == expected_polls
