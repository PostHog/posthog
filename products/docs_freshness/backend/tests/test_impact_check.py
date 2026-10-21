import json
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async
from temporalio.client import Client, WorkflowFailureError, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.dataclasses import frozen
from posthog.models import Integration, Organization, Team, User

from products.docs_freshness.backend.facade.api import accept_pull_request_event, accept_push_event
from products.docs_freshness.backend.facade.contracts import PullRequestHead
from products.docs_freshness.backend.logic.impact_check import docs_agent_origin_key
from products.docs_freshness.backend.temporal import ACTIVITIES, WORKFLOWS
from products.tasks.backend.facade.sandbox import ExecutionResult
from products.tasks.backend.models import Task

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

_MODULE = "products.docs_freshness.backend.logic.impact_check"
_HEAD_SHA = "a" * 40
_MERGE_SHA = "c" * 40
_MERGE_REF = "refs/pull/42/merge"
_HEAD = PullRequestHead(repository="PostHog/posthog", pr_number=42, head_sha=_HEAD_SHA)
_OPEN = {"success": True, "state": "open", "merged": False, "head_sha": _HEAD_SHA, "merge_commit_sha": None}
_SUPERSEDED = {**_OPEN, "head_sha": "b" * 40}
_MERGED = {"success": True, "state": "closed", "merged": True, "head_sha": _HEAD_SHA, "merge_commit_sha": _MERGE_SHA}
_IMPACTED = [{"page": "support/widget.mdx", "kind": "ui-label", "claim": "Secret API Key", "guard": "renamed"}]
_PROMPT = (
    "PR {event.properties.pr_url} at {event.properties.head_sha}\n{event.properties.claims}\n{event.properties.pages}"
)
_PAYLOAD = {
    "action": "synchronize",
    "repository": {"full_name": "PostHog/posthog"},
    "pull_request": {"number": 42, "state": "open", "head": {"sha": _HEAD_SHA}},
}
_PUSH = {
    "ref": "refs/heads/master",
    "deleted": False,
    "repository": {"full_name": "PostHog/posthog"},
    "commits": [{"id": _MERGE_SHA, "message": "feat(insights): rename the key label (#42)\n\nbody"}],
}
_ACCEPT_BY_EVENT_TYPE = {"pull_request": accept_pull_request_event, "push": accept_push_event}
_SYNCHRONIZE_OPEN = ("pull_request", _PAYLOAD, _OPEN)
_SYNCHRONIZE_SUPERSEDED = ("pull_request", _PAYLOAD, _SUPERSEDED)
_SYNCHRONIZE_MERGED = ("pull_request", _PAYLOAD, _MERGED)
_LANDED_PUSH = ("push", _PUSH, _MERGED)


@frozen
class _DocsAgentTask:
    origin_key: str | None
    description: str
    posthog_mcp_scopes: str | list[str]


def _docs_agent_tasks(team_id: int) -> list[_DocsAgentTask]:
    agent_tasks = []
    for task in Task.objects.filter(team_id=team_id).order_by("created_at"):
        latest_run = task.latest_run
        assert latest_run is not None
        agent_tasks.append(
            _DocsAgentTask(
                origin_key=task.origin_key,
                description=task.description,
                posthog_mcp_scopes=latest_run.state["pending_dispatch"]["posthog_mcp_scopes"],
            )
        )
    return agent_tasks


