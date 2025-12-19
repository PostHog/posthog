import re
import json
import logging
from typing import Any, Optional
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from posthog.schema import (
    ArtifactContentType,
    ArtifactSource,
    AssistantToolCallMessage,
    ErrorTrackingBreakdownsQuery,
    ErrorTrackingFiltersArtifactContent,
    ErrorTrackingImpactArtifactContent,
    ErrorTrackingImpactSegment,
    ErrorTrackingQuery,
    OrderBy1,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.sync import database_sync_to_async

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.context.error_tracking import ErrorTrackingFiltersContext, ErrorTrackingIssueContext
from ee.hogai.llm import MaxChatAnthropic
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.utils.types.base import ArtifactRefMessage

from .models import ErrorTrackingIssue
from .prompts import (
    ERROR_TRACKING_EXPLAIN_ISSUE_PROMPT,
    ERROR_TRACKING_FILTER_INITIAL_PROMPT,
    ERROR_TRACKING_FILTER_PROPERTIES_PROMPT,
    ERROR_TRACKING_SYSTEM_PROMPT,
    PREFER_FILTERS_PROMPT,
)

logger = logging.getLogger(__name__)


def _fetch_error_tracking_issue(
    team_id: int, issue_id: str, with_first_seen: bool = False
) -> ErrorTrackingIssue | None:
    """Fetch an error tracking issue from the database.

    Args:
        team_id: The team ID to filter by
        issue_id: The issue ID to fetch
        with_first_seen: If True, includes the first_seen annotation from fingerprints
    """
    try:
        queryset = ErrorTrackingIssue.objects.with_first_seen() if with_first_seen else ErrorTrackingIssue.objects
        return queryset.filter(team_id=team_id, id=issue_id).first()
    except Exception:
        return None


class UpdateIssueQueryArgs(BaseModel):
    change: str = Field(description="The specific change to be made to issue filters, briefly described.")


class ErrorTrackingIssueFilteringTool(MaxTool):
    name: str = "filter_error_tracking_issues"
    description: str = "Create error tracking filters based on search query, property filters, date ranges, assignee and status filters. Returns a filter artifact that the user can apply."
    context_prompt_template: str = "Current issue filters are: {current_query}"
    args_schema: type[BaseModel] = UpdateIssueQueryArgs

    async def _arun_impl(self, change: str) -> tuple[str, ToolMessagesArtifact | None]:
        if "current_query" not in self.context:
            raise ValueError("Context `current_query` is required for the `filter_error_tracking_issues` tool")

        current_query = self.context.get("current_query")
        system_content = (
            ERROR_TRACKING_SYSTEM_PROMPT
            + "<tool_usage>"
            + ERROR_TRACKING_FILTER_INITIAL_PROMPT
            + "</tool_usage>"
            + "<properties_taxonomy>"
            + ERROR_TRACKING_FILTER_PROPERTIES_PROMPT
            + "</properties_taxonomy>"
            + "<prefer_filters>"
            + PREFER_FILTERS_PROMPT
            + "</prefer_filters>"
            + f"\n\n Current issue filters are: {current_query}\n\n"
        )

        user_content = f"Update the error tracking issue list filters to: {change}"
        messages = [SystemMessage(content=system_content), HumanMessage(content=user_content)]

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                result = await self._model.ainvoke(messages)
                parsed_filters = self._parse_output(result.content)
                break
            except PydanticOutputParserException as e:
                # Add error feedback to system message for retry
                system_content += f"\n\nAvoid this error: {str(e)}"
                messages[0] = SystemMessage(content=system_content)
                final_error = e
        else:
            if final_error:
                raise final_error

        # Convert parsed filters to artifact format
        filters_obj = self._convert_to_artifact_format(parsed_filters)

        artifact_name = self._generate_artifact_name(filters_obj)
        content = ErrorTrackingFiltersArtifactContent(filters=filters_obj)
        artifact = await self._context_manager.artifacts.create_error_tracking_filters(
            content=content, name=artifact_name
        )

        artifact_ref_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.ERROR_TRACKING_FILTERS,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )

        issues_data = await self._execute_filters_query(filters_obj)

        # Create tool call message with issues data for the agent
        issues_summary = f"Found {len(issues_data)} issues matching filters: {artifact_name}\n\n"
        if issues_data:
            issues_summary += "Issues:\n"
            for issue in issues_data[:10]:  # Limit to 10 for readability, we can tweak this later if needed
                issues_summary += f"- {issue['name']} (ID: {issue['id']}, occurrences: {issue.get('occurrences', 'N/A')}, users: {issue.get('users', 'N/A')})\n"
            if len(issues_data) > 10:
                issues_summary += f"... and {len(issues_data) - 10} more issues\n"
        else:
            issues_summary += "No issues found matching these filters."

        tool_call_message = AssistantToolCallMessage(
            content=issues_summary,
            id=str(uuid4()),
            tool_call_id=self.tool_call_id,
        )

        return "", ToolMessagesArtifact(messages=[artifact_ref_message, tool_call_message])

    async def _execute_filters_query(self, filters_obj: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute the filters query to get actual issues using ErrorTrackingFiltersContext."""
        date_range = filters_obj.get("dateRange", {"date_from": "-7d"})
        if not date_range:
            date_range = {"date_from": "-7d"}

        context = ErrorTrackingFiltersContext(
            team=self._team,
            status=filters_obj.get("status"),
            search_query=filters_obj.get("searchQuery"),
            date_from=date_range.get("date_from", "-7d"),
            date_to=date_range.get("date_to"),
            order_by=filters_obj.get("orderBy", OrderBy1.LAST_SEEN),
            filter_group=filters_obj.get("filterGroup"),
            filter_test_accounts=filters_obj.get("filterTestAccounts", False),
            limit=25,
        )

        try:
            issues = await context.execute()
            return [issue.model_dump() for issue in issues]
        except Exception as e:
            logger.exception("Failed to execute error tracking filters query: %s", e)
            return []

    def _convert_to_artifact_format(self, parsed_filters: dict[str, Any]) -> dict[str, Any]:
        """Convert the LLM output format to the artifact filters format."""
        filters_obj: dict[str, Any] = {"kind": "ErrorTrackingQuery"}

        if parsed_filters.get("status"):
            filters_obj["status"] = parsed_filters["status"]

        if parsed_filters.get("searchQuery"):
            filters_obj["searchQuery"] = parsed_filters["searchQuery"]

        if parsed_filters.get("dateRange"):
            filters_obj["dateRange"] = parsed_filters["dateRange"]

        if parsed_filters.get("orderBy"):
            filters_obj["orderBy"] = parsed_filters["orderBy"]

        if parsed_filters.get("orderDirection"):
            filters_obj["orderDirection"] = parsed_filters["orderDirection"]

        if parsed_filters.get("filterTestAccounts") is not None:
            filters_obj["filterTestAccounts"] = parsed_filters["filterTestAccounts"]

        if parsed_filters.get("newFilters"):
            filters_obj["filterGroup"] = {"type": "AND", "values": parsed_filters["newFilters"]}

        return filters_obj

    def _generate_artifact_name(self, filters_obj: dict[str, Any]) -> str:
        """Generate a human-readable name for the filter artifact."""
        name_parts: list[str] = []

        if filters_obj.get("status"):
            name_parts.append(f"{filters_obj['status'].capitalize()} issues")
        else:
            name_parts.append("Issues")

        if filters_obj.get("searchQuery"):
            name_parts.append(f"matching '{filters_obj['searchQuery']}'")

        if filters_obj.get("dateRange"):
            date_range = filters_obj["dateRange"]
            if date_range.get("date_from"):
                date_from = date_range["date_from"]
                if date_from.startswith("-"):
                    # Relative date like "-14d"
                    match = re.match(r"-(\d+)([dhwmy])", date_from)
                    if match:
                        num, unit = match.groups()
                        unit_names = {"d": "day", "h": "hour", "w": "week", "m": "month", "y": "year"}
                        unit_name = unit_names.get(unit, unit)
                        name_parts.append(f"from last {num} {unit_name}{'s' if int(num) > 1 else ''}")

        return " ".join(name_parts) if name_parts else "Error tracking filters"

    @property
    def _model(self):
        return MaxChatAnthropic(
            model="claude-sonnet-4-5",
            temperature=0.3,
            streaming=False,
            user=self._user,
            team=self._team,
            billable=True,
            inject_context=False,
        )

    def _parse_output(self, output: str) -> dict[str, Any]:
        """Parse the LLM output and return the filters as a dict."""
        match = re.search(r"<output>(.*?)</output>", output, re.DOTALL)
        if not match:
            # The model may have returned the JSON without tags, or with markdown
            json_str = re.sub(
                r"^\s*```json\s*\n(.*?)\n\s*```\s*$", r"\1", output, flags=re.DOTALL | re.MULTILINE
            ).strip()
        else:
            json_str = match.group(1).strip()

        if not json_str:
            raise PydanticOutputParserException(
                llm_output=output, validation_message="The model returned an empty filters response."
            )

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise PydanticOutputParserException(
                llm_output=json_str, validation_message=f"The filters JSON failed to parse: {str(e)}"
            )

        return data


class ErrorTrackingExplainIssueOutput(BaseModel):
    """Structured output for issue explanation"""

    generic_description: str = Field(description="A comprehensive technical explanation of the root cause")
    specific_problem: str = Field(description="A detailed summary of exactly how the issue occurs")
    possible_resolutions: list[str] = Field(
        description="A list of potential solutions or mitigations to the issue", max_length=3
    )


class ExplainIssueArgs(BaseModel):
    issue_id: str | None = Field(
        default=None,
        description="The ID of the error tracking issue to explain. If omitted, the tool will try to use the injected `issue_id` from contextual tool context.",
    )


class ErrorTrackingExplainIssueTool(MaxTool):
    name: str = "error_tracking_explain_issue"
    description: str = "Given an error tracking issue ID, fetch its stack trace and provide a summary of the problem and potential resolutions."
    args_schema: type[BaseModel] = ExplainIssueArgs
    context_prompt_template: str = """The user is currently viewing an error tracking issue. Here is that issue's context:

```json
{issue_id}
```

When the user says "this issue", they mean the issue with this ID. Use it when calling this tool if the user didn't specify an explicit issue ID.
""".strip()

    async def _arun_impl(self, issue_id: str | None = None) -> tuple[str, dict[str, Any]]:
        # Allow contextual injection (dashboard-style) so "explain this issue" works without the user specifying an ID.
        if not issue_id:
            issue_id = self.context.get("issue_id") if isinstance(self.context, dict) else None

        if not issue_id:
            return (
                "I need an error tracking issue ID to explain. Please open an issue page or provide the issue ID.",
                {},
            )

        # Fetch the issue from the database
        issue = await self._fetch_issue(issue_id)
        if not issue:
            return f"Error tracking issue with ID '{issue_id}' not found.", {}

        # Fetch the latest exception event and extract stacktrace
        stacktrace = await self._fetch_stacktrace(issue_id)
        if not stacktrace:
            return f"No exception events found for issue '{issue_id}'. Cannot explain without a stack trace.", {}

        issue_name = issue.name or f"Issue {issue_id}"

        # Analyze the issue
        analyzed_issue = await self._analyze_issue(stacktrace)
        formatted_explanation = self._format_explanation_for_user(analyzed_issue, issue_name)

        user_message = f"Return this content to the user as is, following this format.\n\n{formatted_explanation}"

        return user_message, {}

    @database_sync_to_async
    def _fetch_issue(self, issue_id: str) -> ErrorTrackingIssue | None:
        """Fetch the error tracking issue from the database."""
        return _fetch_error_tracking_issue(self._team.id, issue_id)

    @database_sync_to_async
    def _fetch_stacktrace(self, issue_id: str) -> str | None:
        """Fetch the latest exception event for the issue and format the stacktrace."""
        # Query for the latest exception event for this issue
        query = ast.SelectQuery(
            select=[
                ast.Field(chain=["properties"]),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["event"]),
                        right=ast.Constant(value="$exception"),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["properties", "$exception_issue_id"]),
                        right=ast.Constant(value=issue_id),
                    ),
                ]
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            limit=ast.Constant(value=1),
        )

        try:
            result = execute_hogql_query(query=query, team=self._team)
            if not result.results or len(result.results) == 0:
                return None

            properties = result.results[0][0]
            if isinstance(properties, str):
                properties = json.loads(properties)

            return self._format_stacktrace_from_properties(properties)
        except Exception:
            return None

    def _format_stacktrace_from_properties(self, properties: dict) -> str:
        """Format the stacktrace from exception event properties."""
        exception_list = properties.get("$exception_list", [])
        if not exception_list:
            # Fallback to legacy format
            exception_types = properties.get("$exception_types", [])
            exception_values = properties.get("$exception_values", [])
            if exception_types and exception_values:
                return f"{exception_types[0]}: {exception_values[0]}"
            return ""

        lines = []
        for exception in exception_list:
            exc_type = exception.get("type", "Unknown")
            exc_value = exception.get("value", "")
            lines.append(f"{exc_type}{': ' + exc_value if exc_value else ''}")

            stacktrace = exception.get("stacktrace", {})
            frames = stacktrace.get("frames", [])

            for frame in frames:
                in_app = frame.get("in_app", False)
                in_app_marker = " [IN-APP]" if in_app else ""
                source = frame.get("filename") or frame.get("abs_path") or "Unknown Source"
                line_no = frame.get("lineno")
                function = frame.get("function")

                frame_line = f'{in_app_marker}  File "{source}"'
                if line_no:
                    frame_line += f", line: {line_no}"
                if function:
                    frame_line += f", in: {function}"
                lines.append(frame_line)

                # Include context line if available
                context_line = frame.get("context_line")
                if context_line:
                    lines.append(f"    {context_line}")

        return "\n".join(lines)

    async def _analyze_issue(self, stacktrace: str) -> ErrorTrackingExplainIssueOutput:
        """Analyze an error tracking issue and generate a summary."""
        formatted_prompt = ERROR_TRACKING_EXPLAIN_ISSUE_PROMPT.replace("{{{stacktrace}}}", stacktrace)

        llm = MaxChatAnthropic(
            user=self._user,
            team=self._team,
            model="claude-sonnet-4-5",
            temperature=0.1,
            streaming=False,
            inject_context=False,
        ).with_structured_output(ErrorTrackingExplainIssueOutput)

        analysis_result = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

        # Ensure we return the proper type
        if isinstance(analysis_result, dict):
            return ErrorTrackingExplainIssueOutput(**analysis_result)
        return analysis_result

    def _format_explanation_for_user(self, summary: ErrorTrackingExplainIssueOutput, issue_name: str) -> str:
        lines = []
        lines.append(f"### Issue: {issue_name}")

        lines.append(summary.generic_description)

        lines.append("\n#### What's happening?")
        lines.append(summary.specific_problem)

        lines.append("\n#### How to fix it:")
        for i, option in enumerate(summary.possible_resolutions, 1):
            lines.append(f"{i}. {option}")

        return "\n".join(lines)


class IssueImpactArgs(BaseModel):
    issue_id: str | None = Field(
        default=None,
        description="The ID of the error tracking issue to analyze impact for. If omitted, the tool will try to use the injected `issue_id` from contextual tool context.",
    )


class ErrorTrackingIssueImpactTool(MaxTool):
    name: str = "error_tracking_issue_impact"
    description: str = "Analyze the impact of an error tracking issue, including affected users, sessions, trends, and breakdowns by browser/OS/URL. Returns an impact artifact with summary data."
    args_schema: type[BaseModel] = IssueImpactArgs
    context_prompt_template: str = """The user is currently viewing an error tracking issue. Here is that issue's context:

```json
{issue_id}
```

When the user says "this issue" or asks about "impact", they mean the issue with this ID. Use it when calling this tool if the user didn't specify an explicit issue ID.
""".strip()

    async def _arun_impl(self, issue_id: str | None = None) -> tuple[str, ToolMessagesArtifact | None]:
        # Allow contextual injection so "show impact of this issue" works without the user specifying an ID.
        if not issue_id:
            issue_id = self.context.get("issue_id") if isinstance(self.context, dict) else None

        if not issue_id:
            return (
                "I need an error tracking issue ID to analyze impact. Please open an issue page or provide the issue ID.",
                None,
            )

        issue = await self._fetch_issue(issue_id)
        if not issue:
            return f"Error tracking issue with ID '{issue_id}' not found.", None

        aggregations = await self._fetch_aggregations(issue_id)
        if not aggregations:
            return f"No data found for issue '{issue_id}'.", None

        breakdowns = await self._fetch_breakdowns(issue_id)

        trend, trend_percentage = await self._calculate_trend(issue_id)

        # Create artifact content
        issue_first_seen = getattr(issue, "first_seen", None)
        content = ErrorTrackingImpactArtifactContent(
            issue_id=issue_id,
            issue_name=issue.name or f"Issue {issue_id}",
            occurrences=aggregations.get("occurrences", 0),
            users_affected=aggregations.get("users", 0),
            sessions_affected=aggregations.get("sessions", 0),
            first_seen=issue_first_seen.isoformat() if issue_first_seen else None,
            last_seen=aggregations.get("last_seen"),
            trend=trend,
            trend_percentage=trend_percentage,
            top_browsers=breakdowns.get("$browser"),
            top_os=breakdowns.get("$os"),
            top_urls=breakdowns.get("$current_url"),
        )

        artifact_name = f"Impact: {issue.name or issue_id}"
        artifact = await self._context_manager.artifacts.create_error_tracking_impact(
            content=content, name=artifact_name
        )

        artifact_ref_message = ArtifactRefMessage(
            id=str(uuid4()),
            content_type=ArtifactContentType.ERROR_TRACKING_IMPACT,
            artifact_id=artifact.short_id,
            source=ArtifactSource.ARTIFACT,
        )

        # Create tool call message with summary
        summary = f"Impact analysis for '{issue.name or issue_id}': {aggregations.get('occurrences', 0):,} occurrences affecting {aggregations.get('users', 0):,} users. Trend: {trend}."
        tool_call_message = AssistantToolCallMessage(
            content=summary,
            id=str(uuid4()),
            tool_call_id=self.tool_call_id,
        )

        return "", ToolMessagesArtifact(messages=[artifact_ref_message, tool_call_message])

    @database_sync_to_async
    def _fetch_issue(self, issue_id: str) -> ErrorTrackingIssue | None:
        """Fetch the error tracking issue from the database with first_seen annotation."""
        return _fetch_error_tracking_issue(self._team.id, issue_id, with_first_seen=True)

    async def _fetch_aggregations(self, issue_id: str) -> dict[str, Any] | None:
        """Fetch aggregations for the issue using ErrorTrackingIssueContext."""
        context = ErrorTrackingIssueContext(
            team=self._team,
            issue_id=issue_id,
            date_from="-30d",
        )
        result = await context.execute()
        if not result:
            return None

        return {
            "occurrences": result.occurrences or 0,
            "users": result.users or 0,
            "sessions": result.sessions or 0,
            "last_seen": result.last_seen,
        }

    @database_sync_to_async
    def _fetch_breakdowns(self, issue_id: str) -> dict[str, list[ErrorTrackingImpactSegment]]:
        """Fetch breakdowns by browser, OS, and URL."""
        query = ErrorTrackingBreakdownsQuery(
            issueId=issue_id,
            breakdownProperties=["$browser", "$os", "$current_url"],
            dateRange={"date_from": "-30d"},
            filterTestAccounts=False,
            maxValuesPerProperty=5,
        )

        result: dict[str, list[ErrorTrackingImpactSegment]] = {}

        try:
            runner = get_query_runner(query, team=self._team)
            response = runner.calculate()

            if not response.results:
                return result

            for breakdown in response.results:
                prop = breakdown.property if hasattr(breakdown, "property") else None
                if not prop:
                    continue

                segments: list[ErrorTrackingImpactSegment] = []
                values = breakdown.values if hasattr(breakdown, "values") else []
                total = sum(v.count for v in values if hasattr(v, "count"))

                for value in values[:5]:
                    if hasattr(value, "value") and hasattr(value, "count"):
                        percentage = (value.count / total * 100) if total > 0 else 0
                        segments.append(
                            ErrorTrackingImpactSegment(
                                value=str(value.value) if value.value else "Unknown",
                                count=value.count,
                                percentage=round(percentage, 1),
                            )
                        )

                if segments:
                    result[prop] = segments

            return result
        except Exception:
            return result

    @database_sync_to_async
    def _calculate_trend(self, issue_id: str) -> tuple[str, float | None]:
        """Calculate trend by comparing current vs previous period."""
        # Current period: last 7 days
        current_query = ErrorTrackingQuery(
            issueId=issue_id,
            dateRange={"date_from": "-7d"},
            orderBy=OrderBy1.LAST_SEEN,
            volumeResolution=1,
            withAggregations=True,
            filterTestAccounts=False,
        )

        # Previous period: 7-14 days ago
        previous_query = ErrorTrackingQuery(
            issueId=issue_id,
            dateRange={"date_from": "-14d", "date_to": "-7d"},
            orderBy=OrderBy1.LAST_SEEN,
            volumeResolution=1,
            withAggregations=True,
            filterTestAccounts=False,
        )

        try:
            current_runner = get_query_runner(current_query, team=self._team)
            current_response = current_runner.calculate()
            current_count = 0
            if current_response.results and len(current_response.results) > 0:
                agg = (
                    current_response.results[0].aggregations
                    if hasattr(current_response.results[0], "aggregations")
                    else None
                )
                if agg:
                    current_count = agg.occurrences or 0

            previous_runner = get_query_runner(previous_query, team=self._team)
            previous_response = previous_runner.calculate()
            previous_count = 0
            if previous_response.results and len(previous_response.results) > 0:
                agg = (
                    previous_response.results[0].aggregations
                    if hasattr(previous_response.results[0], "aggregations")
                    else None
                )
                if agg:
                    previous_count = agg.occurrences or 0

            if previous_count == 0 and current_count == 0:
                return "stable", None
            elif previous_count == 0:
                return "increasing", None
            else:
                change = ((current_count - previous_count) / previous_count) * 100
                if change > 10:
                    return "increasing", round(change, 1)
                elif change < -10:
                    return "decreasing", round(change, 1)
                else:
                    return "stable", round(change, 1)
        except Exception:
            return "stable", None
