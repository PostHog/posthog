import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from unittest.mock import patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.foundry.backend.facade import api
from products.foundry.backend.facade.contracts import CreateBetInput
from products.foundry.backend.facade.enums import BetEventKind, ExecutionMode
from products.foundry.backend.models import BetEvent, BetNode
from products.foundry.backend.temporal.activities import record_bet_event_activity, run_node_activity
from products.foundry.backend.temporal.constants import FOUNDRY_EVENT_PREFIX
from products.foundry.backend.temporal.workflow import FoundryNodeInput, FoundryNodeWorkflow


def _spawn_line(node_id: str, command: str, cost: float = 1.0) -> str:
    payload = {"type": "spawn_child", "node_id": node_id, "command": command, "runner": "test-runner", "cost": cost}
    return f"{FOUNDRY_EVENT_PREFIX}{json.dumps(payload)}"


def _knowledge_line(title: str) -> str:
    payload = {
        "type": "knowledge_published",
        "repo": "file:///memory-repo",
        "ref": "abc123",
        "path": "notes.md",
        "title": title,
    }
    return f"{FOUNDRY_EVENT_PREFIX}{json.dumps(payload)}"


class _FakeExecResult:
    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


def make_fake_sandbox_class(stdout_by_command: dict[str, str], clone_exit_code: int = 0) -> type:
    """A sandbox whose ``execute`` returns scripted stdout keyed by exact command string.

    Unmatched commands (the helper chmod) succeed with empty output; a ``git clone`` command
    returns ``clone_exit_code`` so a test can exercise the memory-repo-unreachable path.
    """

    class _FakeSandbox:
        instances: list[Any] = []

        def __init__(self) -> None:
            self.id = f"fake-sandbox-{uuid.uuid4()}"
            type(self).instances.append(self)

        @classmethod
        def create(cls, config: Any) -> "_FakeSandbox":
            return cls()

        def execute(self, command: str, timeout_seconds: int | None = None) -> _FakeExecResult:
            if command.startswith("git clone"):
                return _FakeExecResult(exit_code=clone_exit_code, stderr="clone failed" if clone_exit_code else "")
            return _FakeExecResult(stdout=stdout_by_command.get(command, ""))

        def write_file(self, path: str, payload: bytes) -> _FakeExecResult:
            return _FakeExecResult()

        def destroy(self) -> None:
            pass

    return _FakeSandbox


