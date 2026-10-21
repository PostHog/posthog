import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async
from temporalio.client import Client, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.dataclasses import frozen
from posthog.models import Integration, Organization, Team, User

from products.docs_freshness.backend.facade.api import accept_pull_request_event
from products.docs_freshness.backend.facade.contracts import PullRequestHead
from products.docs_freshness.backend.logic.impact_check import docs_agent_origin_key
from products.docs_freshness.backend.temporal import ACTIVITIES, WORKFLOWS
from products.tasks.backend.facade.sandbox import ExecutionResult
from products.tasks.backend.models import Task

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

_MODULE = "products.docs_freshness.backend.logic.impact_check"
_HEAD_SHA = "a" * 40
_HEAD = PullRequestHead(repository="PostHog/posthog", pr_number=42, head_sha=_HEAD_SHA)
_IMPACTED = [{"page": "support/widget.mdx", "kind": "ui-label", "claim": "Secret API Key", "guard": "renamed"}]
_PROMPT = (
    "PR {event.properties.pr_url} at {event.properties.head_sha}\n{event.properties.claims}\n{event.properties.pages}"
)
_PAYLOAD = {
    "action": "synchronize",
    "repository": {"full_name": "PostHog/posthog"},
    "pull_request": {"number": 42, "state": "open", "head": {"sha": _HEAD_SHA}},
}


@frozen
class _DocsAgentTask:
    origin_key: str | None
    description: str
    posthog_mcp_scopes: str | list[str]


def _docs_agent_tasks(team_id: int) -> list[_DocsAgentTask]:
    return [
        _DocsAgentTask(
            origin_key=task.origin_key,
            description=task.description,
            posthog_mcp_scopes=task.latest_run.state["pending_dispatch"]["posthog_mcp_scopes"],
        )
        for task in Task.objects.filter(team_id=team_id).order_by("created_at")
    ]


def _sandbox_executor(exit_codes: list[int], impacted: list[dict]) -> Callable[..., ExecutionResult]:
    remaining = list(exit_codes)

    def execute(command: str, **_kwargs: Any) -> ExecutionResult:
        if command.startswith("cat "):
            return ExecutionResult(stdout=_PROMPT, stderr="", exit_code=0)
        exit_code = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return ExecutionResult(stdout=json.dumps(impacted if exit_code == 1 else []), stderr="", exit_code=exit_code)

    return execute


@pytest.fixture
def owner() -> Iterator[User]:
    organization = Organization.objects.create(name="docs freshness")
    team = Team.objects.create(organization=organization, name="docs freshness")
    user = User.objects.create_and_join(organization, "docs-freshness@example.com", "password")
    Integration.objects.create(team=team, kind="github", integration_id="1", config={})
    user.current_team = team
    yield user


@pytest.mark.parametrize(
    "current_head_sha,exit_codes,deliveries,expected_verdicts,expected_agent_tasks,capture_failures",
    [
        pytest.param(_HEAD_SHA, [1], 1, ["flagged"], 1, 0, id="flagged"),
        pytest.param(_HEAD_SHA, [1], 2, ["flagged"], 1, 0, id="redelivered"),
        pytest.param(_HEAD_SHA, [3, 3, 1], 1, ["flagged"], 1, 0, id="merge_ref_lags_then_settles"),
        pytest.param(_HEAD_SHA, [0], 1, ["clear"], 0, 0, id="clear"),
        pytest.param("b" * 40, [0], 1, [], 0, 0, id="superseded"),
        pytest.param(_HEAD_SHA, [4], 1, ["unmergeable"], 0, 0, id="unmergeable_after_last_attempt"),
        pytest.param(_HEAD_SHA, [1], 1, ["flagged"], 1, 1, id="capture_fails_after_agent_start"),
    ],
)
async def test_verdict_for_head(
    current_head_sha: str,
    exit_codes: list[int],
    deliveries: int,
    expected_verdicts: list[str],
    expected_agent_tasks: int,
    capture_failures: int,
    owner: User,
    settings: Any,
) -> None:
    settings.DOCS_FRESHNESS_TEAM_ID = owner.current_team_id
    settings.DOCS_FRESHNESS_OWNER_USER_ID = owner.id
    settings.DOCS_FRESHNESS_TOOL_REF = "main"
    github = MagicMock()
    github.get_pull_request.return_value = {"success": True, "state": "open", "head_sha": current_head_sha}
    sandbox = MagicMock()
    sandbox.execute.side_effect = _sandbox_executor(exit_codes, _IMPACTED)
    captured: list[dict] = []
    remaining_capture_failures = [capture_failures]

    def capture(**event: Any) -> None:
        if remaining_capture_failures[0]:
            remaining_capture_failures[0] -= 1
            raise ConnectionError("capture unavailable")
        captured.append(event)

    @contextmanager
    def scoped_capture() -> Iterator[Callable[..., None]]:
        yield capture

    async with await WorkflowEnvironment.start_time_skipping() as env:
        settings.DOCS_FRESHNESS_TASK_QUEUE = str(uuid.uuid4())

        started_handles: list[WorkflowHandle] = []
        start_workflow = env.client.start_workflow

        async def start_and_keep_handle(*args: Any, **kwargs: Any) -> WorkflowHandle:
            handle = await start_workflow(*args, **kwargs)
            started_handles.append(handle)
            return handle

        async def connect() -> Client:
            return env.client

        with (
            patch("products.docs_freshness.backend.temporal.client.async_connect", connect),
            patch.object(env.client, "start_workflow", start_and_keep_handle),
            patch(f"{_MODULE}.GitHubIntegration.first_for_team_repository", return_value=github),
            patch(f"{_MODULE}.get_sandbox_class") as sandbox_class,
            patch("products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow"),
            patch(f"{_MODULE}.ph_scoped_capture", scoped_capture),
        ):
            sandbox_class.return_value.create.return_value = sandbox
            async with Worker(
                env.client,
                task_queue=settings.DOCS_FRESHNESS_TASK_QUEUE,
                workflows=WORKFLOWS,
                activities=ACTIVITIES,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                for _ in range(deliveries):
                    await sync_to_async(accept_pull_request_event)(_PAYLOAD)
                    await started_handles[-1].result()

    assert [event["properties"]["verdict"] for event in captured] == expected_verdicts
    assert len({event["uuid"] for event in captured}) == len(captured)
    agent_tasks = await sync_to_async(_docs_agent_tasks)(owner.current_team_id)
    assert len(agent_tasks) == expected_agent_tasks
    if expected_agent_tasks:
        assert agent_tasks[0].origin_key == docs_agent_origin_key(_HEAD)
        assert agent_tasks[0].posthog_mcp_scopes == []
        description = agent_tasks[0].description
        assert "https://github.com/PostHog/posthog/pull/42" in description
        assert '"claim": "Secret API Key"' in description
        assert '["support/widget.mdx"]' in description
        assert "guard" not in description
