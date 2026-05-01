from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.llm_analytics.backend.models.skills import LLMSkill, LLMSkillFile
from products.signals.backend.agent_harness.budgets import DEFAULT_BUDGET, BudgetCaps, resolve_budget
from products.signals.backend.agent_harness.prompt import build_run_prompt
from products.signals.backend.agent_harness.runner import RunResult, arun_signals_agent
from products.signals.backend.agent_harness.skill_loader import (
    SkillNotFoundError,
    is_signals_agent_skill,
    load_skill_for_run,
)
from products.signals.backend.models import SignalAgentConfig, SignalAgentRun
from products.signals.backend.temporal.agentic.agent_scheduler import RunSignalsAgentInput, run_signals_agent_activity


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SignalsAgentTestOrg-{random.randint(1, 99999)}",
        is_ai_data_processing_approved=True,
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SignalsAgentTestTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


@pytest_asyncio.fixture
async def aerrors_skill(ateam):
    skill = await sync_to_async(LLMSkill.objects.create)(
        team=ateam,
        name="signals-agent-errors",
        description="Errors scout",
        body="scout",
    )
    yield skill


class TestBudgetResolution(BaseTest):
    def test_default_budget_when_no_overrides(self) -> None:
        assert resolve_budget(None) == DEFAULT_BUDGET
        assert resolve_budget({}) == DEFAULT_BUDGET

    def test_partial_overrides_apply_on_top_of_defaults(self) -> None:
        budget = resolve_budget({"max_runtime_s": 600})
        assert budget.max_runtime_s == 600
        assert budget.max_tool_calls == DEFAULT_BUDGET.max_tool_calls
        assert budget.max_cost_usd == DEFAULT_BUDGET.max_cost_usd
        assert budget.max_findings == DEFAULT_BUDGET.max_findings

    def test_unknown_keys_are_ignored(self) -> None:
        # A stale config row shouldn't crash the runner if a budget field gets renamed.
        budget = resolve_budget({"max_runtime_s": 120, "obsolete_field": "ignore_me"})
        assert budget == BudgetCaps(max_runtime_s=120)


class TestSkillLoader(BaseTest):
    def _create_skill(self, name: str, *, body: str = "skill body", file_paths: list[str] | None = None) -> LLMSkill:
        skill = LLMSkill.objects.create(
            team=self.team,
            name=name,
            description="A test skill",
            body=body,
            allowed_tools=["search_recent_runs", "remember"],
        )
        for path in file_paths or []:
            LLMSkillFile.objects.create(skill=skill, path=path, content=f"# {path}", content_type="text/plain")
        return skill

    def test_loads_latest_version_by_default(self) -> None:
        self._create_skill("signals-agent-errors", body="v1 body")
        loaded = load_skill_for_run(self.team, "signals-agent-errors")
        assert loaded.name == "signals-agent-errors"
        assert loaded.version == 1
        assert loaded.body == "v1 body"
        assert loaded.allowed_tools == ["search_recent_runs", "remember"]

    def test_loads_file_manifest_alongside_body(self) -> None:
        self._create_skill(
            "signals-agent-errors",
            file_paths=["references/playbook.md", "references/examples.md"],
        )
        loaded = load_skill_for_run(self.team, "signals-agent-errors")
        # Files come back sorted by path so the manifest is stable.
        assert [f.path for f in loaded.files] == [
            "references/examples.md",
            "references/playbook.md",
        ]

    def test_missing_skill_raises(self) -> None:
        with pytest.raises(SkillNotFoundError):
            load_skill_for_run(self.team, "signals-agent-does-not-exist")

    def test_signals_agent_prefix_check(self) -> None:
        match = self._create_skill("signals-agent-errors")
        non_match = self._create_skill("custom-research-helper")
        assert is_signals_agent_skill(match) is True
        assert is_signals_agent_skill(non_match) is False


class TestPromptBuilder(BaseTest):
    def test_renders_skill_body_and_file_manifest(self) -> None:
        skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-agent-errors",
            description="Errors scout",
            body="watch for spikes",
        )
        LLMSkillFile.objects.create(skill=skill, path="refs/playbook.md", content="x", content_type="text/plain")
        loaded = load_skill_for_run(self.team, "signals-agent-errors")
        started_at = datetime(2026, 5, 1, 12, 34, 56, tzinfo=UTC)
        prompt = build_run_prompt(
            loaded,
            run_id="00000000-0000-0000-0000-000000000abc",
            team_id=self.team.id,
            started_at=started_at,
        )
        assert "signals-agent-errors" in prompt
        assert "watch for spikes" in prompt
        assert "refs/playbook.md" in prompt
        # The agent needs to know its own run id to attribute emits and memories.
        assert "00000000-0000-0000-0000-000000000abc" in prompt
        # The base prompt teaches the agent to call the harness MCP tools by name.
        assert "signals-agent-harness-runs-findings-create" in prompt
        assert "signals-agent-harness-memory-list" in prompt
        # Recency lens references the started_at anchor.
        assert "Recency lens" in prompt
        assert "2026-05-01T12:34:56+00:00" in prompt


