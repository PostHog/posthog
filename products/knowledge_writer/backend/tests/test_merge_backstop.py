import os
import uuid

import pytest
from unittest.mock import patch

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.knowledge_writer.backend.temporal.backstop import (
    VERDICT_RECORDED,
    MergeBackstopInputs,
    MergeBackstopWorkflow,
)
from products.knowledge_writer.backend.temporal.client import PUSH_SEEN

COMMIT_SHA = "b" * 40
SIGNAL_BACKSTOP = "products.knowledge_writer.backend.temporal.client.signal_merge_backstop"


async def _run_backstop(*signals: str) -> list[MergeBackstopInputs]:
    merge_checks: list[MergeBackstopInputs] = []

    @activity.defn(name="run_merge_check_activity")
    async def record_merge_check(inputs: MergeBackstopInputs) -> None:
        merge_checks.append(inputs)

    task_queue = f"knowledge-writer-{uuid.uuid4()}"
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[MergeBackstopWorkflow],
            activities=[record_merge_check],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                MergeBackstopWorkflow.run,
                MergeBackstopInputs(commit_sha=COMMIT_SHA, team_id=1),
                id=f"knowledge_writer:repo_merge:{COMMIT_SHA}",
                task_queue=task_queue,
                start_signal=PUSH_SEEN,
            )
            for signal in signals:
                await handle.signal(signal)
            await handle.result()
    return merge_checks


@pytest.mark.asyncio
async def test_a_merge_with_no_verdict_within_the_delay_gets_the_backstop_merge_check() -> None:
    merge_checks = await _run_backstop()

    assert merge_checks == [MergeBackstopInputs(commit_sha=COMMIT_SHA, team_id=1)]


@pytest.mark.asyncio
async def test_a_recorded_verdict_stops_the_backstop() -> None:
    merge_checks = await _run_backstop(VERDICT_RECORDED)

    assert merge_checks == []


@pytest.fixture
def writer_env(team, user):
    with patch.dict(
        os.environ,
        {
            "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
            "KNOWLEDGE_WRITER_USER_ID": str(user.id),
            "KNOWLEDGE_WRITER_DOCS_REPOSITORY": "PostHog/posthog.com",
        },
    ):
        yield


@pytest.mark.django_db
@pytest.mark.parametrize(
    "report, expected_status_code, expected_body",
    [
        pytest.param(
            {
                "commit_sha": COMMIT_SHA,
                "commit_url": f"https://github.com/PostHog/posthog/commit/{COMMIT_SHA}",
                "title": "Refactor the query runner",
                "needs_docs": False,
                "reason": "no_mapped_section",
            },
            200,
            {"status": "no_docs"},
            id="verdict",
        ),
        pytest.param(
            {"commit_sha": "not-a-sha", "commit_url": "x", "title": "x", "needs_docs": False, "reason": "x"},
            400,
            None,
            id="invalid",
        ),
    ],
)
def test_merge_verdicts_endpoint_records_a_verdict_and_signals_the_backstop(
    client, team, user, writer_env, report, expected_status_code, expected_body
) -> None:
    client.force_login(user)

    with patch(SIGNAL_BACKSTOP) as signal_backstop:
        response = client.post(
            f"/api/projects/{team.id}/knowledge_writer/merge_verdicts/", report, content_type="application/json"
        )

    assert response.status_code == expected_status_code
    if expected_body is None:
        signal_backstop.assert_not_called()
        return
    assert response.json() == expected_body
    signal_backstop.assert_called_once_with(COMMIT_SHA, team_id=team.id, signal=VERDICT_RECORDED)
