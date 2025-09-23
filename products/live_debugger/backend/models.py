import logging
from typing import Optional

from django.db import models

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import UUIDModel

logger = logging.getLogger(__name__)


class LiveDebuggerBreakpoint(UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
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
                fields=["team", "filename", "line_number"], name="unique_breakpoint_per_line_per_file_per_team"
            )
        ]

    def __str__(self):
        return f"Breakpoint at {self.filename}:{self.line_number} for team {self.team_id}"

    @classmethod
    def get_breakpoint_hits(
        cls, team_id: int, breakpoint_id: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """
        Query ClickHouse for breakpoint hit events.

        Returns a list of breakpoint hit instances with structure:
        {
            'id': event_uuid,
            'timestamp': event_timestamp,
            'breakpoint_id': breakpoint_id_from_properties,
            'line_number': line_number_from_properties,
            'filename': filename_from_properties,
            'locals': locals_dict_from_properties,
            'function_name': function_name_from_properties,
            'stack_trace': stack_trace_from_properties
        }
        """
        # Only get events from the last hour to ensure freshness
        where_clause = (
            "WHERE team_id = %(team_id)s AND event = '$data_breakpoint_hit' AND timestamp >= now() - INTERVAL 1 HOUR"
        )
        params = {
            "team_id": team_id,
            "limit": limit,
            "offset": offset,
        }

        if breakpoint_id:
            where_clause += " AND JSONExtractString(properties, '$breakpoint_id') = %(breakpoint_id)s"
            params["breakpoint_id"] = breakpoint_id

        query = f"""
        SELECT
            uuid,
            timestamp,
            JSONExtractString(properties, '$breakpoint_id') as breakpoint_id,
            JSONExtractInt(properties, '$line_number') as line_number,
            JSONExtractString(properties, '$file_path') as filename,
            JSONExtractString(properties, '$stack_trace[1].function') as function_name,
            JSONExtractRaw(properties, '$locals_variables') as locals,
            JSONExtractRaw(properties, '$stack_trace') as stack_trace,
            properties
        FROM events
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """

        logger.info(f"Executing breakpoint hits query for team_id={team_id}, limit={limit}, offset={offset}")
        results = sync_execute(query, params)
        logger.info(f"Query returned {len(results)} results")

        # Process results to return structured data
        processed_results = []
        for row in results:
            try:
                import json

                locals_data = json.loads(row[6]) if row[6] else {}
                stack_trace_data = json.loads(row[7]) if row[7] else []

                processed_results.append(
                    {
                        "id": str(row[0]),
                        "timestamp": row[1].isoformat(),
                        "breakpoint_id": row[2],
                        "line_number": int(row[3]) if row[3] else None,
                        "filename": row[4],
                        "function_name": row[5],
                        "locals": locals_data,
                        "stack_trace": stack_trace_data,
                    }
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                # Skip malformed entries
                continue

        return processed_results
