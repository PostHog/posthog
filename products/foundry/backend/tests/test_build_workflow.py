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
from products.foundry.backend.facade.enums import BetEventKind, BetState, ExecutionMode
from products.foundry.backend.models import BetEvent
from products.foundry.backend.temporal.activities import record_bet_event_activity, run_node_activity
from products.foundry.backend.temporal.build_activities import check_gate_result_activity, count_gate_results_activity
from products.foundry.backend.temporal.build_workflow import (
    BuildLoopNodeSpec,
    FoundryBuildBetInput,
    FoundryBuildBetWorkflow,
)
from products.foundry.backend.temporal.constants import FOUNDRY_EVENT_PREFIX

_TARGET_REPO_URL = "https://fixture/repo.git"
_GATE_CONFIG = {
    "checks": [{"name": "tests", "check_type": "command", "params": {"command": "pytest"}}],
    "protected_paths": ["tests/acceptance/"],
}
_PASS_RESULT = {
    "pass": True,
    "checks": [{"name": "tests", "type": "command", "pass": True, "required": True}],
    "violations": [],
}


def _artifact_ready_line(ref: str, base_ref: str) -> str:
    payload = {"type": "artifact_ready", "repo_url": _TARGET_REPO_URL, "ref": ref, "base_ref": base_ref}
    return f"{FOUNDRY_EVENT_PREFIX}{json.dumps(payload)}"


def _note_line(message: str) -> str:
    return f"{FOUNDRY_EVENT_PREFIX}{json.dumps({'type': 'note', 'message': message})}"


class _FakeExecResult:
    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


def make_fake_build_sandbox_class(
    stdout_by_node_command: dict[str, str], *, target_clone_ok: bool = True
) -> tuple[type, list[Any]]:
    """A sandbox whose ``execute`` understands the build-loop node protocol (target repo
    clone/checkout, claude CLI install, then the node's own command under ``cd /repo &&``).
    Returns the class and the list of ``SandboxConfig`` every ``create`` call received, so a
    test can assert on the env a specific node (by ``metadata['foundry_node_id']``) ran with.
    """
    created_configs: list[Any] = []

    class _FakeBuildSandbox:
        def __init__(self) -> None:
            self.id = f"fake-build-sandbox-{uuid.uuid4()}"

        @classmethod
        def create(cls, config: Any) -> "_FakeBuildSandbox":
            created_configs.append(config)
            return cls()

        def execute(self, command: str, timeout_seconds: int | None = None) -> _FakeExecResult:
            if command.startswith("git clone"):
                return _FakeExecResult(
                    exit_code=0 if target_clone_ok else 1, stderr="" if target_clone_ok else "clone failed"
                )
            if "npm install -g" in command:
                return _FakeExecResult()
            prefix = "cd /repo && "
            if command.startswith(prefix):
                node_command = command[len(prefix) :]
                if node_command.startswith("git checkout"):
                    return _FakeExecResult()
                return _FakeExecResult(stdout=stdout_by_node_command.get(node_command, ""))
            return _FakeExecResult()

        def write_file(self, path: str, payload: bytes) -> _FakeExecResult:
            return _FakeExecResult()

        def destroy(self) -> None:
            pass

    return _FakeBuildSandbox, created_configs


def make_fake_gate_trigger(outcomes: list[dict[str, Any]]):
    """Stands in for ``execute_foundry_run_gate_workflow``: synchronously records the next
    canned ``gate.result`` outcome instead of actually starting the gauntlet — the gauntlet
    engine itself is already covered by test_gate_workflow.py, this only needs to exercise
    the build loop's OWN reaction to a gate result landing."""
    call_count = {"n": 0}

    def _fake(
        *, bet_id: str, team_id: int, bet_slug: str, created_by_id: int | None, gate_config: dict, artifact: dict
    ) -> None:
        index = min(call_count["n"], len(outcomes) - 1)
        call_count["n"] += 1
        api.record_event(team_id, bet_id, BetEventKind.GATE_RESULT, outcomes[index])

    return _fake, call_count


def _create_bet_in_building(team, user, *, gate_config: dict[str, Any] | None = None):
    bet = api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug=f"build-loop-{uuid.uuid4().hex[:8]}",
            hypothesis="a build-loop bet exercised via the Temporal test environment",
            success_metric={"name": "n/a"},
            guardrails=[],
            budget={},
            exposure_plan={},
            sources=[],
            execution_mode=ExecutionMode.MANAGED,
            gate_config=gate_config if gate_config is not None else _GATE_CONFIG,
        ),
        user=user,
    )
    api.fund_bet(team.id, bet.id, user=user)
    api.record_event(team.id, bet.id, BetEventKind.RUN_STARTED, {}, user=user)
    return bet


