"""Depot CI job attempts, rendered as rows of the raw GitHub runs and jobs tables.

Depot CI is its own CI engine, not Depot runners under GitHub Actions, so the runs it executes never
reach the GitHub source. The Depot source syncs them to a ``job_attempts`` table instead. The
functions here reshape that table into ``WORKFLOW_RUNS_COLUMNS`` and ``WORKFLOW_JOBS_COLUMNS`` rows
and union them onto the GitHub tables, so every builder derives durations, PR numbers and cost for
both engines with one set of rules.

Depot ids are strings. Depot CI sets ``GITHUB_RUN_ID`` to the run id read as a base-30 number over
``_ID_ALPHABET``, which the per-test traces its jobs emit confirm. Decoding every id with the same
rule gives the integer ids the builders join on, and it joins those traces to these jobs.
"""

from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)

_ID_ALPHABET = "0123456789bcdfghjklmnpqrstvwxz"

# Depot ids are 10 characters. Ten base-30 digits stay below 2^53, so the Float64 powers sum exactly.
_MAX_ID_LENGTH = 10

# Depot's API does not report a job's runs-on, so every attempt is costed as the default sandbox.
_DEFAULT_SANDBOX_LABELS = '["depot-ubuntu-24.04"]'

# Depot reports no repository id. Any positive id on both sides lets the runs builder accept the
# pull request association as the run's own.
_REPOSITORY_ID = 1


def _is_id(column: str) -> str:
    return f"match(ifNull({column}, ''), '^[{_ID_ALPHABET}]{{1,{_MAX_ID_LENGTH}}}$')"


def _id_to_int(column: str) -> str:
    # ClickHouse cannot sum an array of Nullable values, so the Nullable column is unwrapped first.
    value = f"ifNull({column}, '')"
    chars = f"splitByString('', {value})"
    digits = f"arrayMap((c, i) -> (position('{_ID_ALPHABET}', c) - 1) * pow(30, length({value}) - i), {chars}, arrayEnumerate({chars}))"
    return f"toInt(arraySum({digits}))"


def _attempts_with_ids(attempts_table: str) -> str:
    # Filtered in their own SELECT because the outer SELECTs alias the decoded ids over the raw
    # column names, and ClickHouse would resolve a WHERE there against the aliases. A push run's id
    # carries a prefix outside the alphabet, so it has no GitHub run id and is left out.
    return f"(SELECT * FROM {attempts_table} WHERE {_is_id('run_id')} AND {_is_id('attempt_id')})"


def _runs(attempts_table: str) -> str:
    # One row per Depot run, because GITHUB_RUN_ID, and so every trace and job, identifies the run
    # and not the workflow inside it.
    pr_number = "ifNull(toInt(extract(any(ref), '^refs/pull/([0-9]+)/')), 0)"
    return f"""
        SELECT
            {_id_to_int("run_id")} AS id,
            any(workflow_name) AS name,
            any(head_sha) AS head_sha,
            NULL AS head_branch,
            'completed' AS status,
            multiIf(any(run_status) = 'finished', 'success', any(run_status) = 'failed', 'failure', any(run_status)) AS conclusion,
            any(run_created_at) AS created_at,
            any(run_started_at) AS run_started_at,
            any(run_finished_at) AS updated_at,
            max(attempt) AS run_attempt,
            if({pr_number} > 0, concat('[{{"number":', toString({pr_number}), ',"base":{{"repo":{{"id":{_REPOSITORY_ID}}}}}}}]'), '[]') AS pull_requests,
            concat('{{"id":{_REPOSITORY_ID},"full_name":"', any(repo), '"}}') AS repository,
            NULL AS head_commit,
            NULL AS actor
        FROM {_attempts_with_ids(attempts_table)}
        GROUP BY run_id
    """


def _jobs(attempts_table: str) -> str:
    return f"""
        SELECT
            {_id_to_int("attempt_id")} AS id,
            {_id_to_int("run_id")} AS run_id,
            attempt AS run_attempt,
            if(ifNull(job_display_name, '') != '', job_display_name, job_key) AS name,
            workflow_name,
            if(ifNull(attempt_finished_at, '') != '', 'completed', 'in_progress') AS status,
            attempt_conclusion AS conclusion,
            head_sha,
            NULL AS head_branch,
            '{_DEFAULT_SANDBOX_LABELS}' AS labels,
            sandbox_id AS runner_name,
            NULL AS runner_group_name,
            attempt_created_at AS created_at,
            attempt_started_at AS started_at,
            attempt_finished_at AS completed_at,
            NULL AS steps
        FROM {_attempts_with_ids(attempts_table)}
    """


def _union(github_table: str, columns: dict[str, dict[str, str]], depot_select: str) -> str:
    # UNION ALL matches columns by position, so the GitHub side names them in the contract order the
    # Depot side follows.
    return f"(SELECT {', '.join(columns)} FROM {github_table} UNION ALL {depot_select})"


def with_depot_runs(runs_table: str, attempts_table: str | None) -> str:
    """The GitHub runs table, or a subquery that also holds the Depot CI runs when they are synced."""
    return _union(runs_table, WORKFLOW_RUNS_COLUMNS, _runs(attempts_table)) if attempts_table else runs_table


def with_depot_jobs(jobs_table: str, attempts_table: str | None) -> str:
    """The GitHub jobs table, or a subquery that also holds the Depot CI job attempts when they are synced."""
    return _union(jobs_table, WORKFLOW_JOBS_COLUMNS, _jobs(attempts_table)) if attempts_table else jobs_table
