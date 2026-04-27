import json
from datetime import UTC
from textwrap import dedent
from typing import Any, Literal, cast

from django.utils import timezone

import structlog
from posthoganalytics import capture_exception
from pydantic import BaseModel, Field

from posthog.schema import (
    ErrorTrackingIssue,
    ErrorTrackingIssueStatus,
    ErrorTrackingQuery,
    FilterLogicalOperator,
    MaxErrorTrackingIssuePreview,
    MaxErrorTrackingSearchResponse,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
)

from ee.hogai.context.insight.query_executor import AssistantQueryExecutor
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

logger = structlog.get_logger(__name__)


EXTENSION_FRAME_SCHEMES = (
    "chrome-extension://",
    "moz-extension://",
    "safari-extension://",
    "safari-web-extension://",
)
THIRD_PARTY_SCRIPT_ERROR_VALUES = {"Script error.", "Script error"}


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


class SearchErrorTrackingIssuesArgs(BaseModel):
    query: ErrorTrackingQuery = Field(
        description=dedent("""
        User's question converted into an error tracking query.

        IMPORTANT: When the user asks to "show more" or "next page", you should pass the cursor
        from the previous response to continue pagination. Do NOT modify the query parameters.""").strip()
        + dedent(f"""

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
        Number of results to return (1-100, default 50)

        ## filterGroup (optional)
        Property filters for advanced filtering. Structure:
        {{{{
            "type": "AND" | "OR",
            "values": [
                {{{{
                    "type": "AND" | "OR",
                    "values": [
                        {{{{
                            "type": "event" | "person" | "session",
                            "key": "property_name",
                            "value": "value_or_array",
                            "operator": "exact" | "icontains" | "is_set" | ...
                        }}}}
                    ]
                }}}}
            ]
        }}}}

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
        """).strip()
    )
    cursor: str | None = Field(
        default=None,
        description="Pagination cursor from previous search results. Pass this to get the next page of results.",
    )


