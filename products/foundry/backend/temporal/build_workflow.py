"""The foundry-build-bet workflow: a real coding agent, gated by the gauntlet it can't touch.

Sibling to ``foundry-run-bet`` (``workflow.py``), not a caller of it — the recursive,
arbitrary-fan-out node tree there doesn't fit this workflow's fixed two-role choreography
(an optional test-writer, then a bounded builder-retry loop), and both share the same
underlying node primitive (``run_node_activity``) directly rather than through
``FoundryNodeWorkflow``. Started instead of ``foundry-run-bet`` when a managed bet's
``run_config.build_loop`` is set (see ``logic/__init__.py::_start_managed_run``); a bet
without ``build_loop`` is completely unaffected by anything in this module.

Branch/ref convention (see STATUS.md for the reasoning): the test-writer, if configured,
clones ``target_repo@base_ref`` and pushes its acceptance tests to an immutable baseline
branch ``bet/<slug>-tests`` — never touched again. Every builder attempt starts fresh from
that baseline (not from a previous attempt's commits, so a broken attempt never compounds)
and force-pushes ``bet/<slug>``. The builder's own ``artifact.ready`` sets ``base_ref`` to
that baseline, so the gauntlet's diff is the builder's changes only — the test-writer's
own commit never shows up in a ``protected_paths`` violation it didn't cause.

Foundry does the mechanical git checkout (``run_node_activity``'s ``target_repo_url``/
``target_repo_ref``, extending the existing memory-repo-clone pattern) and installs the
Claude Code CLI at sandbox-startup time (``install_claude_cli=True`` — ``SLIM_BASE``
already ships git+node+uv; a dedicated image layer would also need mirroring in
``modal_sandbox.py``'s production Image definition, deferred as a documented v1 tradeoff).
The agent itself (prompt templates in ``.agents/skills/bet/references/``) does its own
git commit/push and reports back via the existing ``foundry-event`` mechanism — no new
agent-facing protocol, just the iteration-4 ``artifact_ready`` convention plus a handful of
``FOUNDRY_*`` env vars carrying the bet spec, so the shipped prompts stay generic across
bets rather than needing per-bet text substitution (and never need bet text — hypothesis,
success metric — interpolated into a shell command at all).

Gate feedback loops through env, not command templating: a builder retry gets
``FOUNDRY_GATE_VIOLATIONS`` (JSON) and ``FOUNDRY_GATE_ATTEMPT`` merged into its env.

This workflow never calls the gate engine itself — ``artifact.ready`` still triggers
``foundry-run-gate`` exactly the way ``logic/gate.py`` already does for any bet. It only
polls (short activity + ``workflow.sleep``, restart-safe against the dev-stack nodemon's
~25s worker-restart gap — never one long-running activity call) for the resulting
``gate.result``, tolerating the known double-gate.result quirk by construction: each
attempt takes a baseline count of this bet's gate.result events right before its node
runs, and only ever looks at ones past that baseline (position-based, not wall-clock —
sidesteps comparing Temporal's workflow clock against Django's real ``created_at``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import temporalio.workflow
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from .constants import RECORD_EVENT_RETRY_POLICY, RECORD_EVENT_TIMEOUT

with temporalio.workflow.unsafe.imports_passed_through():
    from .activities import RecordEventInput, RunNodeInput, RunNodeOutput, record_bet_event_activity, run_node_activity
    from .build_activities import (
        CheckGateResultInput,
        CountGateResultsInput,
        GateResultSnapshot,
        check_gate_result_activity,
        count_gate_results_activity,
    )

# A real coding-agent run takes far longer than a scripted demo command; the sandbox-exec
# timeout leaves a few minutes of slack under the activity's own start_to_close_timeout for
# the target-repo clone/checkout, the claude CLI install, and sandbox teardown.
BUILD_NODE_ACTIVITY_TIMEOUT = timedelta(minutes=30)
BUILD_NODE_COMMAND_TIMEOUT_SECONDS = int((BUILD_NODE_ACTIVITY_TIMEOUT - timedelta(minutes=5)).total_seconds())
BUILD_NODE_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

GATE_POLL_INTERVAL = timedelta(seconds=10)
GATE_POLL_MAX_ATTEMPTS = (
    180  # 30 minutes total — matches the gauntlet's own worst-case (coverage + mutation + reviewhog).
)
CHECK_GATE_RESULT_TIMEOUT = timedelta(seconds=30)
CHECK_GATE_RESULT_RETRY_POLICY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
COUNT_GATE_RESULTS_TIMEOUT = timedelta(seconds=30)
COUNT_GATE_RESULTS_RETRY_POLICY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))


@dataclass
class BuildLoopNodeSpec:
    command: str
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class FoundryBuildBetInput:
    bet_id: str
    team_id: int
    bet_slug: str
    hypothesis: str
    success_metric: dict[str, Any]
    protected_paths: list[str]
    target_repo_url: str
    target_repo_base_ref: str
    builder: BuildLoopNodeSpec
    max_gate_iterations: int
    memory_repo_url: str | None = None
    test_writer: BuildLoopNodeSpec | None = None


def _work_branch(bet_slug: str) -> str:
    return f"bet/{bet_slug}"


def _tests_branch(bet_slug: str) -> str:
    return f"bet/{bet_slug}-tests"


async def _record(bet_id: str, team_id: int, kind: str, payload: dict[str, Any]) -> None:
    await workflow.execute_activity(
        record_bet_event_activity,
        RecordEventInput(bet_id=bet_id, team_id=team_id, kind=kind, payload=payload),
        start_to_close_timeout=RECORD_EVENT_TIMEOUT,
        retry_policy=RECORD_EVENT_RETRY_POLICY,
    )


def _base_env(input: FoundryBuildBetInput) -> dict[str, str]:
    return {
        "FOUNDRY_BET_SLUG": input.bet_slug,
        "FOUNDRY_HYPOTHESIS": input.hypothesis,
        "FOUNDRY_SUCCESS_METRIC": json.dumps(input.success_metric),
        "FOUNDRY_PROTECTED_PATHS": json.dumps(input.protected_paths),
        "FOUNDRY_FLAG_KEY": f"bet-{input.bet_slug}",
        "FOUNDRY_TARGET_REPO_URL": input.target_repo_url,
        "FOUNDRY_TARGET_BASE_REF": input.target_repo_base_ref,
    }


async def _run_build_node(
    *,
    input: FoundryBuildBetInput,
    node_id: str,
    node_spec: BuildLoopNodeSpec,
    target_repo_ref: str,
    extra_env: dict[str, str],
    emit_artifact_ready: bool,
) -> RunNodeOutput:
    """Run one test-writer/builder node and record its lifecycle as BetEvents.

    ``emit_artifact_ready`` gates whether a reported ``artifact_ready`` foundry-event
    becomes a real ``artifact.ready`` BetEvent (the builder, which is meant to trigger the
    gauntlet) or a plain ``note`` (the test-writer, whose own tests-only diff must never be
    gated — see the module docstring's branch convention).
    """
    env = {**node_spec.env, **_base_env(input), **extra_env}
    await _record(
        input.bet_id,
        input.team_id,
        "node.spawned",
        {"node_id": node_id, "parent_node_id": None, "runner": node_id, "depth": 0},
    )

    result = await workflow.execute_activity(
        run_node_activity,
        RunNodeInput(
            node_id=node_id,
            command=node_spec.command,
            env=env,
            memory_repo_url=input.memory_repo_url,
            target_repo_url=input.target_repo_url,
            target_repo_ref=target_repo_ref,
            install_claude_cli=True,
            command_timeout_seconds=BUILD_NODE_COMMAND_TIMEOUT_SECONDS,
        ),
        start_to_close_timeout=BUILD_NODE_ACTIVITY_TIMEOUT,
        retry_policy=BUILD_NODE_RETRY_POLICY,
    )

    for note in result.notes:
        await _record(input.bet_id, input.team_id, "note", {"message": note})
    for knowledge in result.knowledge_events:
        await _record(
            input.bet_id,
            input.team_id,
            "knowledge.published",
            {
                "repo": knowledge.get("repo", ""),
                "ref": knowledge.get("ref", ""),
                "path": knowledge.get("path", ""),
                "title": knowledge.get("title", ""),
            },
        )
    for artifact in result.artifact_ready_events:
        payload = {
            "repo_url": artifact.get("repo_url", ""),
            "ref": artifact.get("ref", ""),
            "base_ref": artifact.get("base_ref", ""),
            "pr_url": artifact.get("pr_url"),
        }
        if emit_artifact_ready:
            await _record(input.bet_id, input.team_id, "artifact.ready", payload)
        else:
            await _record(
                input.bet_id,
                input.team_id,
                "note",
                {"message": f"test-writer provenance: {payload['repo_url']}@{payload['ref']}"},
            )

    finished_kind = "node.finished" if result.exit_code == 0 else "node.failed"
    await _record(
        input.bet_id, input.team_id, finished_kind, {"node_id": node_id, "summary": f"exit_code={result.exit_code}"}
    )
    return result


async def _count_gate_results(input: FoundryBuildBetInput) -> int:
    return await workflow.execute_activity(
        count_gate_results_activity,
        CountGateResultsInput(bet_id=input.bet_id, team_id=input.team_id),
        start_to_close_timeout=COUNT_GATE_RESULTS_TIMEOUT,
        retry_policy=COUNT_GATE_RESULTS_RETRY_POLICY,
    )


async def _await_gate_result(input: FoundryBuildBetInput, *, known_count: int) -> GateResultSnapshot | None:
    for _ in range(GATE_POLL_MAX_ATTEMPTS):
        snapshot = await workflow.execute_activity(
            check_gate_result_activity,
            CheckGateResultInput(bet_id=input.bet_id, team_id=input.team_id, known_count=known_count),
            start_to_close_timeout=CHECK_GATE_RESULT_TIMEOUT,
            retry_policy=CHECK_GATE_RESULT_RETRY_POLICY,
        )
        if snapshot is not None:
            return snapshot
        await workflow.sleep(GATE_POLL_INTERVAL)
    return None


@workflow.defn(name="foundry-build-bet")
class FoundryBuildBetWorkflow(PostHogWorkflow):
    inputs_cls = FoundryBuildBetInput

    @workflow.run
    async def run(self, input: FoundryBuildBetInput) -> dict[str, Any]:
        await _record(input.bet_id, input.team_id, "run.started", {})

        tests_ref = input.target_repo_base_ref
        if input.test_writer is not None:
            test_writer_result = await _run_build_node(
                input=input,
                node_id="test-writer",
                node_spec=input.test_writer,
                target_repo_ref=input.target_repo_base_ref,
                extra_env={"FOUNDRY_WORK_BRANCH": _tests_branch(input.bet_slug)},
                emit_artifact_ready=False,
            )
            if test_writer_result.exit_code != 0:
                await _record(input.bet_id, input.team_id, "run.finished", {"outcome": "test_writer_failed"})
                return {"outcome": "test_writer_failed"}
            tests_ref = _tests_branch(input.bet_slug)
            # Branch name only, never the repo URL: target_repo_url is typically tokened
            # (the same convention as memory_repo_url), and unlike that field this note is
            # gratuitous — it doesn't need the credential to serve its purpose.
            await _record(
                input.bet_id,
                input.team_id,
                "note",
                {"message": f"test-writer pushed acceptance tests to {tests_ref}"},
            )

        violations: list[dict[str, Any]] = []
        for attempt in range(1, input.max_gate_iterations + 1):
            await _record(
                input.bet_id,
                input.team_id,
                "note",
                {"message": f"builder: gate attempt {attempt}/{input.max_gate_iterations}"},
            )
            extra_env = {
                "FOUNDRY_WORK_BRANCH": _work_branch(input.bet_slug),
                "FOUNDRY_GATE_BASE_REF": tests_ref,
                "FOUNDRY_GATE_ATTEMPT": str(attempt),
            }
            if violations:
                extra_env["FOUNDRY_GATE_VIOLATIONS"] = json.dumps(violations)

            known_count = await _count_gate_results(input)
            builder_result = await _run_build_node(
                input=input,
                node_id=f"builder-attempt-{attempt}",
                node_spec=input.builder,
                target_repo_ref=tests_ref,
                extra_env=extra_env,
                emit_artifact_ready=True,
            )

            if builder_result.exit_code != 0 or not builder_result.artifact_ready_events:
                violations = [
                    {
                        "code": "builder_node",
                        "message": (
                            f"builder attempt {attempt} produced no artifact (exit_code={builder_result.exit_code})"
                        ),
                        "severity": "must_fix",
                    }
                ]
                continue

            gate_result = await _await_gate_result(input, known_count=known_count)
            if gate_result is None:
                violations = [
                    {
                        "code": "gate_timeout",
                        "message": "the gauntlet did not report a result in time",
                        "severity": "must_fix",
                    }
                ]
                continue
            if gate_result.passed:
                return {"outcome": "gated", "attempt": attempt}
            violations = gate_result.violations

        await _record(input.bet_id, input.team_id, "run.finished", {"outcome": "gate_exhausted"})
        await _record(
            input.bet_id,
            input.team_id,
            "note",
            {"message": f"builder exhausted {input.max_gate_iterations} gate attempt(s) without passing"},
        )
        return {"outcome": "gate_exhausted"}
