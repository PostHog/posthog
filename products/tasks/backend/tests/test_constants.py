import re
from pathlib import Path

import yaml

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX

PRODUCTS_DIR = Path(__file__).resolve().parents[3]


def _enabled_destructive_tools() -> list[str]:
    tools: list[str] = []
    for config_path in sorted(PRODUCTS_DIR.glob("*/mcp/*.yaml")) + sorted(PRODUCTS_DIR.glob("*/mcp/*.yml")):
        config = yaml.safe_load(config_path.read_text())
        if not isinstance(config, dict):
            continue
        declared = config.get("tools") or {}
        entries = declared.items() if isinstance(declared, dict) else ((t.get("name"), t) for t in declared)
        for name, tool in entries:
            if not isinstance(tool, dict) or not isinstance(name, str) or not tool.get("enabled"):
                continue
            if not (tool.get("annotations") or {}).get("destructive"):
                continue
            # confirmed_action tools register no bare `<name>`; codegen emits `<name>-prepare`
            # (non-destructive) and `<name>-execute` (the destructive action that actually runs).
            # Gate the generated execute name, since that is what the client relays for approval.
            tools.append(f"{name}-execute" if tool.get("confirmed_action") else name)
    return tools


def test_exec_permission_regex_covers_destructive_annotated_tools():
    # A destructive-annotated tool the regex misses is never relayed for approval and executes
    # silently in `auto` mode — the exact gap this regex exists to close. When this fails, add the
    # tool name to `POSTHOG_EXEC_DESTRUCTIVE_SUB_TOOLS` in `constants.py` AND to
    # `POSTHOG_DESTRUCTIVE_SUB_TOOLS` in `products/posthog_ai/frontend/policy/toolPolicy.ts`.
    destructive = _enabled_destructive_tools()
    assert len(destructive) > 0, f"no destructive-annotated MCP tools found under {PRODUCTS_DIR} — glob broken?"

    pattern = re.compile(POSTHOG_EXEC_PERMISSION_REGEX, re.IGNORECASE)
    ungated = sorted(name for name in destructive if not pattern.search(name))
    assert not ungated, f"destructive-annotated MCP tools not covered by POSTHOG_EXEC_PERMISSION_REGEX: {ungated}"
