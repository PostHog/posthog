import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, overload

from django.db import models

from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.models import Team

logger = logging.getLogger(__name__)


@overload
def _parse_json_value(value: Any, default: dict[str, Any]) -> dict[str, Any]: ...


@overload
def _parse_json_value(value: Any, default: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


def _parse_json_value(
    value: Any, default: dict[str, Any] | list[dict[str, Any]]
) -> dict[str, Any] | list[dict[str, Any]]:
    if value is None or value == "":
        return default

    parsed = json.loads(value) if isinstance(value, str) else value
    if isinstance(default, dict) and isinstance(parsed, dict):
        return parsed
    if isinstance(default, list) and isinstance(parsed, list):
        return parsed

    raise TypeError(f"Expected {type(default).__name__}, got {type(parsed).__name__}")


@dataclass
class BreakpointHit:
    """
    Represents a single breakpoint hit event.
    """

    id: str
    timestamp: str
    breakpoint_id: str
    line_number: Optional[int]
    filename: str
    function_name: str
    locals: dict[str, Any]
    stack_trace: list[dict[str, Any]]

    def to_json(self) -> dict[str, Any]:
        """
        Convert the breakpoint hit to JSON format with camelCase keys for the API.
        """
        return {
            "id": self.id,
            "lineNumber": self.line_number,
            "functionName": self.function_name,
            "timestamp": self.timestamp,
            "variables": self.locals,
            "stackTrace": self.stack_trace,
            "breakpoint_id": self.breakpoint_id,
            "filename": self.filename,
        }


class LiveDebuggerBreakpoint(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    repository = models.TextField(null=True, blank=True)  # Format: "owner/repo" (e.g., "PostHog/posthog")
    filename = models.TextField()
    line_number = models.PositiveIntegerField()
    enabled = models.BooleanField(default=True)
    condition = models.TextField(blank=True, null=True)  # Optional condition for conditional breakpoints
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_livedebuggerbreakpoint"
        managed = True
        constraints = [
            models.UniqueConstraint(
                fields=["team", "repository", "filename", "line_number"],
                name="unique_breakpoint_per_line_per_file_per_repo_per_team",
            )
        ]
        indexes = [
            models.Index(fields=["team_id", "repository"], name="live_debug_team_repo_idx"),
        ]

    def __str__(self) -> str:
        repo_str = f"{self.repository}/" if self.repository else ""
        return f"Breakpoint at {repo_str}{self.filename}:{self.line_number} for team {self.team.pk}"

    @classmethod
    def get_breakpoint_hits(
        cls,
        team: "Team",
        breakpoint_ids: Optional[list] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BreakpointHit]:
        """
        Query ClickHouse for breakpoint hit events using HogQL.

        Returns a list of BreakpointHit dataclass instances.
        """
        from posthog.hogql import ast
        from posthog.hogql.parser import parse_select
        from posthog.hogql.query import execute_hogql_query

        # Build WHERE conditions (team_id filter is automatically added by execute_hogql_query)
        where_conditions = [
            "event = {event_name}",
            "timestamp >= now() - INTERVAL 1 HOUR",
        ]

        placeholders: dict[str, ast.Expr] = {
            "event_name": ast.Constant(value="$data_breakpoint_hit"),
            "limit": ast.Constant(value=limit),
            "offset": ast.Constant(value=offset),
        }

        if breakpoint_ids:
            # Convert UUIDs to strings for the IN clause
            breakpoint_id_strings = [str(bp_id) for bp_id in breakpoint_ids]
            where_conditions.append("properties.$breakpoint_id IN {breakpoint_ids}")
            placeholders["breakpoint_ids"] = ast.Constant(value=breakpoint_id_strings)

        where_clause = " AND ".join(where_conditions)

        query = parse_select(
            f"""
            SELECT
                uuid,
                timestamp,
                properties
            FROM events
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT {{limit}} OFFSET {{offset}}
            """,
            placeholders=placeholders,
        )

        logger.info(f"Executing breakpoint hits query for team_id={team.pk}, limit={limit}, offset={offset}")
        response = execute_hogql_query(query, team=team)
        results = response.results or []
        logger.info(f"Query returned {len(results)} results")

        # Process results to return structured data
        processed_results = []

        for row in results:
            try:
                properties = _parse_json_value(row[2], {})
                locals_data = _parse_json_value(properties.get("$locals_variables"), {})
                stack_trace_data = _parse_json_value(properties.get("$stack_trace"), [])
                stack_first = stack_trace_data[0] if stack_trace_data else {}
                function_name = stack_first.get("function", "")
                line_number = properties.get("$line_number")

                processed_results.append(
                    BreakpointHit(
                        id=str(row[0]),
                        timestamp=row[1].isoformat(),
                        breakpoint_id=str(properties.get("$breakpoint_id", "")),
                        line_number=int(line_number) if line_number not in (None, "") else None,
                        filename=str(properties.get("$file_path", "")),
                        function_name=function_name,
                        locals=locals_data,
                        stack_trace=stack_trace_data,
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                # Skip malformed entries
                continue

        return processed_results
