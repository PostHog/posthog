from datetime import UTC
from typing import Literal

from django.utils import timezone

import structlog
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import ErrorTrackingIssue, ErrorTrackingIssueStatus, ErrorTrackingQuery

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.tool import MaxTool, ToolMessagesArtifact
from ee.hogai.tool_errors import MaxToolRetryableError

logger = structlog.get_logger(__name__)


SEARCH_QUERY_EXAMPLES = """
# Examples

## Status filtering
- "Show me active errors" → status: "active"
- "What resolved issues do we have?" → status: "resolved"
- "Show suppressed errors" → status: "suppressed"

## Text search
- "TypeError errors" → searchQuery: "TypeError"
- "Errors mentioning 'undefined'" → searchQuery: "undefined"
- "Find null pointer exceptions" → searchQuery: "null pointer"

## Date range
- "Errors from last 7 days" → dateRange: { date_from: "-7d" }
- "Issues since last week" → dateRange: { date_from: "-7d" }
- "Errors from December" → dateRange: { date_from: "2024-12-01", date_to: "2024-12-31" }

## Ordering
- "Most frequent errors" → orderBy: "occurrences", orderDirection: "DESC"
- "Newest errors first" → orderBy: "first_seen", orderDirection: "DESC"
- "Most recent errors" → orderBy: "last_seen", orderDirection: "DESC"
- "Errors affecting most users" → orderBy: "users", orderDirection: "DESC"

## Combined queries
- "Active TypeError errors from last week" → status: "active", searchQuery: "TypeError", dateRange: { date_from: "-7d" }
- "Top 10 most frequent resolved issues" → status: "resolved", orderBy: "occurrences", limit: 10
"""

QUERY_FIELD_DESCRIPTION = f"""
User's question converted into an error tracking query.

# Query Structure

## status (optional)
Filter by issue status:
- "active": Currently active issues (default if not specified)
- "resolved": Issues marked as resolved
- "pending_release": Issues pending a release
- "suppressed": Suppressed/muted issues
- "archived": Archived issues
- "all": Show all issues regardless of status

## searchQuery (optional)
Free text search across:
- Exception type (e.g., "TypeError", "ReferenceError")
- Exception message
- Function names in stack traces
- File paths in stack traces

## dateRange (REQUIRED)
Time range for the query:
- date_from: Start date (relative like "-7d", "-30d" or absolute "2024-12-01")
- date_to: End date (null for "until now", or absolute date)

Common relative formats:
- "-7d" = last 7 days
- "-30d" = last 30 days
- "-24h" = last 24 hours

Note: All dates in results are displayed in UTC timezone.

## orderBy (REQUIRED)
Sort results by:
- "last_seen": When the issue was last seen (most recent activity)
- "first_seen": When the issue first appeared
- "occurrences": Total occurrence count
- "users": Number of affected users
- "sessions": Number of affected sessions
- "revenue": Revenue impact (if configured)

## orderDirection (optional)
- "DESC": Descending (default, highest/newest first)
- "ASC": Ascending (lowest/oldest first)

## limit (optional)
Number of results to return (1-100, default 25)

## filterGroup (optional)
Property filters for advanced filtering. Structure:
{{
    "type": "AND" | "OR",
    "values": [
        {{
            "type": "AND" | "OR",
            "values": [
                {{
                    "type": "event" | "person" | "session",
                    "key": "property_name",
                    "value": "value_or_array",
                    "operator": "exact" | "icontains" | "is_set" | ...
                }}
            ]
        }}
    ]
}}

Common filter properties:
- event.$browser: Browser type
- event.$os: Operating system
- event.$device_type: Device type (Desktop, Mobile, Tablet)
- event.$current_url: URL where error occurred
- event.$lib: SDK/library used (web, posthog-python, posthog-node, etc.)

## filterTestAccounts (optional)
- true: Exclude internal/test accounts
- false: Include all accounts

## volumeResolution (REQUIRED)
Resolution for volume chart data. Use 1 for daily buckets.

{SEARCH_QUERY_EXAMPLES}
""".strip()

