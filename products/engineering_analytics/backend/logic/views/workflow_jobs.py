"""Curated workflow-jobs query builder.

Maps the raw GitHub workflow-jobs warehouse snapshot (``WORKFLOW_JOBS_COLUMNS`` in
``source_schema``) into honest job-level columns: ``status`` / ``conclusion`` pass through
unchanged, ``duration_seconds`` is computed only for completed jobs, and ``labels`` (the
runner-tier JSON the cost model parses) is unwrapped from its Nullable column. ``run_id`` joins
back to ``github_workflow_runs``. The source table name is resolved per-team and passed in (see
``logic.sources``); it is never hardcoded.

Same layered shape as ``workflow_runs``: the inner SELECT parses timestamps with
``parseDateTimeBestEffortOrNull`` (a queued/running job has no start/finish) and unwraps Nullable
JSON with ``ifNull``; the outer SELECT derives the durations and the copy flag off the parsed columns.

**``provisioning_seconds`` — the VM boot Depot does not bill.** GitHub stamps a job's ``started_at``
the moment Depot accepts it, but the machine then boots before the first step ("Set up job") runs, and
Depot bills only the time after the job started running, not provisioning. The gap is the job's
``started_at`` to its first step's ``started_at`` — tens of seconds per job, a few percent of billed
minutes at scale (the tail at the other end, last step to ``completed_at``, is negligible). NULL when the ``steps`` payload is missing or empty, which ``logic.cost`` reads as "don't
correct" — an under-correction, never an over-correction. ``duration_seconds`` stays the full
wall-clock, because that is what queue and duration UX is about; only cost reads this.

**``is_rerun_copy`` — rows for jobs that never executed.** "Re-run failed jobs" re-lists every job
that already passed under the new ``run_attempt``: new job ids, but ``started_at`` / ``completed_at``
copied verbatim from the attempt that actually ran (a partial re-run of a large matrix re-lists every
passed job and re-runs only the failed ones; GitHub's ``filter=latest`` returns the re-listings too, so
the source can't drop them). Those rows are re-listings, not executions — nothing ran and Depot billed
nothing — and they are a few percent of job rows and minutes. A row is a copy when the same
``(run_id, name, started_at, completed_at)`` exists at a LOWER ``run_attempt``. Consumers counting
executions (cost, retry pressure, duration percentiles) must exclude them; the flag is defined here
so nobody re-derives it.

A narrow aggregate scan finds the duplicated ``(run_id, name, started_at, completed_at)`` groups,
and each job LEFT JOINs against them. Never compute this flag with a window function: a window sorts
every selected column of its whole input in memory, and an outer date filter cannot pass a window
step. The exposed views have no scan floor, so a windowed flag made every query sort the team's
entire job history and exceed the per-query memory limit. The aggregate reads five columns and keeps
only the duplicated groups, so memory scales with the re-runs, not the history.

The raw ``created_at`` string rides along as ``created_at_raw`` (unparsed) because ISO-8601 strings
compare correctly lexicographically. A parsed-column predicate never pushes down to the parquet/S3
scan, so a raw-column floor (``created_at_raw >= '<date>'``) is the only windowing predicate the scan
can prune on — the parsed ``created_at`` stays the precise filter, the raw twin lets the scan skip.
A caller's own outer ``created_at_raw`` predicate can prune the jobs scan, but never the duplicate
scan, which reads no ``created_at_raw``. Windowed callers therefore pass ``created_floor=True`` and
register the ``{job_created_floor}`` placeholder (see ``run_started_floor_constant``, shared with
the runs builder). The floor is a prefilter on the RAW column inside the shared table source, so it
bounds both scans. The trade is exact: a run whose
earlier attempt falls below the floor loses the evidence that its later attempt is a copy, so a
boundary re-run reads as billable — the same coarseness the floor already has, and why the floor sits
a day below the window.

Embedded as a subquery by the jobs query module (see ``_curated``); nothing registers a global view.
"""

