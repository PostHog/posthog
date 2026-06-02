import json
from pathlib import Path

_DEFINITIONS = Path(__file__).parents[4] / "services/mcp/schema/generated-tool-definitions.json"


class TestEngineeringAnalyticsMCPTools:
    def test_pr_lifecycle_tool_is_generated_read_only_and_scoped(self) -> None:
        definitions = json.loads(_DEFINITIONS.read_text())

        assert "pr-lifecycle" in definitions, (
            "pr-lifecycle missing from generated tool definitions; run hogli build:openapi"
        )
        entry = definitions["pr-lifecycle"]
        assert entry["feature"] == "engineering_analytics"
        assert entry["annotations"]["readOnlyHint"] is True
        assert entry["annotations"]["destructiveHint"] is False
        assert "engineering_analytics:read" in entry["required_scopes"]

    def test_removed_report_tools_are_not_generated(self) -> None:
        definitions = json.loads(_DEFINITIONS.read_text())

        assert "workflow-report" not in definitions
        assert "time-to-merge" not in definitions
