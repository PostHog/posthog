import uuid
from collections.abc import Callable
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
from products.foundry.backend.facade.enums import BetEventKind
from products.foundry.backend.models import BetEvent
from products.foundry.backend.temporal.activities import record_bet_event_activity
from products.foundry.backend.temporal.gate_activities import (
    provision_gate_sandbox_activity,
    run_command_check_activity,
    run_coverage_check_activity,
    run_flag_guard_check_activity,
    run_mutation_check_activity,
    run_protected_paths_check_activity,
    run_reviewhog_check_activity,
    teardown_gate_sandbox_activity,
)
from products.foundry.backend.temporal.gate_workflow import FoundryGateWorkflow, GateRunInput
from products.review_hog.backend.facade.contracts import ReviewReportStatus, ReviewViolation, TriggerReviewResult

_DIFF = (
    "diff --git a/tests/acceptance/test_checkout.py b/tests/acceptance/test_checkout.py\n"
    "--- a/tests/acceptance/test_checkout.py\n+++ b/tests/acceptance/test_checkout.py\n"
    "@@ -1,1 +1,2 @@\n line1\n+assert True\n"
)
_DIFF_SRC_ONLY = (
    "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1,1 +1,2 @@\n line1\n+added_line\n"
)


class _FakeExecResult:
    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


def make_fake_gate_sandbox_class(
    *,
    diff_text: str = _DIFF_SRC_ONLY,
    file_contents: dict[str, str] | None = None,
    exit_codes: dict[str, int] | None = None,
    crash_on: str | None = None,
    clone_ok: bool = True,
) -> tuple[type, list[tuple[str, int | None]]]:
    """A sandbox whose ``execute`` understands the gate engine's own command shapes (git
    clone / checkout+diff / cat <report>) plus test-supplied overrides for check commands.
    Returns the class and the list every ``execute`` call (command, timeout_seconds) lands in,
    so a test can assert on what the gate engine actually asked the sandbox to run."""
    resolved_file_contents: dict[str, str] = file_contents or {}
    resolved_exit_codes: dict[str, int] = exit_codes or {}
    execute_calls: list[tuple[str, int | None]] = []

    class _FakeGateSandbox:
        _by_id: dict[str, "_FakeGateSandbox"] = {}

        def __init__(self) -> None:
            self.id = f"fake-gate-sandbox-{uuid.uuid4()}"
            _FakeGateSandbox._by_id[self.id] = self

        @classmethod
        def create(cls, config: Any) -> "_FakeGateSandbox":
            return cls()

        @staticmethod
        def get_by_id(sandbox_id: str) -> "_FakeGateSandbox":
            return _FakeGateSandbox._by_id[sandbox_id]

        def execute(self, command: str, timeout_seconds: int | None = None) -> _FakeExecResult:
            execute_calls.append((command, timeout_seconds))
            if crash_on and crash_on in command:
                raise RuntimeError(f"simulated sandbox crash for: {command[:80]}")
            if "git clone" in command:
                return _FakeExecResult(exit_code=0 if clone_ok else 1, stderr="" if clone_ok else "clone failed")
            if "git diff" in command:
                return _FakeExecResult(stdout=diff_text)
            if command.startswith("cat "):
                for suffix, content in resolved_file_contents.items():
                    if command.endswith(suffix):
                        return _FakeExecResult(stdout=content)
                return _FakeExecResult(exit_code=1, stderr="no such file")
            for substr, exit_code in resolved_exit_codes.items():
                if substr in command:
                    return _FakeExecResult(exit_code=exit_code, stderr="failed" if exit_code else "")
            return _FakeExecResult(exit_code=0)

        def destroy(self) -> None:
            pass

    return _FakeGateSandbox, execute_calls


def _bet_in_building(team, user):
    bet = api.create_bet(
        CreateBetInput(
            team_id=team.id,
            slug=f"gate-workflow-test-{uuid.uuid4().hex[:8]}",
            hypothesis="the gauntlet runs against a real artifact diff",
            success_metric={"name": "n/a"},
            guardrails=[],
            budget={},
            exposure_plan={},
            sources=[],
        ),
        user=user,
    )
    api.fund_bet(team.id, bet.id, user=user)
    api.record_event(team.id, bet.id, BetEventKind.RUN_STARTED, {}, user=user)
    return bet


ACTIVITIES: list[Callable[..., Any]] = [
    record_bet_event_activity,
    provision_gate_sandbox_activity,
    teardown_gate_sandbox_activity,
    run_command_check_activity,
    run_coverage_check_activity,
    run_mutation_check_activity,
    run_protected_paths_check_activity,
    run_flag_guard_check_activity,
    run_reviewhog_check_activity,
]


