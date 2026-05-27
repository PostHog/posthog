import json
from pathlib import Path

from parameterized import parameterized

_DEFINITIONS = Path(__file__).parents[4] / "services/mcp/schema/generated-tool-definitions.json"


class TestEngineeringAnalyticsMCPTools:
    @parameterized.expand(["workflow-report", "time-to-merge", "pr-lifecycle"])
    def test_tool_is_generated_read_only_and_scoped(self, tool_name: str) -> None:
        definitions = json.loads(_DEFINITIONS.read_text())

        assert tool_name in definitions, f"{tool_name} missing from generated tool definitions; run hogli build:openapi"
        entry = definitions[tool_name]
        assert entry["feature"] == "engineering_analytics"
        assert entry["annotations"]["readOnlyHint"] is True
        assert entry["annotations"]["destructiveHint"] is False
        assert "engineering_analytics:read" in entry["required_scopes"]
