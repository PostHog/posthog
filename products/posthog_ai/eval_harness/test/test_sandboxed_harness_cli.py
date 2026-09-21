from __future__ import annotations

import pytest

from products.posthog_ai.eval_harness.harness.cli import MCP_EXEC_SKILLS_FLAG_KEY, SkillDelivery, parse_args
from products.tasks.backend.facade.agents import MCP_EXEC_SKILLS_FEATURE_FLAG


@pytest.mark.parametrize(
    "argv,expected_delivery",
    [
        ([], "bundled"),
        (["--skill-delivery", "exec"], "exec"),
    ],
)
def test_skill_delivery_defaults_to_bundled_and_allows_exec(argv: list[str], expected_delivery: SkillDelivery) -> None:
    assert parse_args(argv).skill_delivery == expected_delivery


@pytest.mark.parametrize(
    "argv,expected_flags",
    [
        ([], ()),
        (["--mcp-flag", "tool-a", "--mcp-flag", "tool-b", "--mcp-flag", "tool-a"], ("tool-a", "tool-b")),
    ],
)
def test_mcp_flags_are_collected_once_each(argv: list[str], expected_flags: tuple[str, ...]) -> None:
    assert parse_args(argv).mcp_flags == expected_flags


def test_mcp_flag_cannot_bypass_skill_delivery() -> None:
    assert MCP_EXEC_SKILLS_FLAG_KEY == MCP_EXEC_SKILLS_FEATURE_FLAG
    with pytest.raises(SystemExit):
        parse_args(["--mcp-flag", MCP_EXEC_SKILLS_FEATURE_FLAG])