async def _run_root(*, bet_id: str, team_id: int, command: str, sandbox_class: type, **caps: Any) -> None:
    with patch(
        "products.foundry.backend.temporal.activities.get_sandbox_class_for_backend", lambda backend: sandbox_class
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.FOUNDRY_TASK_QUEUE,
                workflows=[FoundryNodeWorkflow],
                activities=[run_node_activity, record_bet_event_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ):
                await env.client.execute_workflow(
                    FoundryNodeWorkflow.run,
                    FoundryNodeInput(
                        bet_id=bet_id,
                        team_id=team_id,
                        node_id="root",
                        parent_node_id=None,
                        depth=0,
                        runner="test-runner",
                        command=command,
                        **caps,
                    ),
                    id=f"foundry-node-{bet_id}-root",
                    task_queue=settings.FOUNDRY_TASK_QUEUE,
                )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_recursive_spawn_builds_matching_bet_node_tree(team) -> None:
    """Root -> 2 children -> 1 grandchild, driven end-to-end through real child workflows."""
    bet = await sync_to_async(_create_managed_bet)(team)
    stdout_by_command = {
        "root-cmd": "\n".join([_spawn_line("root.0", "child-a-cmd"), _spawn_line("root.1", "child-b-cmd")]),
        "child-b-cmd": _spawn_line("root.1.0", "grandchild-cmd"),
        "grandchild-cmd": _knowledge_line("insight from the grandchild"),
    }
    sandbox_class = make_fake_sandbox_class(stdout_by_command)

    await _run_root(bet_id=str(bet.id), team_id=team.id, command="root-cmd", sandbox_class=sandbox_class)

    nodes = await sync_to_async(lambda: {n.node_id: n for n in BetNode.objects.filter(bet_id=bet.id)})()
    assert set(nodes) == {"root", "root.0", "root.1", "root.1.0"}
    assert nodes["root"].parent_id is None and nodes["root"].depth == 0
    assert nodes["root.0"].parent_id == nodes["root"].id and nodes["root.0"].depth == 1
    assert nodes["root.1"].parent_id == nodes["root"].id and nodes["root.1"].depth == 1
    assert nodes["root.1.0"].parent_id == nodes["root.1"].id and nodes["root.1.0"].depth == 2
    assert all(n.status == "finished" for n in nodes.values())

    kinds = await sync_to_async(lambda: list(BetEvent.objects.filter(bet_id=bet.id).values_list("kind", flat=True)))()
    assert kinds.count(BetEventKind.RUN_STARTED) == 1
    assert kinds.count(BetEventKind.RUN_FINISHED) == 1
    assert kinds.count(BetEventKind.NODE_SPAWNED) == 4
    assert kinds.count(BetEventKind.NODE_FINISHED) == 4
    assert kinds.count(BetEventKind.KNOWLEDGE_PUBLISHED) == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_memory_repo_clone_failure_degrades_gracefully(team) -> None:
    """An unreachable memory_repo_url must not fail the run — just leave a note."""
    bet = await sync_to_async(_create_managed_bet)(team)
    sandbox_class = make_fake_sandbox_class({"root-cmd": ""}, clone_exit_code=1)

    await _run_root(
        bet_id=str(bet.id),
        team_id=team.id,
        command="root-cmd",
        sandbox_class=sandbox_class,
        memory_repo_url="file:///unreachable-memory-repo",
    )

    kinds = await sync_to_async(lambda: list(BetEvent.objects.filter(bet_id=bet.id).values_list("kind", flat=True)))()
    assert BetEventKind.RUN_FINISHED in kinds
    note_payloads = await sync_to_async(
        lambda: list(BetEvent.objects.filter(bet_id=bet.id, kind=BetEventKind.NOTE).values_list("payload", flat=True))
    )()
    assert any("memory repo unreachable" in p.get("message", "") for p in note_payloads)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "caps,expected_children,expected_cap,expected_budget_events",
    [
        # max_depth rejects BOTH requested children (root.0 and root.1 both land at depth 1 > 0).
        ({"max_depth": 0, "max_children": None, "budget_remaining": None}, 0, "max_depth", 2),
        # max_children allows the first, rejects the second.
        ({"max_depth": None, "max_children": 1, "budget_remaining": None}, 1, "max_children", 1),
        # A cost-1 budget covers the first child (cost 1.0) but not the second.
        ({"max_depth": None, "max_children": None, "budget_remaining": 1.0}, 1, "cost", 1),
    ],
)
async def test_cap_violation_cancels_subtree_and_emits_budget_exceeded(
    team, caps: dict, expected_children: int, expected_cap: str, expected_budget_events: int
) -> None:
    bet = await sync_to_async(_create_managed_bet)(team)
    stdout_by_command = {
        "root-cmd": "\n".join(
            [_spawn_line("root.0", "child-a-cmd", cost=1.0), _spawn_line("root.1", "child-b-cmd", cost=1.0)]
        )
    }
    sandbox_class = make_fake_sandbox_class(stdout_by_command)

    await _run_root(bet_id=str(bet.id), team_id=team.id, command="root-cmd", sandbox_class=sandbox_class, **caps)

    children = await sync_to_async(lambda: list(BetNode.objects.filter(bet_id=bet.id).exclude(node_id="root")))()
    assert len(children) == expected_children

    budget_events = await sync_to_async(
        lambda: list(
            BetEvent.objects.filter(bet_id=bet.id, kind=BetEventKind.BUDGET_EXCEEDED).values_list("payload", flat=True)
        )
    )()
    assert len(budget_events) == expected_budget_events
    assert all(e["cap"] == expected_cap for e in budget_events)


def _create_managed_bet(team):
    return api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug=f"managed-bet-{uuid.uuid4().hex[:8]}",
            hypothesis="A managed bet exercised via the Temporal test environment",
            success_metric={"name": "n/a"},
            guardrails=[],
            budget={},
            exposure_plan={},
            sources=[],
            execution_mode=ExecutionMode.MANAGED,
        )
    )