def _base_input_kwargs(bet, *, max_gate_iterations: int = 3, with_test_writer: bool = True) -> dict[str, Any]:
    return {
        "bet_slug": bet.slug,
        "hypothesis": bet.hypothesis,
        "success_metric": bet.success_metric,
        "protected_paths": ["tests/acceptance/"],
        "target_repo_url": _TARGET_REPO_URL,
        "target_repo_base_ref": "main",
        "builder": BuildLoopNodeSpec(command="builder-cmd"),
        "max_gate_iterations": max_gate_iterations,
        "test_writer": BuildLoopNodeSpec(command="test-writer-cmd") if with_test_writer else None,
    }


async def _run_build(*, bet_id: str, team_id: int, input_kwargs: dict[str, Any], sandbox_class: type) -> dict:
    with patch(
        "products.foundry.backend.temporal.activities.get_sandbox_class_for_backend", lambda backend: sandbox_class
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.FOUNDRY_TASK_QUEUE,
                workflows=[FoundryBuildBetWorkflow],
                activities=[
                    run_node_activity,
                    record_bet_event_activity,
                    check_gate_result_activity,
                    count_gate_results_activity,
                ],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ):
                return await env.client.execute_workflow(
                    FoundryBuildBetWorkflow.run,
                    FoundryBuildBetInput(bet_id=bet_id, team_id=team_id, **input_kwargs),
                    id=f"foundry-build-test-{uuid.uuid4()}",
                    task_queue=settings.FOUNDRY_TASK_QUEUE,
                )


