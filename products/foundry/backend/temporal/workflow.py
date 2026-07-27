"""The foundry-run-bet workflow: a recursive, fractal-style node tree.

``FoundryNodeWorkflow`` is the recursive unit — the root (started when a managed bet is
funded) and every child it spawns are the *same* workflow type, started with a different
input. A node's command declares child requests via the in-sandbox ``foundry-event`` helper
(see ``constants.py``/``activities.py``); this workflow enforces depth/children/cost caps
before recursing into ``execute_child_workflow`` for each one it allows, and emits
``budget.exceeded`` for any it refuses. Children are awaited sequentially, so by the time a
node's own spawn loop finishes, its entire subtree has completed.

Every BetEvent this workflow needs goes through ``record_bet_event_activity`` — the exact
facade path external orchestrators' POSTs use — so the state machine, BetNode tree, and gate
hook all behave identically whether a bet is external or managed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .constants import RECORD_EVENT_RETRY_POLICY, RECORD_EVENT_TIMEOUT, RUN_NODE_RETRY_POLICY, RUN_NODE_TIMEOUT

with temporalio.workflow.unsafe.imports_passed_through():
    from .activities import RecordEventInput, RunNodeInput, record_bet_event_activity, run_node_activity


@dataclass
class FoundryNodeInput:
    bet_id: str
    team_id: int
    node_id: str
    parent_node_id: str | None
    depth: int
    runner: str
    command: str
    env: dict[str, str] = field(default_factory=dict)
    memory_repo_url: str | None = None
    max_depth: int | None = None
    max_children: int | None = None
    budget_remaining: float | None = None
    # This node's own reserved cost (declared by its parent's spawn request); None for the root.
    own_cost: float | None = None


async def _record(input: FoundryNodeInput, kind: str, payload: dict[str, Any]) -> None:
    await workflow.execute_activity(
        record_bet_event_activity,
        RecordEventInput(bet_id=input.bet_id, team_id=input.team_id, kind=kind, payload=payload),
        start_to_close_timeout=RECORD_EVENT_TIMEOUT,
        retry_policy=RECORD_EVENT_RETRY_POLICY,
    )


@workflow.defn(name="foundry-run-bet")
class FoundryNodeWorkflow(PostHogWorkflow):
    inputs_cls = FoundryNodeInput

    @workflow.run
    async def run(self, input: FoundryNodeInput) -> dict[str, Any]:
        is_root = input.parent_node_id is None
        if is_root:
            await _record(input, "run.started", {})
            await _record(
                input,
                "node.spawned",
                {
                    "node_id": input.node_id,
                    "parent_node_id": None,
                    "runner": input.runner,
                    "depth": input.depth,
                    "max_cost": input.budget_remaining,
                    "max_depth": input.max_depth,
                    "max_children": input.max_children,
                },
            )

        try:
            result = await workflow.execute_activity(
                run_node_activity,
                RunNodeInput(
                    node_id=input.node_id,
                    command=input.command,
                    env=input.env,
                    memory_repo_url=input.memory_repo_url,
                ),
                start_to_close_timeout=RUN_NODE_TIMEOUT,
                retry_policy=RUN_NODE_RETRY_POLICY,
            )
        except Exception as e:
            await _record(
                input, "node.failed", {"node_id": input.node_id, "cost": input.own_cost, "summary": str(e)[:300]}
            )
            if is_root:
                await _record(input, "run.finished", {})
            return {"node_id": input.node_id, "exit_code": -1}

        for note in result.notes:
            await _record(input, "note", {"message": note})
        for knowledge in result.knowledge_events:
            await _record(
                input,
                "knowledge.published",
                {
                    "repo": knowledge.get("repo", ""),
                    "ref": knowledge.get("ref", ""),
                    "path": knowledge.get("path", ""),
                    "title": knowledge.get("title", ""),
                },
            )

        finished_kind = "node.finished" if result.exit_code == 0 else "node.failed"
        await _record(
            input,
            finished_kind,
            {"node_id": input.node_id, "cost": input.own_cost, "summary": f"exit_code={result.exit_code}"},
        )

        children_started = 0
        # Tracks this node's OWN remaining budget as siblings consume it — distinct from
        # input.budget_remaining, which stays fixed (it's what this node itself was allocated).
        budget_remaining = input.budget_remaining
        for idx, spawn_request in enumerate(result.spawn_requests):
            child_node_id = str(spawn_request.get("node_id") or f"{input.node_id}.{idx}")
            cost = float(spawn_request.get("cost") or 1.0)
            child_depth = input.depth + 1

            cap: str | None = None
            detail = ""
            if input.max_depth is not None and child_depth > input.max_depth:
                cap, detail = "max_depth", f"depth {child_depth} exceeds max_depth {input.max_depth}"
            elif input.max_children is not None and children_started >= input.max_children:
                cap, detail = (
                    "max_children",
                    f"node {input.node_id} already spawned {children_started} children (max {input.max_children})",
                )
            elif budget_remaining is not None and cost > budget_remaining:
                cap, detail = "cost", f"child cost {cost} exceeds remaining budget {budget_remaining}"

            if cap is not None:
                await _record(input, "budget.exceeded", {"node_id": child_node_id, "cap": cap, "detail": detail})
                continue

            children_started += 1
            new_budget_remaining = budget_remaining - cost if budget_remaining is not None else None
            budget_remaining = new_budget_remaining
            child_input = FoundryNodeInput(
                bet_id=input.bet_id,
                team_id=input.team_id,
                node_id=child_node_id,
                parent_node_id=input.node_id,
                depth=child_depth,
                runner=str(spawn_request.get("runner") or ""),
                command=str(spawn_request.get("command") or ""),
                env=input.env,
                memory_repo_url=input.memory_repo_url,
                max_depth=input.max_depth,
                max_children=input.max_children,
                budget_remaining=new_budget_remaining,
                own_cost=cost,
            )
            await _record(
                input,
                "node.spawned",
                {
                    "node_id": child_node_id,
                    "parent_node_id": input.node_id,
                    "runner": child_input.runner,
                    "depth": child_depth,
                    "max_cost": new_budget_remaining,
                    "max_depth": input.max_depth,
                    "max_children": input.max_children,
                },
            )
            await workflow.execute_child_workflow(
                FoundryNodeWorkflow.run,
                child_input,
                id=f"foundry-node-{input.bet_id}-{child_node_id}",
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

        if is_root:
            await _record(input, "run.finished", {})
        return {"node_id": input.node_id, "exit_code": result.exit_code}
