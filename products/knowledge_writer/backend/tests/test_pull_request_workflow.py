import os
import asyncio
import logging
from collections.abc import Callable

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration

from products.knowledge_writer.backend.logic.pull_requests import OUTCOME_EVENT
from products.knowledge_writer.backend.temporal.client import signal_pull_request_closed_workflow
from products.knowledge_writer.backend.temporal.pull_request_workflow import (
    STALE_AFTER,
    PullRequestInputs,
    WriterPullRequestWorkflow,
    pull_request_workflow_id,
    settle_pull_request_activity,
    start_pull_request_workflow,
)

DOCS_REPOSITORY = "PostHog/posthog.com"
PULL_REQUEST_NUMBER = 42
WRITER_BRANCH = "knowledge-writer/0123456789ab"
WRITER_APP_LOGIN = "posthog-app[bot]"
OPENED_AT = "2026-11-01T00:00:00Z"
APPROVED_AT = "2026-11-01T06:00:00Z"
MERGED_AT = "2026-11-03T00:00:00Z"
STALE_CLOSED_AT = "2026-11-08T00:00:00Z"
GITHUB_REQUEST = "posthog.models.integration.GitHubIntegration.api_request"
CAPTURE = "products.knowledge_writer.backend.logic.pull_requests.ph_scoped_capture"
PULL_REQUEST_PATH = f"/repos/{DOCS_REPOSITORY}/pulls/{PULL_REQUEST_NUMBER}"


def _pull_request(*, state: str = "open", merged_at: str | None = None, closed_at: str | None = None) -> dict:
    return {
        "number": PULL_REQUEST_NUMBER,
        "html_url": f"https://github.com/{DOCS_REPOSITORY}/pull/{PULL_REQUEST_NUMBER}",
        "state": state,
        "merged": merged_at is not None,
        "merged_at": merged_at,
        "created_at": OPENED_AT,
        "closed_at": closed_at,
        "head": {"ref": WRITER_BRANCH, "repo": {"full_name": DOCS_REPOSITORY}},
    }


MERGED = _pull_request(state="closed", merged_at=MERGED_AT, closed_at=MERGED_AT)
APPROVAL = {"state": "APPROVED", "submitted_at": APPROVED_AT, "author_association": "MEMBER"}


class DocsPullRequestGitHub:
    def __init__(self, pull_request: dict, reviews: list[dict]) -> None:
        self.pull_request = pull_request
        self.reviews = reviews
        self.closed_by: str | None = None
        self.delete_status_code = 204
        self.is_unavailable = False
        self.writes: list[tuple[str, str]] = []
        self.on_pull_request_read: Callable[[], object] = lambda: None

    def __call__(self, method: str, path: str, **kwargs) -> MagicMock:
        if self.is_unavailable:
            return MagicMock(status_code=503)
        if method == "PATCH" and path == PULL_REQUEST_PATH:
            self.writes.append((method, path))
            self.closed_by = WRITER_APP_LOGIN
            self.pull_request = {**self.pull_request, "state": "closed", "closed_at": STALE_CLOSED_AT}
            return _replied(self.pull_request)
        if method == "DELETE":
            self.writes.append((method, path))
            return MagicMock(status_code=self.delete_status_code)
        if path == PULL_REQUEST_PATH:
            read = _replied(self.pull_request)
            self.on_pull_request_read()
            return read
        if path == f"{PULL_REQUEST_PATH}/reviews":
            return _replied(self.reviews)
        if path == f"/repos/{DOCS_REPOSITORY}/issues/{PULL_REQUEST_NUMBER}":
            return _replied({"closed_by": {"login": self.closed_by or "octo"}})
        raise AssertionError(f"unexpected GitHub call {method} {path}")


def _replied(payload: object) -> MagicMock:
    return MagicMock(status_code=200, json=MagicMock(return_value=payload))