class SearchErrorTrackingIssuesTool(MaxTool):
    name: Literal["search_error_tracking_issues"] = "search_error_tracking_issues"
    args_schema: type[BaseModel] = SearchErrorTrackingIssuesArgs
    description: str = dedent("""
        Search for error tracking issues based on criteria like status, search text, date range, and ordering.

        # When to use this tool:
        - User asks to find, search, or list error tracking issues
        - User asks about errors, exceptions, or issues in their application
        - User wants to filter errors by status, date, frequency, or other criteria
        - User asks questions like "show me recent errors" or "what are the most common issues"
        - User asks to "show more" or see "next page" of results (use the cursor from previous results)

        # What this tool returns:
        A formatted list of matching issues with their name, status, occurrence count, and other key metrics.
        If more results are available, a cursor will be provided for pagination.
        All timestamps are in UTC timezone.
        """).strip()

    def get_required_resource_access(self):
        return [("error_tracking", "viewer")]

    async def _arun_impl(
        self, query: ErrorTrackingQuery, cursor: str | None = None
    ) -> tuple[str, MaxErrorTrackingSearchResponse | None]:
        # Ensure reasonable defaults to match dashboard behavior
        if query.limit is None or query.limit <= 0:
            query.limit = 50  # Match dashboard default
        elif query.limit > 100:
            query.limit = 100

        # Default to active issues if no status specified
        if query.status is None:
            query.status = ErrorTrackingIssueStatus.ACTIVE

        # Ensure query parameters match dashboard defaults
        query.withAggregations = True
        # Pull the first event so we can surface URL/library context and detect cross-origin
        # script / extension noise. This costs a little more per row but is bounded by `limit`,
        # and the AI agent's debugging value depends on having this context per-issue.
        query.withFirstEvent = True
        if query.filterTestAccounts is None:
            query.filterTestAccounts = False
        # Set empty filterGroup if not provided (matches dashboard behavior)
        if query.filterGroup is None:
            query.filterGroup = PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
            )
        # Set searchQuery to empty string if None (matches dashboard behavior)
        if query.searchQuery is None:
            query.searchQuery = ""

        # Apply cursor offset for pagination (default to 0 to match dashboard behavior)
        current_offset = 0
        if cursor:
            try:
                current_offset = int(cursor)
            except ValueError:
                logger.warning("Invalid pagination cursor", cursor=cursor)
        query.offset = current_offset

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

        # Extract results and pagination info from response
        # Note: executor returns dict with extra caching fields, so we validate issues individually
        raw_results = cast(list[dict], query_results.get("results", []))
        results = [ErrorTrackingIssue.model_validate(r) for r in raw_results]
        has_more_from_response = cast(bool, query_results.get("hasMore", False))

        # Use has_more from paginator response (based on ClickHouse results before Postgres filtering)
        # Fall back to comparing result count vs limit if not available
        has_more = has_more_from_response if has_more_from_response else len(results) >= query.limit
        next_cursor = str(current_offset + query.limit) if has_more else None

        content = self._format_results(results, has_more)
        issue_previews = self._build_issue_previews(results)

        filters = MaxErrorTrackingSearchResponse(
            status=query.status,
            search_query=query.searchQuery,
            date_from=query.dateRange.date_from if query.dateRange else None,
            date_to=query.dateRange.date_to if query.dateRange else None,
            order_by=query.orderBy,
            order_direction=query.orderDirection,
            limit=query.limit,
            has_more=has_more,
            next_cursor=next_cursor,
            issues=issue_previews,
        )

        return content, filters

    def _build_issue_previews(self, results: list[ErrorTrackingIssue]) -> list[MaxErrorTrackingIssuePreview]:
        """Build issue preview objects for frontend display."""
        previews = []
        for issue in results:
            aggregations = issue.aggregations
            properties = self._first_event_properties(issue)

            previews.append(
                MaxErrorTrackingIssuePreview(
                    id=issue.id or "",
                    name=issue.name,
                    description=issue.description or self._extract_exception_message(issue),
                    status=issue.status or "unknown",
                    library=issue.library,
                    url=self._extract_url(properties),
                    source=getattr(issue, "source", None),
                    noise_reason=self._detect_noise_reason(issue, properties),
                    first_seen=self._format_date(issue.first_seen) or None,
                    last_seen=self._format_date(issue.last_seen) or None,
                    occurrences=int(aggregations.occurrences) if aggregations else 0,
                    users=int(aggregations.users) if aggregations else 0,
                    sessions=int(aggregations.sessions) if aggregations else 0,
                )
            )
        return previews

    def _format_results(self, results: list[ErrorTrackingIssue], has_more: bool = False) -> str:
        """Format query results as text output."""

        if not results:
            return "No issues found matching your criteria."

        total_count = len(results)
        if total_count == 1:
            content = "Found 1 issue matching your criteria:\n\n"
        else:
            content = f"Found {total_count} issues matching your criteria:\n\n"

        # Show up to 10 issues in the response
        for i, issue in enumerate(results[:10], 1):
            content += self._format_issue(i, issue)

        if total_count > 10:
            content += f"\n...and {total_count - 10} more issues in this batch"

        if has_more:
            content += "\n\nMore issues are available. Ask me to show more if needed."

        return content

    def _format_issue(self, index: int, issue: ErrorTrackingIssue) -> str:
        """Format a single issue for display."""
        issue_id = issue.id or ""
        name = issue.name or "Unnamed issue"
        properties = self._first_event_properties(issue)
        description = issue.description or self._extract_exception_message(issue)
        status = issue.status or "unknown"
        first_seen = issue.first_seen
        last_seen = issue.last_seen
        library = issue.library
        url = self._extract_url(properties)
        noise_reason = self._detect_noise_reason(issue, properties)

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

        title_suffix = " [LIKELY THIRD-PARTY NOISE]" if noise_reason else ""
        lines = [f"{index}. {name}{title_suffix}"]
        if description:
            # Truncate long descriptions
            desc_display = description[:100] + "..." if len(description) > 100 else description
            lines.append(f"   {desc_display}")
        lines.append(f"   ID: {issue_id}")
        lines.append(f"   Status: {status} | Occurrences: {occurrences:,} | Users: {users:,} | Sessions: {sessions:,}")

        environment_parts: list[str] = []
        if library:
            environment_parts.append(f"Library: {library}")
        if url:
            environment_parts.append(f"URL: {url}")
        if environment_parts:
            lines.append(f"   {' | '.join(environment_parts)}")

        if noise_reason:
            lines.append(f"   Noise: {noise_reason} — likely not actionable")

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

    def _extract_exception_message(self, issue: ErrorTrackingIssue) -> str | None:
        """Extract exception message from first_event properties."""
        properties = self._first_event_properties(issue)
        exception_list = properties.get("$exception_list", []) or []
        if exception_list and isinstance(exception_list[0], dict):
            value = exception_list[0].get("value")
            if value:
                return value
        return None

    @staticmethod
    def _first_event_properties(issue: ErrorTrackingIssue) -> dict[str, Any]:
        """Decode `first_event.properties` (always serialized as a JSON string) safely."""
        first_event = getattr(issue, "first_event", None)
        if not first_event:
            return {}
        properties = getattr(first_event, "properties", None)
        if not properties:
            return {}
        try:
            decoded = json.loads(properties) if isinstance(properties, str) else properties
        except (json.JSONDecodeError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _extract_url(properties: dict[str, Any]) -> str | None:
        url = properties.get("$current_url")
        return url if isinstance(url, str) and url else None

    @classmethod
    def _detect_noise_reason(
        cls, issue: ErrorTrackingIssue, properties: dict[str, Any]
    ) -> str | None:
        """Return a human-readable reason if the issue is likely third-party noise.

        Mirrors `getThirdPartyNoiseReason` in the frontend so AI consumers and the
        UI agree on what counts as noise. We check both the issue-level fields
        (already in the listing query result) and the captured first-event frames.
        """

        def is_script_error(value: Any) -> bool:
            return isinstance(value, str) and value.strip() in THIRD_PARTY_SCRIPT_ERROR_VALUES

        if is_script_error(issue.description) or is_script_error(issue.name):
            return "Cross-origin 'Script error.' with no usable stack frames"

        source = getattr(issue, "source", None)
        if isinstance(source, str) and source.startswith(EXTENSION_FRAME_SCHEMES):
            return "Top frame is from a browser extension"

        exception_list = properties.get("$exception_list", []) or []
        for exception in exception_list:
            if not isinstance(exception, dict):
                continue
            if is_script_error(exception.get("value")):
                return "Cross-origin 'Script error.' with no usable stack frames"
            stacktrace = exception.get("stacktrace") or {}
            frames = stacktrace.get("frames", []) if isinstance(stacktrace, dict) else []
            if frames and all(cls._frame_is_extension(frame) for frame in frames):
                return "All stack frames are from a browser extension"

        return None

    @staticmethod
    def _frame_is_extension(frame: Any) -> bool:
        if not isinstance(frame, dict):
            return False
        for key in ("source", "abs_path", "filename"):
            value = frame.get(key)
            if isinstance(value, str) and value.startswith(EXTENSION_FRAME_SCHEMES):
                return True
        return False

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
        return str(date_value)
