"""Curated workflow-jobs query builder.

Maps the raw GitHub workflow-jobs warehouse snapshot (``WORKFLOW_JOBS_COLUMNS`` in
``source_schema``) into honest job-level columns: ``status`` / ``conclusion`` pass through
unchanged, ``duration_seconds`` is computed only for completed jobs, and ``labels`` (the
runner-tier JSON the cost model parses) is unwrapped from its Nullable column. ``run_id`` joins
back to ``github_workflow_runs``. The source table name is resolved per-team and passed in (see
``logic.sources``); it is never hardcoded.

Same two-layer shape as ``workflow_runs``: the inner SELECT parses timestamps with
``parseDateTimeBestEffortOrNull`` (a queued/running job has no start/finish) and unwraps Nullable
JSON with ``ifNull``; the outer SELECT derives the duration off the parsed columns.

Embedded as a subquery by the jobs query module (see ``_curated``); nothing registers a global view.
"""


def build_query(table_name: str) -> str:
    return f"""
        SELECT
            id,
            run_id,
            run_attempt,
            name,
            workflow_name,
            head_branch,
            status,
            conclusion,
            labels,
            runner_name,
            created_at,
            started_at,
            completed_at,
            if(status = 'completed', dateDiff('second', started_at, completed_at), NULL) AS duration_seconds,
            -- Queue wait: webhook creation to first execution. NULL while still queued.
            if(started_at IS NOT NULL, dateDiff('second', created_at, started_at), NULL) AS queue_seconds
        FROM (
            SELECT
                id,
                run_id,
                run_attempt,
                name,
                ifNull(workflow_name, '') AS workflow_name,
                ifNull(head_branch, '') AS head_branch,
                status,
                conclusion,
                ifNull(labels, '[]') AS labels,
                ifNull(runner_name, '') AS runner_name,
                -- HogQL maps parseDateTimeBestEffort to the OrNull variant, so an empty/queued '' lands
                -- as NULL with no explicit nullIf — same as the runs builder.
                parseDateTimeBestEffort(created_at) AS created_at,
                parseDateTimeBestEffort(started_at) AS started_at,
                parseDateTimeBestEffort(completed_at) AS completed_at
            FROM {table_name}
        )
    """
