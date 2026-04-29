from __future__ import annotations

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.llm_analytics.backend.models.skills import LLMSkill, LLMSkillFile
from products.signals.backend.agent_harness.budgets import DEFAULT_BUDGET, BudgetCaps, resolve_budget
from products.signals.backend.agent_harness.prompt import build_run_prompt
from products.signals.backend.agent_harness.runner import run_signals_agent
from products.signals.backend.agent_harness.skill_loader import (
    SkillNotFoundError,
    is_signals_agent_skill,
    load_skill_for_run,
)
from products.signals.backend.models import SignalAgentConfig, SignalAgentRun


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
        prompt = build_run_prompt(loaded)
        assert "signals-agent-errors" in prompt
        assert "watch for spikes" in prompt
        assert "refs/playbook.md" in prompt
        # Phase 2 contract: scaffolding-only run, no signal emission.
        assert "Do not emit any signals" in prompt


class TestRunnerOrchestration(BaseTest):
    """Exercise the runner without actually spawning a sandbox.

    Mocks `_spawn_and_run` so we can assert the run-row lifecycle (insert with
    status=running, update with status=completed/failed) and the per-run config
    get-or-create behavior.
    """

    def setUp(self) -> None:
        super().setUp()
        LLMSkill.objects.create(
            team=self.team,
            name="signals-agent-errors",
            description="Errors scout",
            body="scout",
        )

    def test_successful_run_persists_completed_row(self) -> None:
        async def fake_spawn(**_kwargs):
            return "I would investigate /checkout 500s next."

        with patch("products.signals.backend.agent_harness.runner._spawn_and_run", side_effect=fake_spawn):
            result = run_signals_agent(team_id=self.team.id, skill_name="signals-agent-errors")

        assert result.status == SignalAgentRun.Status.COMPLETED
        assert result.skill_name == "signals-agent-errors"
        assert result.skill_version == 1
        assert result.last_message and "checkout" in result.last_message

        run_row = SignalAgentRun.objects.get(id=result.run_id)
        assert run_row.status == SignalAgentRun.Status.COMPLETED
        assert run_row.completed_at is not None
        assert run_row.summary == "I would investigate /checkout 500s next."
        assert "runtime_s" in run_row.budget_used
        # Config gets auto-created with safe defaults on first run.
        config = SignalAgentConfig.objects.get(team=self.team)
        assert config.enabled is False
        assert config.shadow_mode is True
        assert run_row.agent_config_id == config.id

    def test_failed_run_persists_failure_metadata(self) -> None:
        async def fake_spawn(**_kwargs):
            raise RuntimeError("sandbox refused to start")

        with patch("products.signals.backend.agent_harness.runner._spawn_and_run", side_effect=fake_spawn):
            result = run_signals_agent(team_id=self.team.id, skill_name="signals-agent-errors")

        assert result.status == SignalAgentRun.Status.FAILED
        assert result.last_message is None
        run_row = SignalAgentRun.objects.get(id=result.run_id)
        assert run_row.status == SignalAgentRun.Status.FAILED
        assert run_row.completed_at is not None
        assert "sandbox refused to start" in run_row.summary
        assert run_row.metadata.get("error_type") == "RuntimeError"

    def test_missing_skill_does_not_create_run_row(self) -> None:
        with pytest.raises(SkillNotFoundError):
            run_signals_agent(team_id=self.team.id, skill_name="signals-agent-missing")
        assert not SignalAgentRun.objects.filter(team=self.team).exists()

    def test_budget_overrides_propagate_into_run_metadata(self) -> None:
        async def fake_spawn(**_kwargs):
            return "ok"

        with patch("products.signals.backend.agent_harness.runner._spawn_and_run", side_effect=fake_spawn):
            result = run_signals_agent(
                team_id=self.team.id,
                skill_name="signals-agent-errors",
                budget_overrides={"max_runtime_s": 120},
            )

        run_row = SignalAgentRun.objects.get(id=result.run_id)
        assert run_row.metadata["budget"]["max_runtime_s"] == 120
