import re
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).parent
SKILL_PATH = SKILLS_DIR / "investigating-logs" / "SKILL.md"
TOOLS_PATHS = [
    SKILLS_DIR.parent / "mcp" / "tools.yaml",
    SKILLS_DIR.parents[1] / "tracing" / "mcp" / "tools.yaml",
]


def _daily_health_recipe() -> str:
    skill_content = SKILL_PATH.read_text(encoding="utf-8")
    match = re.search(r"^### Daily service health report.*?(?=^### )", skill_content, re.MULTILINE | re.DOTALL)
    assert match is not None
    return match.group(0)


def test_daily_health_recipe_uses_tools_that_return_log_health_and_alert_history() -> None:
    enabled_tools: set[str] = set()
    for tools_path in TOOLS_PATHS:
        tools = yaml.safe_load(tools_path.read_text(encoding="utf-8"))["tools"]
        enabled_tools |= {name for name, config in tools.items() if config.get("enabled")}

    recipe = _daily_health_recipe()
    referenced_tools = set(re.findall(r"posthog:([a-z0-9-]+)", recipe))

    assert referenced_tools - enabled_tools == set()
    assert {"logs-services-create", "apm-service-health", "logs-alerts-events-list"} <= referenced_tools
    assert "firedSince" not in recipe
    assert 'include: ["logs"]' not in recipe