def _events(bet_id) -> list[BetEvent]:
    return list(BetEvent.objects.filter(bet_id=bet_id).order_by("created_at"))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_happy_path_test_writer_then_builder_gate_passes_first_try(team, user) -> None:
    bet = await sync_to_async(_create_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_build_sandbox_class(
        {
            "test-writer-cmd": _artifact_ready_line("bet/x-tests", "main"),
            "builder-cmd": _artifact_ready_line(f"bet/{bet.slug}", f"bet/{bet.slug}-tests"),
        }
    )
    fake_trigger, _ = make_fake_gate_trigger([_PASS_RESULT])

    with (
        patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
        patch(
            "products.foundry.backend.temporal.gate_client.execute_foundry_run_gate_workflow", side_effect=fake_trigger
        ),
    ):
        result = await _run_build(
            bet_id=str(bet.id), team_id=team.id, input_kwargs=_base_input_kwargs(bet), sandbox_class=sandbox_class
        )

    assert result == {"outcome": "gated", "attempt": 1}
    events = await sync_to_async(_events)(bet.id)
    kinds = [e.kind for e in events]
    assert kinds.count(BetEventKind.ARTIFACT_READY) == 1  # only the builder's, never the test-writer's
    assert kinds.count(BetEventKind.GATE_RESULT) == 1
    assert any(
        "test-writer pushed acceptance tests" in e.payload.get("message", "")
        for e in events
        if e.kind == BetEventKind.NOTE
    )
    bet_state = await sync_to_async(lambda: api.get_bet(team.id, bet.id).state)()
    assert bet_state == BetState.GATED


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_gate_failure_feeds_violations_verbatim_into_the_next_attempts_env(team, user) -> None:
    """Criterion 3: attempt N+1's node env demonstrably contains attempt N's violations."""
    bet = await sync_to_async(_create_bet_in_building)(team, user)
    sandbox_class, created_configs = make_fake_build_sandbox_class(
        {
            "test-writer-cmd": _artifact_ready_line("bet/x-tests", "main"),
            "builder-cmd": _artifact_ready_line(f"bet/{bet.slug}", f"bet/{bet.slug}-tests"),
        }
    )
    fail_violations = [{"code": "tests", "message": "test_checkout failed: AssertionError", "severity": "must_fix"}]
    fake_trigger, _ = make_fake_gate_trigger(
        [{"pass": False, "checks": [], "violations": fail_violations}, _PASS_RESULT]
    )

    with (
        patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
        patch(
            "products.foundry.backend.temporal.gate_client.execute_foundry_run_gate_workflow", side_effect=fake_trigger
        ),
    ):
        result = await _run_build(
            bet_id=str(bet.id), team_id=team.id, input_kwargs=_base_input_kwargs(bet), sandbox_class=sandbox_class
        )

    assert result == {"outcome": "gated", "attempt": 2}
    attempt_2_config = next(c for c in created_configs if c.metadata["foundry_node_id"] == "builder-attempt-2")
    assert json.loads(attempt_2_config.environment_variables["FOUNDRY_GATE_VIOLATIONS"]) == fail_violations
    assert attempt_2_config.environment_variables["FOUNDRY_GATE_ATTEMPT"] == "2"
    attempt_1_config = next(c for c in created_configs if c.metadata["foundry_node_id"] == "builder-attempt-1")
    assert "FOUNDRY_GATE_VIOLATIONS" not in attempt_1_config.environment_variables


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_exhausted_iterations_leaves_bet_building_with_gate_exhausted_outcome(team, user) -> None:
    bet = await sync_to_async(_create_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_build_sandbox_class(
        {
            "test-writer-cmd": _artifact_ready_line("bet/x-tests", "main"),
            "builder-cmd": _artifact_ready_line(f"bet/{bet.slug}", f"bet/{bet.slug}-tests"),
        }
    )
    always_fails = {
        "pass": False,
        "checks": [],
        "violations": [{"code": "tests", "message": "still red", "severity": "must_fix"}],
    }
    fake_trigger, call_count = make_fake_gate_trigger([always_fails])

    with (
        patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
        patch(
            "products.foundry.backend.temporal.gate_client.execute_foundry_run_gate_workflow", side_effect=fake_trigger
        ),
    ):
        result = await _run_build(
            bet_id=str(bet.id),
            team_id=team.id,
            input_kwargs=_base_input_kwargs(bet, max_gate_iterations=2),
            sandbox_class=sandbox_class,
        )

    assert result == {"outcome": "gate_exhausted"}
    assert call_count["n"] >= 2  # both attempts actually reached the gauntlet
    bet_state = await sync_to_async(lambda: api.get_bet(team.id, bet.id).state)()
    assert bet_state == BetState.BUILDING
    events = await sync_to_async(_events)(bet.id)
    run_finished = [e for e in events if e.kind == BetEventKind.RUN_FINISHED]
    assert any(e.payload.get("outcome") == "gate_exhausted" for e in run_finished)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_test_writer_skipped_when_not_configured(team, user) -> None:
    bet = await sync_to_async(_create_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_build_sandbox_class({"builder-cmd": _artifact_ready_line(f"bet/{bet.slug}", "main")})
    fake_trigger, _ = make_fake_gate_trigger([_PASS_RESULT])

    with (
        patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
        patch(
            "products.foundry.backend.temporal.gate_client.execute_foundry_run_gate_workflow", side_effect=fake_trigger
        ),
    ):
        result = await _run_build(
            bet_id=str(bet.id),
            team_id=team.id,
            input_kwargs=_base_input_kwargs(bet, with_test_writer=False),
            sandbox_class=sandbox_class,
        )

    assert result == {"outcome": "gated", "attempt": 1}
    events = await sync_to_async(_events)(bet.id)
    node_spawned_ids = {e.payload["node_id"] for e in events if e.kind == BetEventKind.NODE_SPAWNED}
    assert node_spawned_ids == {"builder-attempt-1"}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_env_secret_is_redacted_even_when_the_agent_echoes_it(team, user) -> None:
    """ADR-5 decision 5's round-trip test: an allowlisted env secret must never appear in
    any persisted BetEvent, even if the node's own command echoes it into a note."""
    bet = await sync_to_async(_create_bet_in_building)(team, user)
    secret = "sk-ant-api03-FAKESECRETVALUE1234567890ABCDEF"
    leaky_builder_stdout = "\n".join(
        [_note_line(f"debug: using key {secret}"), _artifact_ready_line(f"bet/{bet.slug}", "main")]
    )
    sandbox_class, _ = make_fake_build_sandbox_class({"builder-cmd": leaky_builder_stdout})
    fake_trigger, _ = make_fake_gate_trigger([_PASS_RESULT])

    kwargs = _base_input_kwargs(bet, with_test_writer=False)
    kwargs["builder"] = BuildLoopNodeSpec(command="builder-cmd", env={"ANTHROPIC_API_KEY": secret})

    with (
        patch("products.foundry.backend.logic.gate.reviewhog_gate_enabled", return_value=True),
        patch(
            "products.foundry.backend.temporal.gate_client.execute_foundry_run_gate_workflow", side_effect=fake_trigger
        ),
    ):
        await _run_build(bet_id=str(bet.id), team_id=team.id, input_kwargs=kwargs, sandbox_class=sandbox_class)

    events = await sync_to_async(_events)(bet.id)
    assert not any(secret in json.dumps(e.payload) for e in events)
    leaked_note = next(
        e for e in events if e.kind == BetEventKind.NOTE and "debug: using key" in e.payload.get("message", "")
    )
    assert "<redacted>" in leaked_note.payload["message"]
