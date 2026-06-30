"""Curated workflow-jobs query builder.

Maps the raw GitHub workflow-jobs snapshot (``WORKFLOW_JOBS_COLUMNS``) into honest job-level columns:
``status`` / ``conclusion`` pass through, ``duration_seconds`` is computed only for completed jobs, and
``labels`` (the runner-tier JSON) is unwrapped from its Nullable column. ``run_id`` joins back to
``github_workflow_runs``. The source table name is resolved per-team and passed in; never hardcoded.

Same two-layer shape as ``workflow_runs``: the inner SELECT parses timestamps with
``parseDateTimeBestEffortOrNull`` and unwraps Nullable JSON with ``ifNull``; the outer derives duration.
"""


def build_query(table_name: str) -> str:
    return f"""
        SELECT
            id,
            run_id,
            run_attempt,
            name,
            status,
            conclusion,
            labels,
            runner_name,
            started_at,
            completed_at,
            if(status = 'completed', dateDiff('second', started_at, completed_at), NULL) AS duration_seconds
        FROM (
            SELECT
                id,
                run_id,
                run_attempt,
                name,
                status,
                conclusion,
                ifNull(labels, '[]') AS labels,
                ifNull(runner_name, '') AS runner_name,
                -- HogQL maps parseDateTimeBestEffort to the OrNull variant, so an empty/queued '' lands
                -- as NULL with no explicit nullIf — same as the runs builder.
                parseDateTimeBestEffort(started_at) AS started_at,
                parseDateTimeBestEffort(completed_at) AS completed_at
            FROM {table_name}
        )
    """
