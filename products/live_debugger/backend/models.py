import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from django.db import models

from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.models import Team

logger = logging.getLogger(__name__)


@dataclass
class ProgramEvent:
    """A single event emitted by a live debugger program (e.g. a probe hit).

    Mirrors the property shape that ``libdebugger`` actually emits for the
    ``$hogtrace_capture`` event — see ``libdebugger/instrumentation.py``
    ``_enqueue_message`` for the source of truth.
    """

    id: str
    timestamp: str
    program_id: str
    probe_id: Optional[str]
    probe_spec: Optional[dict[str, Any]]
    captures: dict[str, Any]
    thread_id: Optional[int]
    thread_name: Optional[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "program_id": self.program_id,
            "probe_id": self.probe_id,
            "probe_spec": self.probe_spec,
            "captures": self.captures,
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
        }


class LiveDebuggerProgram(UUIDModel):
    class Status(models.TextChoices):
        INSTALLED = "installed", "Installed"
        UNINSTALLED = "uninstalled", "Uninstalled"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    session = models.ForeignKey(
        "live_debugger.LiveDebuggerSession",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="programs",
    )
    code = models.TextField()
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INSTALLED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_livedebuggerprogram"
        managed = True
        indexes = [
            models.Index(fields=["team_id", "status"], name="live_debug_prog_team_st_idx"),
        ]

    def __str__(self) -> str:
        return f"Program {self.pk} ({self.status}) for team {self.team_id}"

    @classmethod
    def get_program_events(
        cls,
        team: "Team",
        program_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list["ProgramEvent"]:
        """Query ClickHouse for events emitted by a specific program."""
        import json

        from posthog.hogql import ast
        from posthog.hogql.parser import parse_select
        from posthog.hogql.query import execute_hogql_query

        placeholders: dict[str, ast.Expr] = {
            "event_name": ast.Constant(value="$hogtrace_capture"),
            "program_id": ast.Constant(value=str(program_id)),
            "limit": ast.Constant(value=limit),
            "offset": ast.Constant(value=offset),
        }

        query = parse_select(
            """
            SELECT
                uuid,
                timestamp,
                properties.program_id as program_id,
                properties.probe_id as probe_id,
                properties.probe_spec as probe_spec,
                properties.captures as captures,
                properties.thread_id as thread_id,
                properties.thread_name as thread_name
            FROM events
            WHERE event = {event_name}
              AND JSONExtractString(properties, 'program_id') = {program_id}
            ORDER BY timestamp DESC
            LIMIT {limit} OFFSET {offset}
            """,
            placeholders=placeholders,
        )

        response = execute_hogql_query(query, team=team)
        results = response.results or []

        events: list[ProgramEvent] = []
        for row in results:
            try:
                probe_spec = json.loads(row[4]) if row[4] else None
                captures = json.loads(row[5]) if row[5] else {}
                thread_id = int(row[6]) if row[6] is not None else None
                events.append(
                    ProgramEvent(
                        id=str(row[0]),
                        timestamp=row[1].isoformat(),
                        program_id=row[2],
                        probe_id=row[3],
                        probe_spec=probe_spec if isinstance(probe_spec, dict) else None,
                        captures=captures if isinstance(captures, dict) else {},
                        thread_id=thread_id,
                        thread_name=row[7],
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        return events


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
            where_conditions.append("JSONExtractString(properties, '$breakpoint_id') IN {breakpoint_ids}")
            placeholders["breakpoint_ids"] = ast.Constant(value=breakpoint_id_strings)

        where_clause = " AND ".join(where_conditions)

        query = parse_select(
            f"""
            SELECT
                uuid,
                timestamp,
                properties.$breakpoint_id as breakpoint_id,
                properties.$line_number as line_number,
                properties.$file_path as filename,
                arrayElement(JSONExtractArrayRaw(properties, '$stack_trace'), 1) as stack_first,
                properties.$locals_variables as locals,
                properties.$stack_trace as stack_trace,
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
        import json

        for row in results:
            try:
                # Extract function name from first stack trace element
                stack_first = json.loads(row[5]) if row[5] else {}
                function_name = stack_first.get("function", "") if isinstance(stack_first, dict) else ""

                locals_data = json.loads(row[6]) if row[6] else {}
                stack_trace_data = json.loads(row[7]) if row[7] else []

                processed_results.append(
                    BreakpointHit(
                        id=str(row[0]),
                        timestamp=row[1].isoformat(),
                        breakpoint_id=row[2],
                        line_number=int(row[3]) if row[3] else None,
                        filename=row[4],
                        function_name=function_name,
                        locals=locals_data,
                        stack_trace=stack_trace_data,
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                # Skip malformed entries
                continue

        return processed_results


class LiveDebuggerSession(UUIDModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    title = models.TextField()
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_livedebuggersession"
        managed = True
        indexes = [
            models.Index(fields=["team_id", "status"], name="live_debug_sess_team_st_idx"),
        ]

    def __str__(self) -> str:
        return f"Session {self.pk} ({self.status}) for team {self.team_id}"


class LiveDebuggerSessionEntry(UUIDModel):
    class Kind(models.TextChoices):
        NOTE = "note", "Note"
        PROGRAM_INSTALL = "program_install", "Program install"
        PROGRAM_UNINSTALL = "program_uninstall", "Program uninstall"
        EVENT_HIGHLIGHT = "event_highlight", "Event highlight"
        CONCLUSION = "conclusion", "Conclusion"

    session = models.ForeignKey(LiveDebuggerSession, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_livedebuggersessionentry"
        managed = True
        indexes = [
            models.Index(fields=["session_id", "created_at"], name="live_debug_entry_sess_ts_idx"),
        ]

    def __str__(self) -> str:
        return f"Entry {self.pk} ({self.kind}) in session {self.session_id}"