# Orchestration tests run as plain pytest functions because the async runner uses
# `database_sync_to_async`, which requires the test team to be visible across threads.
# The fixture-based pattern (matching test_agentic_report_activity.py) gives us that.


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_successful_run_persists_completed_row(ateam, aerrors_skill):
    async def fake_spawn(**_kwargs):
        return "I would investigate /checkout 500s next."

    with patch("products.signals.backend.agent_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_agent(team_id=ateam.id, skill_name="signals-agent-errors")

    assert result.status == SignalAgentRun.Status.COMPLETED
    assert result.skill_name == "signals-agent-errors"
    assert result.skill_version == 1
    assert result.last_message and "checkout" in result.last_message

    run_row = await database_sync_to_async(SignalAgentRun.objects.get)(id=result.run_id)
    assert run_row.status == SignalAgentRun.Status.COMPLETED
    assert run_row.completed_at is not None
    assert run_row.summary == "I would investigate /checkout 500s next."
    assert "runtime_s" in run_row.budget_used
    config = await database_sync_to_async(SignalAgentConfig.objects.get)(team=ateam)
    assert config.enabled is False
    assert config.shadow_mode is True
    assert run_row.agent_config_id == config.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_failed_run_persists_failure_metadata(ateam, aerrors_skill):
    async def fake_spawn(**_kwargs):
        raise RuntimeError("sandbox refused to start")

    with patch("products.signals.backend.agent_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_agent(team_id=ateam.id, skill_name="signals-agent-errors")

    assert result.status == SignalAgentRun.Status.FAILED
    assert result.last_message is None
    run_row = await database_sync_to_async(SignalAgentRun.objects.get)(id=result.run_id)
    assert run_row.status == SignalAgentRun.Status.FAILED
    assert run_row.completed_at is not None
    assert "sandbox refused to start" in run_row.summary
    assert run_row.metadata.get("error_type") == "RuntimeError"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_missing_skill_does_not_create_run_row(ateam):
    with pytest.raises(SkillNotFoundError):
        await arun_signals_agent(team_id=ateam.id, skill_name="signals-agent-missing")
    has_runs = await database_sync_to_async(SignalAgentRun.objects.filter(team=ateam).exists)()
    assert not has_runs


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_budget_overrides_propagate_into_run_metadata(ateam, aerrors_skill):
    async def fake_spawn(**_kwargs):
        return "ok"

    with patch("products.signals.backend.agent_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_agent(
            team_id=ateam.id,
            skill_name="signals-agent-errors",
            budget_overrides={"max_runtime_s": 120},
        )

    run_row = await database_sync_to_async(SignalAgentRun.objects.get)(id=result.run_id)
    assert run_row.metadata["budget"]["max_runtime_s"] == 120


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_skip_if_running_prevents_concurrent_runs(ateam, aerrors_skill):
    config = await database_sync_to_async(SignalAgentConfig.objects.create)(team=ateam)
    await database_sync_to_async(SignalAgentRun.objects.create)(
        team=ateam,
        agent_config=config,
        skill_name="signals-agent-errors",
        skill_version=1,
        status=SignalAgentRun.Status.RUNNING,
    )

    async def fake_spawn(**_kwargs):
        raise AssertionError("spawn should not run while a prior run is RUNNING")

    with patch("products.signals.backend.agent_harness.runner._spawn_and_run", side_effect=fake_spawn):
        result = await arun_signals_agent(team_id=ateam.id, skill_name="signals-agent-errors")

    assert result.run_id is None
    assert result.status is None
    assert result.skip_reason and "RUNNING" in result.skip_reason
    count = await database_sync_to_async(SignalAgentRun.objects.filter(team=ateam).count)()
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_returns_completed_outcome(ateam):
    async def fake_arun(**_kwargs):
        return RunResult(
            run_id="abc",
            status=SignalAgentRun.Status.COMPLETED,
            last_message="ok",
            runtime_s=1.5,
            skill_name="signals-agent-errors",
            skill_version=2,
        )

    with patch(
        "products.signals.backend.temporal.agentic.agent_scheduler.arun_signals_agent",
        side_effect=fake_arun,
    ):
        env = ActivityEnvironment()
        output = await env.run(
            run_signals_agent_activity,
            RunSignalsAgentInput(team_id=ateam.id, skill_name="signals-agent-errors"),
        )

    assert output.run_id == "abc"
    assert output.status == "completed"
    assert output.skill_version == 2
    assert output.skip_reason is None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_activity_returns_skip_outcome_when_already_running(ateam):
    async def fake_arun(**_kwargs):
        return RunResult(
            run_id=None,
            status=None,
            last_message=None,
            runtime_s=0.0,
            skill_name="signals-agent-errors",
            skill_version=1,
            skip_reason="prior run still in RUNNING status",
        )

    with patch(
        "products.signals.backend.temporal.agentic.agent_scheduler.arun_signals_agent",
        side_effect=fake_arun,
    ):
        env = ActivityEnvironment()
        output = await env.run(
            run_signals_agent_activity,
            RunSignalsAgentInput(team_id=ateam.id, skill_name="signals-agent-errors"),
        )

    assert output.run_id is None
    assert output.status is None
    assert output.skip_reason and "RUNNING" in output.skip_reason
