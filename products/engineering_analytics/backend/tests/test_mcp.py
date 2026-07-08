import json
from pathlib import Path

import pytest

_DEFINITIONS = Path(__file__).parents[4] / "services/mcp/schema/generated-tool-definitions.json"


class TestEngineeringAnalyticsMCPTools:
    @pytest.mark.parametrize(
        "tool", ["pull-requests", "workflow-health", "pr-lifecycle", "engineering-analytics-flaky-tests"]
    )
    def test_tool_is_generated_read_only_and_scoped(self, tool: str) -> None:
        definitions = json.loads(_DEFINITIONS.read_text())

        assert tool in definitions, f"{tool} missing from generated tool definitions; run hogli build:openapi"
        entry = definitions[tool]
        assert entry["feature"] == "engineering_analytics"
        assert entry["annotations"]["readOnlyHint"] is True
        assert entry["annotations"]["destructiveHint"] is False
        assert "engineering_analytics:read" in entry["required_scopes"]
