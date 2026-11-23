"""The workflow jobs builder: one row per job attempt.

``provisioning_seconds`` is the time from the job's ``started_at`` to its first step's start. It is
NULL when the ``steps`` payload is missing or empty. Depot does not bill that time, so only cost reads it.

``is_rerun_copy`` marks a row GitHub lists again under a later ``run_attempt`` for a job that did not
run again. A read that counts executions must exclude those rows. The flag comes from a join against
the duplicated groups and never from a window function, which sorts its whole input in memory.

``created_at_raw`` is the unparsed ``created_at`` string. The parquet scan can prune on a predicate
over it and cannot prune on one over the parsed ``created_at``. An outer ``created_at_raw`` predicate
does not reach the duplicate scan, so a windowed caller passes ``created_floor=True`` and registers
the ``{job_created_floor}`` placeholder (see ``job_created_floor_constant``).
"""

from posthog.dataclasses import frozen

# ClickHouse rejects an Array nested inside a Nullable, so ``steps`` is unwrapped before
# ``JSONExtractArrayRaw``. The ``toString`` covers a pipeline that lands the column as a JSON type.
# An empty array parses to NULL.
_FIRST_STEP_STARTED_AT = (
    "parseDateTimeBestEffort("
    "JSONExtractString(arrayElement(JSONExtractArrayRaw(ifNull(toString(steps), '[]')), 1), 'started_at')"
    ")"
)


def branch(jobs_alias: str, runs_alias: str) -> str:
    """The job's branch, or its run's branch when the job has none. Depot CI job rows carry no branch."""
    return f"coalesce(nullIf({jobs_alias}.head_branch, ''), {runs_alias}.head_branch)"


@frozen
class JobsTable:
    """``rows`` is the source of the jobs a read returns, and ``duplicates`` is the source of the duplicate scan.

    ``duplicates`` may hold runs that ``rows`` leaves out, because a job row only joins to duplicates of
    its own run.
    """

    rows: str
    duplicates: str

    @classmethod
    def of(cls, table: str) -> "JobsTable":
        return cls(rows=table, duplicates=table)


COLUMNS = (
    "id",
    "run_id",
    "run_attempt",
    "name",
    "workflow_name",
    "head_sha",
    "head_branch",
    "status",
    "conclusion",
    "labels",
    "runner_name",
    "created_at",
    "created_at_raw",
    "started_at",
    "completed_at",
    "duration_seconds",
    "queue_seconds",
    "provisioning_seconds",
    "is_rerun_copy",
    "ci_engine",
    "native_run_id",
    "native_workflow_run_id",
    "native_job_id",
    "native_attempt_id",
)


def build_query(
    table: JobsTable, *, created_floor: bool = False, include_steps: bool = False, compact_duplicates: bool = True
) -> str:
    """Returns the ``COLUMNS`` in order. ``include_steps`` appends the raw ``steps`` JSON as the last column.

    ``steps`` is the widest column of the table, so only a read bounded to one run should ask for it.
    """

    # The floor needs its own innermost SELECT on the raw string column. The parsing SELECT below
    # aliases the parsed value as created_at, so a WHERE there would compare a DateTime with the floor string.
    def floored(source: str) -> str:
        return f"(SELECT * FROM {source} WHERE created_at >= {{job_created_floor}})" if created_floor else source

    rows_source = floored(table.rows)
    duplicates_source = floored(table.duplicates)
    steps_column = ",\n            job.steps AS steps" if include_steps else ""
    parsed_steps_column = ",\n                ifNull(toString(steps), '[]') AS steps" if include_steps else ""
    # The HAVING saves memory on an unbounded read. A materialized view passes compact_duplicates=False,
    # because incremental validation rejects a query that removes groups.
    duplicate_filter = (
        "HAVING count() > 1 AND started_key IS NOT NULL AND completed_key IS NOT NULL" if compact_duplicates else ""
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
            ifNull(job.run_attempt > dupes.first_attempt, 0) AS is_rerun_copy,
            job.ci_engine AS ci_engine,
            job.native_run_id AS native_run_id,
            job.native_workflow_run_id AS native_workflow_run_id,
            job.native_job_id AS native_job_id,
            job.native_attempt_id AS native_attempt_id{steps_column}
        FROM (
            SELECT
                id,
                ci_engine, native_run_id, native_workflow_run_id, native_job_id, native_attempt_id,
                run_id,
                run_attempt,
                ifNull(name, '') AS name,
                ifNull(workflow_name, '') AS workflow_name,
                ifNull(head_sha, '') AS head_sha,
                ifNull(head_branch, '') AS head_branch,
                ifNull(status, '') AS status,
                conclusion,
                ifNull(labels, '[]') AS labels,
                ifNull(runner_name, '') AS runner_name,
                -- HogQL maps parseDateTimeBestEffort to the OrNull variant, so an empty/queued '' lands
                -- as NULL with no explicit nullIf — same as the runs builder.
                parseDateTimeBestEffort(created_at) AS created_at,
                created_at_raw,
                parseDateTimeBestEffort(started_at) AS started_at,
                parseDateTimeBestEffort(completed_at) AS completed_at,
                {_FIRST_STEP_STARTED_AT} AS first_step_started_at{parsed_steps_column}
            FROM (SELECT *, created_at AS created_at_raw FROM {rows_source})
        ) AS job
        -- The duplicated (run_id, name, started_at, completed_at) groups: the re-run copies plus
        -- their originals, from a scan that reads only these five columns. The HAVING drops the
        -- NULL-timestamp groups too: two still-queued attempts of the same job both carry NULL and
        -- are not copies of each other. The key aliases avoid shadowing the raw columns, so the
        -- GROUP BY unambiguously names the parsed values.
        LEFT JOIN (
            SELECT
                ci_engine,
                run_id,
                name,
                parseDateTimeBestEffort(started_at) AS started_key,
                parseDateTimeBestEffort(completed_at) AS completed_key,
                min(run_attempt) AS first_attempt
            FROM {duplicates_source}
            GROUP BY ci_engine, run_id, name, started_key, completed_key
            {duplicate_filter}
        ) AS dupes
            ON job.run_id = dupes.run_id AND job.ci_engine = dupes.ci_engine
            AND job.name = dupes.name
            AND job.started_at = dupes.started_key
            AND job.completed_at = dupes.completed_key
    """