TOOL_DESCRIPTION = """
Search for error tracking issues based on criteria like status, search text, date range, and ordering.

# When to use this tool:
- User asks to find, search, or list error tracking issues
- User asks about errors, exceptions, or issues in their application
- User wants to filter errors by status, date, frequency, or other criteria
- User asks questions like "show me recent errors" or "what are the most common issues"

# What this tool returns:
A formatted list of matching issues with their name, status, occurrence count, and other key metrics.
All timestamps are in UTC timezone.
""".strip()


class SearchErrorTrackingIssuesArgs(BaseModel):
    query: ErrorTrackingQuery = Field(description=QUERY_FIELD_DESCRIPTION)


class SearchErrorTrackingIssuesTool(MaxTool):
    name: Literal["search_error_tracking_issues"] = "search_error_tracking_issues"
    args_schema: type[BaseModel] = SearchErrorTrackingIssuesArgs
    description: str = TOOL_DESCRIPTION

    async def _arun_impl(self, query: ErrorTrackingQuery) -> tuple[str, ToolMessagesArtifact | None]:
        # Adding some sane default limits
        if query.limit is None or query.limit <= 0:
            query.limit = 25
        elif query.limit > 100:
            query.limit = 100

        # Default to active issues if no status specified
        if query.status is None:
            query.status = ErrorTrackingIssueStatus.ACTIVE

        try:
            utc_now = timezone.now().astimezone(UTC)
            executor = AssistantQueryExecutor(self._team, utc_now)
            query_results = await executor.aexecute_query(query)
        except MaxToolRetryableError:
            raise
        except Exception as e:
            capture_exception(e)
            logger.exception("Error executing error tracking query", error=str(e))
            return f"Error searching for issues: {e}", None

        return self._format_results(query_results), None

    def _format_results(self, response: dict) -> str:
        """Format query results as text output."""
        results = response.get("results", [])

        if not results:
            return "No issues found matching your criteria."

        total_count = len(results)
        if total_count == 1:
            content = "Found 1 issue matching your criteria:\n\n"
        else:
            content = f"Found {total_count} issues matching your criteria:\n\n"

        # Show up to 10 issues in the response
        for i, issue in enumerate(results[:10], 1):
            content += self._format_issue(i, ErrorTrackingIssue.model_validate(issue))

        if total_count > 10:
            content += f"\n...and {total_count - 10} more issues"

        return content

    def _format_issue(self, index: int, issue: ErrorTrackingIssue) -> str:
        """Format a single issue for display."""
        name = issue.name or "Unnamed issue"
        status = issue.status or "unknown"
        first_seen = issue.first_seen
        last_seen = issue.last_seen

        aggregations = issue.aggregations
        if aggregations:
            occurrences = int(aggregations.occurrences or 0)
            users = int(aggregations.users or 0)
            sessions = int(aggregations.sessions or 0)
        else:
            occurrences = 0
            users = 0
            sessions = 0

        first_seen_str = self._format_date(first_seen)
        last_seen_str = self._format_date(last_seen)

        lines = [f"{index}. {name}"]
        lines.append(f"   Status: {status} | Occurrences: {occurrences:,} | Users: {users:,} | Sessions: {sessions:,}")

        if first_seen_str or last_seen_str:
            date_parts = []
            if first_seen_str:
                date_parts.append(f"First seen: {first_seen_str}")
            if last_seen_str:
                date_parts.append(f"Last seen: {last_seen_str}")
            lines.append(f"   {' | '.join(date_parts)}")

        # Empty line between issues for formatting
        lines.append("")
        return "\n".join(lines)

    def _format_date(self, date_value) -> str:
        """Format a date value for display in UTC."""
        if not date_value:
            return ""
        from datetime import datetime

        try:
            if isinstance(date_value, datetime):
                return date_value.strftime("%Y-%m-%d %H:%M UTC")
            elif isinstance(date_value, str):
                dt = datetime.fromisoformat(date_value.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, AttributeError):
            return str(date_value) if date_value else ""
        return ""