def _sandbox_executor(
    merge_ref_exit_codes: list[int], landed_exit_code: int, checked_refs: list[str]
) -> Callable[..., ExecutionResult]:
    remaining = list(merge_ref_exit_codes)

    def execute(command: str, **_kwargs: Any) -> ExecutionResult:
        if command.startswith("cat "):
            return ExecutionResult(stdout=_PROMPT, stderr="", exit_code=0)
        checked_ref = command.split("sandbox_check.sh ")[1].split()[0]
        checked_refs.append(checked_ref)
        exit_code = landed_exit_code
        if checked_ref == _MERGE_REF:
            exit_code = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return ExecutionResult(stdout=json.dumps(_IMPACTED if exit_code == 1 else []), stderr="", exit_code=exit_code)

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
    "deliveries,merge_ref_exit_codes,landed_exit_code,expected_verdicts,expected_checked_refs,expected_agent_tasks,capture_failures",
    [
        pytest.param([_SYNCHRONIZE_OPEN], [1], 0, ["flagged"], {_MERGE_REF}, 1, 0, id="flagged"),
        pytest.param([_SYNCHRONIZE_OPEN] * 2, [1], 0, ["flagged"], {_MERGE_REF}, 1, 0, id="redelivered"),
        pytest.param(
            [_SYNCHRONIZE_OPEN], [3, 3, 1], 0, ["flagged"], {_MERGE_REF}, 1, 0, id="merge_ref_lags_then_settles"
        ),
        pytest.param([_SYNCHRONIZE_OPEN], [0], 0, ["clear"], {_MERGE_REF}, 0, 0, id="clear"),
        pytest.param([_SYNCHRONIZE_SUPERSEDED], [0], 0, [], set(), 0, 0, id="superseded"),
        pytest.param(
            [_SYNCHRONIZE_OPEN], [4], 0, ["unmergeable"], {_MERGE_REF}, 0, 0, id="unmergeable_after_last_attempt"
        ),
        pytest.param(
            [_SYNCHRONIZE_OPEN], [1], 0, ["flagged"], {_MERGE_REF}, 1, 1, id="capture_fails_after_agent_start"
        ),
        pytest.param(
            [_SYNCHRONIZE_MERGED], [4], 1, ["flagged"], {_MERGE_SHA}, 1, 0, id="merged_before_check_uses_landed_commit"
        ),
        pytest.param([_LANDED_PUSH], [4], 1, ["flagged"], {_MERGE_SHA}, 1, 0, id="landed_push_checks_unchecked_head"),
        pytest.param(
            [_SYNCHRONIZE_OPEN, _LANDED_PUSH], [1], 1, ["flagged"], {_MERGE_REF}, 1, 0, id="landed_push_after_check"
        ),
        pytest.param(
            [_SYNCHRONIZE_OPEN, _LANDED_PUSH],
            [4],
            1,
            ["unmergeable", "flagged"],
            {_MERGE_REF, _MERGE_SHA},
            1,
            0,
            id="unmergeable_then_landed",
        ),
        pytest.param(
            [_SYNCHRONIZE_OPEN, _SYNCHRONIZE_OPEN],
            [4, 4, 4, 4, 4, 4, 1],
            0,
            ["unmergeable", "flagged"],
            {_MERGE_REF},
            1,
            0,
            id="unmergeable_then_merge_ref_appears",
        ),
        pytest.param(
            [("push", {**_PUSH, "ref": "refs/heads/feature"}, _MERGED)], [4], 1, [], set(), 0, 0, id="non_master_push"
        ),
        pytest.param(
            [("push", {**_PUSH, "commits": [{"id": _MERGE_SHA, "message": "Revert a change"}]}, _MERGED)],
            [4],
            1,
            [],
            set(),
            0,
            0,
            id="push_without_pull_request_number",
        ),
        pytest.param(
            [("push", _PUSH, {**_MERGED, "merge_commit_sha": "d" * 40})],
            [4],
            1,
            [],
            set(),
            0,
            0,
            id="push_of_another_pull_requests_commit",
        ),
    ],
)
async def test_verdict_for_head(
    deliveries: list[tuple[str, dict[str, Any], dict[str, Any]]],
    merge_ref_exit_codes: list[int],
    landed_exit_code: int,
    expected_verdicts: list[str],
    expected_checked_refs: set[str],
    expected_agent_tasks: int,
    capture_failures: int,
    owner: User,
    settings: Any,
) -> None:
    team_id = owner.current_team_id
    assert team_id is not None
    settings.DOCS_FRESHNESS_TEAM_ID = team_id
    settings.DOCS_FRESHNESS_OWNER_USER_ID = owner.id
    settings.DOCS_FRESHNESS_TOOL_REF = "main"
    github = MagicMock()
    checked_refs: list[str] = []
    sandbox = MagicMock()
    sandbox.execute.side_effect = _sandbox_executor(merge_ref_exit_codes, landed_exit_code, checked_refs)
    failed_runs = 0
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
                awaited_runs = 0
                for event_type, payload, pull_request in deliveries:
                    github.get_pull_request.return_value = pull_request
                    await sync_to_async(_ACCEPT_BY_EVENT_TYPE[event_type])(payload)
                    while awaited_runs < len(started_handles):
                        try:
                            await started_handles[awaited_runs].result()
                        except WorkflowFailureError:
                            failed_runs += 1
                        awaited_runs += 1

    assert [event["properties"]["verdict"] for event in captured] == expected_verdicts
    assert len({event["uuid"] for event in captured}) == len(captured)
    assert set(checked_refs) == expected_checked_refs
    assert failed_runs == expected_verdicts.count("unmergeable")
    agent_tasks = await sync_to_async(_docs_agent_tasks)(team_id)
    assert len(agent_tasks) == expected_agent_tasks
    if expected_agent_tasks:
        assert agent_tasks[0].origin_key == docs_agent_origin_key(_HEAD)
        assert agent_tasks[0].posthog_mcp_scopes == []
        description = agent_tasks[0].description
        assert "https://github.com/PostHog/posthog/pull/42" in description
        assert '"claim": "Secret API Key"' in description
        assert '["support/widget.mdx"]' in description
        assert "guard" not in description
