from __future__ import annotations

import pytest

from products.posthog_ai.eval_harness.harness.cli import SkillDelivery, parse_args
from products.posthog_ai.eval_harness.harness.lifecycle import _with_mcp_mode


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
    "argv,expected_url",
    [
        ([], "http://host.docker.internal:8787/mcp"),
        (["--mcp-mode", "cli"], "http://host.docker.internal:8787/mcp?mode=cli"),
        (["--mcp-mode", "code"], "http://host.docker.internal:8787/mcp?mode=code"),
    ],
)
def test_mcp_mode_pins_the_sandbox_mcp_url(argv: list[str], expected_url: str) -> None:
    overrides = {
        "SANDBOX_API_URL": "http://host.docker.internal:8000",
        "SANDBOX_MCP_URL": "http://host.docker.internal:8787/mcp",
    }

    pinned = _with_mcp_mode(overrides, parse_args(argv).mcp_mode)

    assert pinned == {**overrides, "SANDBOX_MCP_URL": expected_url}
