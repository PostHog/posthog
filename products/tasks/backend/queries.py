import json
from typing import Any

from posthog.clickhouse.client import sync_execute


def get_agent_logs(
    team_id: int,
    task_id: str,
    run_id: str,
    limit: int | None = None,
    after_sequence: int | None = None,
) -> list[dict[str, Any]]:
    """
    Get all logs for a task run, ordered by sequence.

    Args:
        team_id: The team ID
        task_id: The task UUID
        run_id: The run UUID
        limit: Optional limit on number of results
        after_sequence: Optional sequence number to start from (for pagination/resume)

    Returns:
        List of log entries as dictionaries
    """
    query = """
        SELECT
            sequence,
            timestamp,
            entry_type,
            entry
        FROM agent_logs
        WHERE team_id = %(team_id)s
          AND task_id = %(task_id)s
          AND run_id = %(run_id)s
          {after_sequence_filter}
        ORDER BY sequence ASC
        {limit_clause}
    """

    after_sequence_filter = ""
    if after_sequence is not None:
        after_sequence_filter = "AND sequence > %(after_sequence)s"

    limit_clause = ""
    if limit is not None:
        limit_clause = f"LIMIT {int(limit)}"

    query = query.format(
        after_sequence_filter=after_sequence_filter,
        limit_clause=limit_clause,
    )

    results = sync_execute(
        query,
        {
            "team_id": team_id,
            "task_id": task_id,
            "run_id": run_id,
            "after_sequence": after_sequence,
        },
    )

    return [
        {
            "sequence": row[0],
            "timestamp": row[1].isoformat() if row[1] else None,
            "entry_type": row[2],
            "entry": json.loads(row[3]) if row[3] else None,
        }
        for row in results
    ]


def get_agent_logs_tail(
    team_id: int,
    task_id: str,
    run_id: str,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """
    Get the last N logs for a task run (tail query).

    Args:
        team_id: The team ID
        task_id: The task UUID
        run_id: The run UUID
        limit: Number of entries to return (default 2000)

    Returns:
        List of log entries as dictionaries, ordered by sequence ASC
    """
    query = """
        SELECT
            sequence,
            timestamp,
            entry_type,
            entry
        FROM (
            SELECT
                sequence,
                timestamp,
                entry_type,
                entry
            FROM agent_logs
            WHERE team_id = %(team_id)s
              AND task_id = %(task_id)s
              AND run_id = %(run_id)s
            ORDER BY sequence DESC
            LIMIT %(limit)s
        )
        ORDER BY sequence ASC
    """

    results = sync_execute(
        query,
        {
            "team_id": team_id,
            "task_id": task_id,
            "run_id": run_id,
            "limit": limit,
        },
    )

    return [
        {
            "sequence": row[0],
            "timestamp": row[1].isoformat() if row[1] else None,
            "entry_type": row[2],
            "entry": json.loads(row[3]) if row[3] else None,
        }
        for row in results
    ]


def get_agent_logs_as_jsonl(
    team_id: int,
    task_id: str,
    run_id: str,
) -> str:
    """
    Get all logs for a task run as JSONL format (for API compatibility with S3 format).

    Args:
        team_id: The team ID
        task_id: The task UUID
        run_id: The run UUID

    Returns:
        JSONL string of log entries
    """
    logs = get_agent_logs(team_id, task_id, run_id)

    if not logs:
        return ""

    lines = []
    for log in logs:
        if log["entry"]:
            lines.append(json.dumps(log["entry"]))

    return "\n".join(lines)


def get_max_sequence(
    team_id: int,
    task_id: str,
    run_id: str,
) -> int:
    """
    Get the current max sequence number for a task run.
    Used for generating the next sequence number when appending.

    Returns:
        Max sequence number, or 0 if no logs exist
    """
    query = """
        SELECT max(sequence)
        FROM agent_logs
        WHERE team_id = %(team_id)s
          AND task_id = %(task_id)s
          AND run_id = %(run_id)s
    """

    result = sync_execute(
        query,
        {
            "team_id": team_id,
            "task_id": task_id,
            "run_id": run_id,
        },
    )

    if result and result[0][0] is not None:
        return result[0][0]
    return 0