async def _run_gate(
    *, bet, team, user, gate_config: dict[str, Any], artifact: dict[str, Any], sandbox_class: type
) -> dict:
    with patch(
        "products.foundry.backend.temporal.gate_activities.get_sandbox_class_for_backend", lambda backend: sandbox_class
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.FOUNDRY_TASK_QUEUE,
                workflows=[FoundryGateWorkflow],
                activities=ACTIVITIES,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ):
                return await env.client.execute_workflow(
                    FoundryGateWorkflow.run,
                    GateRunInput(
                        bet_id=str(bet.id),
                        team_id=team.id,
                        bet_slug=bet.slug,
                        created_by_id=user.id,
                        gate_config=gate_config,
                        artifact=artifact,
                    ),
                    id=f"foundry-gate-test-{uuid.uuid4()}",
                    task_queue=settings.FOUNDRY_TASK_QUEUE,
                )


def _gate_result_payload(bet_id) -> dict:
    event = BetEvent.objects.get(bet_id=bet_id, kind=BetEventKind.GATE_RESULT)
    return event.payload


def _checks_by_name(payload: dict) -> dict[str, dict]:
    return {c["name"]: c for c in payload["checks"]}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_all_required_checks_pass_gate_passes(team, user) -> None:
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_gate_sandbox_class(exit_codes={"pytest": 0})
    gate_config = {"checks": [{"name": "tests", "check_type": "command", "params": {"command": "pytest"}}]}

    result = await _run_gate(
        bet=bet,
        team=team,
        user=user,
        gate_config=gate_config,
        artifact={"repo_url": "file:///fixture-repo", "ref": "builder-branch", "base_ref": "main"},
        sandbox_class=sandbox_class,
    )

    assert result["pass"] is True
    payload = await sync_to_async(_gate_result_payload)(bet.id)
    assert payload["pass"] is True
    assert _checks_by_name(payload)["tests"]["pass"] is True
    assert payload["violations"] == []


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_one_required_check_fails_gate_fails_with_named_violation(team, user) -> None:
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_gate_sandbox_class(exit_codes={"pytest": 1})
    gate_config = {"checks": [{"name": "tests", "check_type": "command", "params": {"command": "pytest"}}]}

    result = await _run_gate(
        bet=bet,
        team=team,
        user=user,
        gate_config=gate_config,
        artifact={"repo_url": "file:///fixture-repo", "ref": "builder-branch", "base_ref": "main"},
        sandbox_class=sandbox_class,
    )

    assert result["pass"] is False
    payload = await sync_to_async(_gate_result_payload)(bet.id)
    assert _checks_by_name(payload)["tests"]["pass"] is False
    assert any(v["code"] == "tests" and v["severity"] == "must_fix" for v in payload["violations"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_optional_check_failure_is_recorded_but_does_not_block(team, user) -> None:
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_gate_sandbox_class(exit_codes={"pytest": 0, "lint": 1})
    gate_config = {
        "checks": [
            {"name": "tests", "check_type": "command", "params": {"command": "pytest"}},
            {"name": "lint", "check_type": "command", "required": False, "params": {"command": "lint"}},
        ]
    }

    result = await _run_gate(
        bet=bet,
        team=team,
        user=user,
        gate_config=gate_config,
        artifact={"repo_url": "file:///fixture-repo", "ref": "builder-branch", "base_ref": "main"},
        sandbox_class=sandbox_class,
    )

    assert result["pass"] is True
    payload = await sync_to_async(_gate_result_payload)(bet.id)
    checks = _checks_by_name(payload)
    assert checks["lint"]["pass"] is False
    assert checks["lint"]["required"] is False
    assert any(v["code"] == "lint" and v["severity"] == "advisory" for v in payload["violations"])


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_check_crash_fails_the_check_and_never_hangs_the_workflow(team, user) -> None:
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_gate_sandbox_class(crash_on="boom")
    gate_config = {"checks": [{"name": "tests", "check_type": "command", "params": {"command": "boom"}}]}

    result = await _run_gate(
        bet=bet,
        team=team,
        user=user,
        gate_config=gate_config,
        artifact={"repo_url": "file:///fixture-repo", "ref": "builder-branch", "base_ref": "main"},
        sandbox_class=sandbox_class,
    )

    assert result["pass"] is False
    payload = await sync_to_async(_gate_result_payload)(bet.id)
    assert "crashed" in _checks_by_name(payload)["tests"]["details"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_mutation_check_threads_max_minutes_through_as_the_sandbox_timeout(team, user) -> None:
    """The sandbox's own execute() timeout is the mutation check's time-box (see
    gate_activities.py) — if a refactor drops or hardcodes it, this catches it directly
    rather than trusting that the check merely "finished in time" in a fake environment
    that can't actually enforce wall-clock time."""
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, execute_calls = make_fake_gate_sandbox_class(
        file_contents={"mutants/mutmut-cicd-stats.json": '{"killed": 1, "survived": 0, "total": 1}'}
    )
    gate_config = {
        "checks": [{"name": "mutation", "check_type": "mutation", "params": {"min_score_pct": 50, "max_minutes": 3}}]
    }

    await _run_gate(
        bet=bet,
        team=team,
        user=user,
        gate_config=gate_config,
        artifact={"repo_url": "file:///fixture-repo", "ref": "builder-branch", "base_ref": "main"},
        sandbox_class=sandbox_class,
    )

    mutation_calls = [tc for tc in execute_calls if "mutmut" in tc[0]]
    assert mutation_calls and mutation_calls[0][1] == 3 * 60


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_protected_paths_violation_names_the_touched_path(team, user) -> None:
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_gate_sandbox_class(diff_text=_DIFF)  # touches tests/acceptance/test_checkout.py

    result = await _run_gate(
        bet=bet,
        team=team,
        user=user,
        gate_config={"protected_paths": ["tests/acceptance/"]},
        artifact={"repo_url": "file:///fixture-repo", "ref": "builder-branch", "base_ref": "main"},
        sandbox_class=sandbox_class,
    )

    assert result["pass"] is False
    payload = await sync_to_async(_gate_result_payload)(bet.id)
    protected = _checks_by_name(payload)["protected_paths"]
    assert protected["pass"] is False
    assert "tests/acceptance/test_checkout.py" in protected["details"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_flag_guard_catches_unguarded_change_and_passes_a_guarded_one(team, user) -> None:
    bet = await sync_to_async(_bet_in_building)(team, user)
    guarded_diff = (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -1,1 +1,2 @@\n line1\n+if flags.get('bet-my-slug'): pass\n"
    )

    unguarded_sandbox, _ = make_fake_gate_sandbox_class(diff_text=_DIFF_SRC_ONLY)
    guarded_sandbox, _ = make_fake_gate_sandbox_class(diff_text=guarded_diff)
    gate_config = {
        "checks": [{"name": "flag_guard", "check_type": "flag_guard", "params": {"flag_key": "bet-my-slug"}}]
    }
    artifact = {"repo_url": "file:///fixture-repo", "ref": "builder-branch", "base_ref": "main"}

    unguarded_result = await _run_gate(
        bet=bet, team=team, user=user, gate_config=gate_config, artifact=artifact, sandbox_class=unguarded_sandbox
    )
    assert unguarded_result["pass"] is False

    bet2 = await sync_to_async(_bet_in_building)(team, user)
    guarded_result = await _run_gate(
        bet=bet2, team=team, user=user, gate_config=gate_config, artifact=artifact, sandbox_class=guarded_sandbox
    )
    assert guarded_result["pass"] is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reviewhog_check_skips_gracefully_without_a_pr_url(team, user) -> None:
    """A reviewhog check declared on a bet whose artifact carries no pr_url must not block
    the gate — this is the ADR-2 "never block on ReviewHog" guarantee, now generalized to
    apply per-check regardless of its `required` flag."""
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_gate_sandbox_class()
    gate_config = {"checks": [{"name": "review", "check_type": "reviewhog"}]}

    result = await _run_gate(
        bet=bet, team=team, user=user, gate_config=gate_config, artifact={}, sandbox_class=sandbox_class
    )

    assert result["pass"] is True
    payload = await sync_to_async(_gate_result_payload)(bet.id)
    assert "skipped" in _checks_by_name(payload)["review"]["details"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_reviewhog_check_maps_blocking_findings_to_a_failing_check(team, user) -> None:
    bet = await sync_to_async(_bet_in_building)(team, user)
    sandbox_class, _ = make_fake_gate_sandbox_class()
    gate_config = {"checks": [{"name": "review", "check_type": "reviewhog"}]}

    with (
        patch("products.review_hog.backend.facade.api.is_review_available_for_team", return_value=True),
        patch(
            "products.review_hog.backend.facade.api.trigger_review",
            return_value=TriggerReviewResult(started=True, review_id="review-1", reason=None),
        ),
        patch(
            "products.review_hog.backend.facade.api.get_review_status",
            return_value=ReviewReportStatus(
                review_id="review-1",
                in_progress=False,
                violations=[ReviewViolation(code="bug", message="off-by-one", severity="must_fix")],
            ),
        ),
    ):
        result = await _run_gate(
            bet=bet,
            team=team,
            user=user,
            gate_config=gate_config,
            artifact={"pr_url": "https://github.com/o/r/pull/1"},
            sandbox_class=sandbox_class,
        )

    assert result["pass"] is False
    payload = await sync_to_async(_gate_result_payload)(bet.id)
    assert "off-by-one" in _checks_by_name(payload)["review"]["details"]