@pytest.fixture
def writer_env(team, user):
    Integration.objects.create(
        team=team, kind="github", integration_id="31337", config={"account": {"name": "PostHog"}}
    )
    with (
        override_instance_config("GITHUB_APP_SLUG", "posthog-app"),
        patch.dict(os.environ, {"KNOWLEDGE_WRITER_DOCS_REPOSITORY": DOCS_REPOSITORY}),
    ):
        yield


@pytest.fixture
def temporal_logs_at_info():
    loggers = [logging.getLogger("temporalio.activity"), logging.getLogger("temporalio.workflow")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.INFO)
    yield
    for logger, level in zip(loggers, levels):
        logger.setLevel(level)


def _outcomes(scoped_capture: MagicMock) -> list[dict]:
    capture = scoped_capture.return_value.__enter__.return_value
    return [
        {"event": call.args[0], "uuid": call.kwargs["uuid"], **call.kwargs["properties"]}
        for call in capture.call_args_list
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "pull_request, reviews, is_closed_signal_sent, delete_status_code, expected_writes, expected_outcome",
    [
        pytest.param(
            MERGED,
            [APPROVAL],
            True,
            204,
            [],
            {
                "close_reason": "merged",
                "merged": True,
                "approved": True,
                "hours_to_first_approval": 6.0,
                "hours_open": 48.0,
            },
            id="merged_after_a_closed_signal",
        ),
        pytest.param(
            _pull_request(state="closed", closed_at=STALE_CLOSED_AT),
            [],
            True,
            204,
            [("DELETE", f"/repos/{DOCS_REPOSITORY}/git/refs/heads/{WRITER_BRANCH}")],
            {"close_reason": "closed_by_reviewer", "merged": False, "hours_open": 168.0},
            id="closed_by_a_reviewer_deletes_its_branch",
        ),
        pytest.param(
            _pull_request(),
            [
                {"state": "COMMENTED", "submitted_at": APPROVED_AT, "author_association": "MEMBER"},
                {**APPROVAL, "author_association": "NONE"},
            ],
            False,
            204,
            [("PATCH", PULL_REQUEST_PATH), ("DELETE", f"/repos/{DOCS_REPOSITORY}/git/refs/heads/{WRITER_BRANCH}")],
            {
                "close_reason": "closed_stale",
                "merged": False,
                "approved": False,
                "hours_to_first_approval": None,
                "hours_open": 168.0,
            },
            id="unapproved_by_a_maintainer_and_stale",
        ),
        pytest.param(
            _pull_request(),
            [],
            False,
            403,
            [("PATCH", PULL_REQUEST_PATH), ("DELETE", f"/repos/{DOCS_REPOSITORY}/git/refs/heads/{WRITER_BRANCH}")],
            {"close_reason": "closed_stale", "merged": False, "approved": False, "hours_open": 168.0},
            id="unapproved_and_stale_with_a_forbidden_branch_delete",
        ),
    ],
)
async def test_a_closed_writer_pull_request_captures_one_outcome(
    team,
    writer_env,
    temporal_logs_at_info,
    pull_request,
    reviews,
    is_closed_signal_sent,
    delete_status_code,
    expected_writes,
    expected_outcome,
) -> None:
    github = DocsPullRequestGitHub(pull_request, reviews)
    github.delete_status_code = delete_status_code
    inputs = PullRequestInputs(team_id=team.id, repository=DOCS_REPOSITORY, pull_request_number=PULL_REQUEST_NUMBER)
    with patch(GITHUB_REQUEST, side_effect=github), patch(CAPTURE) as scoped_capture:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                workflows=[WriterPullRequestWorkflow],
                activities=[settle_pull_request_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                for _ in range(2):
                    await start_pull_request_workflow(env.client, inputs)
                if is_closed_signal_sent:
                    await signal_pull_request_closed_workflow(DOCS_REPOSITORY, PULL_REQUEST_NUMBER, client=env.client)
                if not is_closed_signal_sent:
                    await env.sleep(STALE_AFTER)
                handle = env.client.get_workflow_handle(pull_request_workflow_id(DOCS_REPOSITORY, PULL_REQUEST_NUMBER))
                await asyncio.wait_for(handle.result(), timeout=60)
                await start_pull_request_workflow(env.client, inputs)
                await signal_pull_request_closed_workflow(DOCS_REPOSITORY, PULL_REQUEST_NUMBER, client=env.client)

    assert github.writes == expected_writes
    assert [(outcome["event"], outcome["close_reason"]) for outcome in _outcomes(scoped_capture)] == [
        (OUTCOME_EVENT, expected_outcome["close_reason"])
    ]
    outcome = _outcomes(scoped_capture)[0]
    assert {key: outcome[key] for key in expected_outcome} == expected_outcome


@pytest.mark.django_db(transaction=True)
async def test_an_approved_writer_pull_request_stays_open_past_the_stale_window(
    team, writer_env, temporal_logs_at_info
) -> None:
    github = DocsPullRequestGitHub(_pull_request(), [APPROVAL])
    stale_window_settled = asyncio.Event()
    loop = asyncio.get_running_loop()
    github.on_pull_request_read = lambda: loop.call_soon_threadsafe(stale_window_settled.set)
    inputs = PullRequestInputs(team_id=team.id, repository=DOCS_REPOSITORY, pull_request_number=PULL_REQUEST_NUMBER)
    with patch(GITHUB_REQUEST, side_effect=github), patch(CAPTURE) as scoped_capture:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                workflows=[WriterPullRequestWorkflow],
                activities=[settle_pull_request_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await start_pull_request_workflow(env.client, inputs)
                await env.sleep(STALE_AFTER)
                await asyncio.wait_for(stale_window_settled.wait(), timeout=60)
                github.pull_request = MERGED
                await signal_pull_request_closed_workflow(DOCS_REPOSITORY, PULL_REQUEST_NUMBER, client=env.client)
                handle = env.client.get_workflow_handle(pull_request_workflow_id(DOCS_REPOSITORY, PULL_REQUEST_NUMBER))
                await asyncio.wait_for(handle.result(), timeout=60)

    assert github.writes == []
    assert [(outcome["close_reason"], outcome["hours_to_first_approval"]) for outcome in _outcomes(scoped_capture)] == [
        ("merged", 6.0)
    ]


@pytest.mark.django_db(transaction=True)
async def test_a_github_outage_past_the_retry_budget_still_settles_once_github_recovers(
    team, writer_env, temporal_logs_at_info
) -> None:
    github = DocsPullRequestGitHub(MERGED, [APPROVAL])
    github.is_unavailable = True
    inputs = PullRequestInputs(team_id=team.id, repository=DOCS_REPOSITORY, pull_request_number=PULL_REQUEST_NUMBER)
    with patch(GITHUB_REQUEST, side_effect=github), patch(CAPTURE) as scoped_capture:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                workflows=[WriterPullRequestWorkflow],
                activities=[settle_pull_request_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await start_pull_request_workflow(env.client, inputs)
                await signal_pull_request_closed_workflow(DOCS_REPOSITORY, PULL_REQUEST_NUMBER, client=env.client)
                await env.sleep(STALE_AFTER)
                github.is_unavailable = False
                await start_pull_request_workflow(env.client, inputs)
                await signal_pull_request_closed_workflow(DOCS_REPOSITORY, PULL_REQUEST_NUMBER, client=env.client)
                handle = env.client.get_workflow_handle(pull_request_workflow_id(DOCS_REPOSITORY, PULL_REQUEST_NUMBER))
                await asyncio.wait_for(handle.result(), timeout=60)

    assert [(outcome["event"], outcome["close_reason"]) for outcome in _outcomes(scoped_capture)] == [
        (OUTCOME_EVENT, "merged")
    ]
