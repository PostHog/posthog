from __future__ import annotations

import pytest
from posthog.test.base import BaseTest

from products.llm_analytics.backend.models.skills import LLMSkill
from products.signals.backend.scout_harness.skill_loader import load_skill_for_run
from products.signals.backend.scout_harness.tool_registry import (
    HARNESS_INTERNAL_TOOLS,
    InvalidAllowedToolsError,
    UnknownHarnessToolError,
    validate_and_partition_allowed_tools,
)


class TestValidateAndPartitionAllowedTools:
    def test_empty_list_returns_undeclared_resolution(self) -> None:
        result = validate_and_partition_allowed_tools([])
        assert result.declared is False
        assert result.harness_tools == frozenset()
        assert result.mcp_tool_candidates == frozenset()

    def test_known_harness_tools_partition_correctly(self) -> None:
        result = validate_and_partition_allowed_tools(["search_recent_runs", "remember", "emit_finding"])
        assert result.declared is True
        assert result.harness_tools == frozenset({"search_recent_runs", "remember", "emit_finding"})
        assert result.mcp_tool_candidates == frozenset()

    def test_mcp_shaped_names_partition_to_mcp_candidates(self) -> None:
        result = validate_and_partition_allowed_tools(["mcp__posthog__exec", "posthog:execute-sql", "team.tool"])
        assert result.declared is True
        assert result.harness_tools == frozenset()
        assert result.mcp_tool_candidates == frozenset({"mcp__posthog__exec", "posthog:execute-sql", "team.tool"})

    def test_mixed_harness_and_mcp_partition(self) -> None:
        result = validate_and_partition_allowed_tools(["remember", "mcp__posthog__exec", "search_scratchpad"])
        assert result.harness_tools == frozenset({"remember", "search_scratchpad"})
        assert result.mcp_tool_candidates == frozenset({"mcp__posthog__exec"})

    def test_unknown_bare_name_raises_with_known_list(self) -> None:
        with pytest.raises(UnknownHarnessToolError) as exc_info:
            validate_and_partition_allowed_tools(["search_resent_runs"])
        # Error mentions both the offender and the known set so the skill author can self-correct.
        assert "search_resent_runs" in str(exc_info.value)
        assert "search_recent_runs" in str(exc_info.value)

    def test_duplicate_entries_raise(self) -> None:
        with pytest.raises(InvalidAllowedToolsError):
            validate_and_partition_allowed_tools(["remember", "remember"])

    def test_empty_string_entry_raises(self) -> None:
        with pytest.raises(InvalidAllowedToolsError):
            validate_and_partition_allowed_tools(["remember", ""])

    def test_whitespace_only_entry_raises(self) -> None:
        with pytest.raises(InvalidAllowedToolsError):
            validate_and_partition_allowed_tools(["remember", "   "])

    def test_non_string_entry_raises(self) -> None:
        with pytest.raises(InvalidAllowedToolsError):
            validate_and_partition_allowed_tools(["remember", 123])  # type: ignore[list-item]

    def test_harness_internal_tools_registry_matches_expected(self) -> None:
        # Locks in the canonical surface — bumping HARNESS_INTERNAL_TOOLS must be deliberate.
        assert HARNESS_INTERNAL_TOOLS == frozenset(
            {
                "emit_finding",
                "forget",
                "get_run",
                "remember",
                "search_scratchpad",
                "search_recent_runs",
            }
        )


class TestSkillLoaderAllowedToolsIntegration(BaseTest):
    def test_loads_resolution_alongside_raw_allowed_tools(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="Errors scout",
            body="x",
            allowed_tools=["search_recent_runs", "remember", "mcp__posthog__exec"],
        )
        loaded = load_skill_for_run(self.team, "signals-scout-errors")
        assert loaded.allowed_tools == ["search_recent_runs", "remember", "mcp__posthog__exec"]
        assert loaded.allowed_tools_resolution.declared is True
        assert loaded.allowed_tools_resolution.harness_tools == frozenset({"search_recent_runs", "remember"})
        assert loaded.allowed_tools_resolution.mcp_tool_candidates == frozenset({"mcp__posthog__exec"})

    def test_load_raises_on_unknown_harness_tool_in_allowed_tools(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="Errors scout",
            body="x",
            allowed_tools=["search_resent_runs"],  # typo of search_recent_runs
        )
        with pytest.raises(UnknownHarnessToolError):
            load_skill_for_run(self.team, "signals-scout-errors")

    def test_empty_allowed_tools_yields_undeclared_resolution(self) -> None:
        LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-errors",
            description="Errors scout",
            body="x",
            allowed_tools=[],
        )
        loaded = load_skill_for_run(self.team, "signals-scout-errors")
        assert loaded.allowed_tools_resolution.declared is False