# The moment the job actually began running: the first entry of the ``steps`` JSON array. ``steps`` is
# a Nullable JSON string, and ClickHouse rejects an Array nested inside a Nullable, so it is
# ``ifNull``-unwrapped before ``JSONExtractArrayRaw`` (``toString`` keeps this correct if the pipeline
# ever lands the column as a JSON type rather than a String). An empty array yields '' from
# ``arrayElement``, which extracts to '' and parses to NULL — the "steps not synced" fallback.
_FIRST_STEP_STARTED_AT = (
    "parseDateTimeBestEffort("
    "JSONExtractString(arrayElement(JSONExtractArrayRaw(ifNull(toString(steps), '[]')), 1), 'started_at')"
    ")"
)


def build_query(table_name: str, *, created_floor: bool = False) -> str:
    # The floor must live in its OWN innermost SELECT on the raw string column, like the runs
    # builder's: the parsing SELECT below aliases parseDateTimeBestEffort(created_at) AS created_at,
    # so a WHERE there would compare the parsed DateTime against the floor string. Both the jobs scan
    # and the duplicate scan read this source, so the one floor bounds both.
    table_source = (
        f"(SELECT * FROM {table_name} WHERE created_at >= {{job_created_floor}})" if created_floor else table_name
    )
    return f"""
        SELECT
            job.id AS id,
            job.run_id AS run_id,
            job.run_attempt AS run_attempt,
            job.name AS name,
            job.workflow_name AS workflow_name,
            job.head_sha AS head_sha,
            job.head_branch AS head_branch,
            job.status AS status,
            job.conclusion AS conclusion,
            job.labels AS labels,
            job.runner_name AS runner_name,
            job.created_at AS created_at,
            job.created_at_raw AS created_at_raw,
            job.started_at AS started_at,
            job.completed_at AS completed_at,
            if(job.status = 'completed', dateDiff('second', job.started_at, job.completed_at), NULL) AS duration_seconds,
            -- Queue wait: webhook creation to first execution. NULL while still queued.
            if(job.started_at IS NOT NULL, dateDiff('second', job.created_at, job.started_at), NULL) AS queue_seconds,
            -- Runner boot: the job's start to its first step's start. NULL when steps aren't synced;
            -- clamped so a skewed pair can never hand the cost model a negative correction.
            if(
                job.started_at IS NOT NULL AND job.first_step_started_at IS NOT NULL,
                greatest(dateDiff('second', job.started_at, job.first_step_started_at), 0),
                NULL
            ) AS provisioning_seconds,
            -- A matched row shares its exact start/finish with another attempt of the same job; it is
            -- a copy when a LOWER attempt exists. An unmatched row (single occurrence, or NULL
            -- timestamps, which never match the join keys) reads first_attempt as NULL, so the
            -- comparison yields 0. min(run_attempt) stays Nullable, which makes the LEFT JOIN
            -- non-match default NULL rather than 0 (a 0 default would flag every unmatched row).
            ifNull(job.run_attempt > dupes.first_attempt, 0) AS is_rerun_copy
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
                parseDateTimeBestEffort(completed_at) AS completed_at,
                {_FIRST_STEP_STARTED_AT} AS first_step_started_at
            FROM (SELECT *, created_at AS created_at_raw FROM {table_source})
        ) AS job
        -- The duplicated (run_id, name, started_at, completed_at) groups: the re-run copies plus
        -- their originals, from a scan that reads only these five columns. The HAVING drops the
        -- NULL-timestamp groups too: two still-queued attempts of the same job both carry NULL and
        -- are not copies of each other. The key aliases avoid shadowing the raw columns, so the
        -- GROUP BY unambiguously names the parsed values.
        LEFT JOIN (
            SELECT
                run_id,
                name,
                parseDateTimeBestEffort(started_at) AS started_key,
                parseDateTimeBestEffort(completed_at) AS completed_key,
                min(run_attempt) AS first_attempt
            FROM {table_source}
            GROUP BY run_id, name, started_key, completed_key
            HAVING count() > 1 AND started_key IS NOT NULL AND completed_key IS NOT NULL
        ) AS dupes
            ON job.run_id = dupes.run_id
            AND job.name = dupes.name
            AND job.started_at = dupes.started_key
            AND job.completed_at = dupes.completed_key
    """
