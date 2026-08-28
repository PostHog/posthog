"""Curated workflow-jobs query builder.

Maps the raw GitHub workflow-jobs warehouse snapshot (``WORKFLOW_JOBS_COLUMNS`` in
``source_schema``) into honest job-level columns: ``status`` / ``conclusion`` pass through
unchanged, ``duration_seconds`` is computed only for completed jobs, and ``labels`` (the
runner-tier JSON the cost model parses) is unwrapped from its Nullable column. ``run_id`` joins
back to ``github_workflow_runs``. The source table name is resolved per-team and passed in (see
``logic.sources``); it is never hardcoded.

Same layered shape as ``workflow_runs``: the inner SELECT parses timestamps with
``parseDateTimeBestEffortOrNull`` (a queued/running job has no start/finish) and unwraps Nullable
JSON with ``ifNull``; the outer SELECT derives the duration and the copy flag off the parsed columns.

**``is_rerun_copy`` — rows for jobs that never executed.** "Re-run failed jobs" re-lists every job
that already passed under the new ``run_attempt``: new job ids, but ``started_at`` / ``completed_at``
copied verbatim from the attempt that actually ran (verified on ``PostHog/posthog`` run 32837341242,
where attempt 2 lists 81 jobs of which 80 are copies; GitHub's ``filter=latest`` returns them too, so
the source can't drop them). Those rows are re-listings, not executions — nothing ran and Depot billed
nothing — and on this repo they are ~2.6% of job rows and minutes. A row is a copy when the same
``(run_id, name, started_at, completed_at)`` exists at a LOWER ``run_attempt``, which is the window
below. Consumers counting executions (cost, retry pressure, duration percentiles) must exclude them;
the flag is defined here so nobody re-derives it.

The raw ``created_at`` string rides along as ``created_at_raw`` (unparsed) because ISO-8601 strings
compare correctly lexicographically. A parsed-column predicate never pushes down to the parquet/S3
scan, so a raw-column floor (``created_at_raw >= '<date>'``) is the only windowing predicate the scan
can prune on — the parsed ``created_at`` stays the precise filter, the raw twin lets the scan skip.
A caller's own outer ``created_at_raw`` predicate no longer prunes, though: it sits above the
``is_rerun_copy`` window, and ClickHouse can only push a filter below a window step when it reads
partition-by columns. Windowed callers therefore pass ``created_floor=True``, which puts the same
coarse floor in an innermost prefilter on the RAW column — below the window, where the scan can still
use it — and register the ``{job_created_floor}`` placeholder (see ``run_started_floor_constant``,
shared with the runs builder). The trade is exact: a run whose earlier attempt falls below the floor
loses the evidence that its later attempt is a copy, so a boundary re-run reads as billable — the same
coarseness the floor already has, and why the floor sits a day below the window.

Embedded as a subquery by the jobs query module (see ``_curated``); nothing registers a global view.
"""

# A row GitHub re-listed under a later attempt without re-running it (see the module docstring): the
# same run, job name, and exact start/finish already exist at a lower attempt. Both timestamps must be
# present — two still-queued attempts of the same job both carry NULL and are not copies of each other.
_IS_RERUN_COPY = """ifNull(
                started_at IS NOT NULL
                    AND completed_at IS NOT NULL
                    AND run_attempt > min(run_attempt) OVER (
                        PARTITION BY run_id, name, started_at, completed_at
                    ),
                0
            )"""


def build_query(table_name: str, *, created_floor: bool = False) -> str:
    # The floor must live in its OWN innermost SELECT on the raw string column, like the runs
    # builder's: the parsing SELECT below aliases parseDateTimeBestEffort(created_at) AS created_at,
    # so a WHERE there would compare the parsed DateTime against the floor string.
    table_source = (
        f"(SELECT * FROM {table_name} WHERE created_at >= {{job_created_floor}})" if created_floor else table_name
    )
    return f"""
        SELECT
            id,
            run_id,
            run_attempt,
            name,
            workflow_name,
            head_sha,
            head_branch,
            status,
            conclusion,
            labels,
            runner_name,
            created_at,
            created_at_raw,
            started_at,
            completed_at,
            if(status = 'completed', dateDiff('second', started_at, completed_at), NULL) AS duration_seconds,
            -- Queue wait: webhook creation to first execution. NULL while still queued.
            if(started_at IS NOT NULL, dateDiff('second', created_at, started_at), NULL) AS queue_seconds,
            {_IS_RERUN_COPY} AS is_rerun_copy
        FROM (
            SELECT
                id,
                run_id,
                run_attempt,
                name,
                ifNull(workflow_name, '') AS workflow_name,
                ifNull(head_sha, '') AS head_sha,
                ifNull(head_branch, '') AS head_branch,
                status,
                conclusion,
                ifNull(labels, '[]') AS labels,
                ifNull(runner_name, '') AS runner_name,
                -- HogQL maps parseDateTimeBestEffort to the OrNull variant, so an empty/queued '' lands
                -- as NULL with no explicit nullIf — same as the runs builder.
                parseDateTimeBestEffort(created_at) AS created_at,
                created_at_raw,
                parseDateTimeBestEffort(started_at) AS started_at,
                parseDateTimeBestEffort(completed_at) AS completed_at
            FROM (SELECT *, created_at AS created_at_raw FROM {table_source})
        )
    """
