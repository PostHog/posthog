import pytest
from posthog.test.base import BaseTest

from products.error_tracking.backend.max_tools import (
    ErrorTrackingExplainIssueOutput,
    ErrorTrackingExplainIssueTool,
    ErrorTrackingIssueFilteringTool,
)

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.utils.types import AssistantState


class TestErrorTrackingIssueFilteringToolHelpers(BaseTest):
    def _create_tool(self) -> ErrorTrackingIssueFilteringTool:
        return ErrorTrackingIssueFilteringTool(
            team=self.team,
            user=self.user,
            tool_call_id="test-call",
            state=AssistantState(messages=[]),
            context={"current_query": "{}"},
        )

    def test_convert_to_artifact_format_status_only(self):
        tool = self._create_tool()
        result = tool._convert_to_artifact_format({"status": "active"})
        assert result == {"kind": "ErrorTrackingQuery", "status": "active"}

    def test_convert_to_artifact_format_search_query(self):
        tool = self._create_tool()
        result = tool._convert_to_artifact_format({"searchQuery": "TypeError"})
        assert result == {"kind": "ErrorTrackingQuery", "searchQuery": "TypeError"}

    def test_convert_to_artifact_format_date_range(self):
        tool = self._create_tool()
        result = tool._convert_to_artifact_format({"dateRange": {"date_from": "-7d"}})
        assert result == {"kind": "ErrorTrackingQuery", "dateRange": {"date_from": "-7d"}}

    def test_convert_to_artifact_format_combined(self):
        tool = self._create_tool()
        result = tool._convert_to_artifact_format(
            {
                "status": "resolved",
                "searchQuery": "NullPointer",
                "dateRange": {"date_from": "-14d"},
            }
        )
        assert result == {
            "kind": "ErrorTrackingQuery",
            "status": "resolved",
            "searchQuery": "NullPointer",
            "dateRange": {"date_from": "-14d"},
        }

    def test_convert_to_artifact_format_new_filters(self):
        tool = self._create_tool()
        result = tool._convert_to_artifact_format({"newFilters": [{"type": "AND", "values": []}]})
        assert result == {
            "kind": "ErrorTrackingQuery",
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
        }

    def test_convert_to_artifact_format_empty(self):
        tool = self._create_tool()
        result = tool._convert_to_artifact_format({})
        assert result == {"kind": "ErrorTrackingQuery"}

    def test_generate_artifact_name_status_only(self):
        tool = self._create_tool()
        result = tool._generate_artifact_name({"status": "active"})
        assert result == "Active issues"

    def test_generate_artifact_name_search_query(self):
        tool = self._create_tool()
        result = tool._generate_artifact_name({"searchQuery": "TypeError"})
        assert result == "Issues matching 'TypeError'"

    def test_generate_artifact_name_status_and_search(self):
        tool = self._create_tool()
        result = tool._generate_artifact_name({"status": "resolved", "searchQuery": "NullPointer"})
        assert result == "Resolved issues matching 'NullPointer'"

    def test_generate_artifact_name_relative_date_days(self):
        tool = self._create_tool()
        result = tool._generate_artifact_name({"dateRange": {"date_from": "-7d"}})
        assert result == "Issues from last 7 days"

    def test_generate_artifact_name_relative_date_hours(self):
        tool = self._create_tool()
        result = tool._generate_artifact_name({"dateRange": {"date_from": "-24h"}})
        assert result == "Issues from last 24 hours"

    def test_generate_artifact_name_full_combo(self):
        tool = self._create_tool()
        result = tool._generate_artifact_name(
            {
                "status": "active",
                "searchQuery": "Error",
                "dateRange": {"date_from": "-14d"},
            }
        )
        assert result == "Active issues matching 'Error' from last 14 days"

    def test_generate_artifact_name_empty(self):
        tool = self._create_tool()
        result = tool._generate_artifact_name({})
        assert result == "Issues"

    def test_parse_output_with_xml_tags(self):
        tool = self._create_tool()
        output = '<output>{"status": "active", "searchQuery": "TypeError"}</output>'
        result = tool._parse_output(output)
        assert result == {"status": "active", "searchQuery": "TypeError"}

    def test_parse_output_with_markdown_code_block(self):
        tool = self._create_tool()
        output = '```json\n{"status": "resolved"}\n```'
        result = tool._parse_output(output)
        assert result == {"status": "resolved"}

    def test_parse_output_raw_json(self):
        tool = self._create_tool()
        output = '{"dateRange": {"date_from": "-7d"}}'
        result = tool._parse_output(output)
        assert result == {"dateRange": {"date_from": "-7d"}}

    def test_parse_output_empty_raises(self):
        tool = self._create_tool()
        with pytest.raises(PydanticOutputParserException):
            tool._parse_output("")

    def test_parse_output_invalid_json_raises(self):
        tool = self._create_tool()
        with pytest.raises(PydanticOutputParserException):
            tool._parse_output("not valid json")


class TestErrorTrackingExplainIssueToolHelpers(BaseTest):
    def _create_tool(self) -> ErrorTrackingExplainIssueTool:
        return ErrorTrackingExplainIssueTool(
            team=self.team,
            user=self.user,
            tool_call_id="test-call",
            state=AssistantState(messages=[]),
            context={},
        )

    def test_format_stacktrace_with_exception_list(self):
        tool = self._create_tool()
        properties = {
            "$exception_list": [
                {
                    "type": "TypeError",
                    "value": "Cannot read property 'foo' of undefined",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app.js",
                                "lineno": 42,
                                "function": "handleClick",
                                "in_app": True,
                                "context_line": "const val = obj.foo;",
                            },
                            {
                                "filename": "react.js",
                                "lineno": 100,
                                "function": "dispatchEvent",
                                "in_app": False,
                            },
                        ]
                    },
                }
            ]
        }
        result = tool._format_stacktrace_from_properties(properties)
        assert "TypeError: Cannot read property 'foo' of undefined" in result
        assert "[IN-APP]" in result
        assert "app.js" in result
        assert "line: 42" in result
        assert "handleClick" in result
        assert "const val = obj.foo;" in result
        assert "react.js" in result

    def test_format_stacktrace_with_legacy_format(self):
        tool = self._create_tool()
        properties = {
            "$exception_types": ["ValueError"],
            "$exception_values": ["Invalid input"],
        }
        result = tool._format_stacktrace_from_properties(properties)
        assert result == "ValueError: Invalid input"

    def test_format_stacktrace_empty_exception_list(self):
        tool = self._create_tool()
        properties: dict = {"$exception_list": []}
        result = tool._format_stacktrace_from_properties(properties)
        assert result == ""

    def test_format_explanation_for_user(self):
        tool = self._create_tool()
        summary = ErrorTrackingExplainIssueOutput(
            generic_description="A TypeError occurs when accessing a property on undefined.",
            specific_problem="The 'user' object is null when handleClick runs before data loads.",
            possible_resolutions=[
                "Add null check before accessing user.name",
                "Use optional chaining: user?.name",
                "Ensure data is loaded before rendering the component",
            ],
        )
        result = tool._format_explanation_for_user(summary, "TypeError in handleClick")

        assert "### Issue: TypeError in handleClick" in result
        assert "TypeError occurs when accessing a property" in result
        assert "#### What's happening?" in result
        assert "'user' object is null" in result
        assert "#### How to fix it:" in result
        assert "1. Add null check" in result
        assert "2. Use optional chaining" in result
        assert "3. Ensure data is loaded" in result
