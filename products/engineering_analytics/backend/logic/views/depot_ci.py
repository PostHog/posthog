"""Depot CI job attempts, rendered as rows of the raw GitHub runs and jobs tables.

Depot CI is its own CI engine, not Depot runners under GitHub Actions, so the runs it executes never
reach the GitHub source. The Depot source syncs them to a ``job_attempts`` table instead. The
functions here reshape that table into ``WORKFLOW_RUNS_COLUMNS`` and ``WORKFLOW_JOBS_COLUMNS`` rows
and union them onto the GitHub tables, so every builder derives durations, PR numbers and cost for
both engines with one set of rules.

A Depot workflow is the counterpart of a GitHub workflow run, so it becomes one runs row. Depot ids
are strings. Depot CI sets ``GITHUB_RUN_ID`` to the run id read as a base-30 number over
``_ID_ALPHABET``, which the per-test traces its jobs emit confirm. A run with one workflow therefore
takes its decoded run id, which joins those traces to its jobs. A run with several workflows takes
each workflow's decoded id instead, because one shared id would fan every join on it out.
"""

import re

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.logic.views.source_schema import (
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)

_ID_ALPHABET = "0123456789bcdfghjklmnpqrstvwxz"

# The repository is written into HogQL as a string literal, so only a plain owner/name qualifies.
_PLAIN_REPOSITORY = re.compile(r"\A[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")


@frozen
class DepotJobAttempts:
    """A synced Depot ``job_attempts`` table and the repository whose rows it contributes.

    Reads keep only that repository's rows, because a Depot source moved to another repository keeps
    the rows it synced before the move.
    """

    table: str
    repository: str

    def __post_init__(self) -> None:
        if not _PLAIN_REPOSITORY.match(self.repository):
            raise ValueError(f"Not a plain owner/name repository: {self.repository!r}")

    @classmethod
    def for_repository(cls, table: str, repository: str) -> "DepotJobAttempts | None":
        """The attempts of ``repository``, or None when it is not a plain owner/name."""
        return cls(table=table, repository=repository) if _PLAIN_REPOSITORY.match(repository) else None


# Depot ids are 10 characters. Ten base-30 digits stay below 2^53, so the Float64 powers sum exactly.
_MAX_ID_LENGTH = 10

# Depot's API does not report a job's runs-on, so every attempt is costed as the default sandbox.
_DEFAULT_SANDBOX_LABELS = '["depot-ubuntu-24.04"]'

# Depot reports no repository id. Any positive id on both sides lets the runs builder accept the
# pull request association as the run's own.
_REPOSITORY_ID = 1


def _is_id(column: str) -> str:
    return f"match(ifNull({column}, ''), '^[{_ID_ALPHABET}]{{1,{_MAX_ID_LENGTH}}}$')"


def depot_id_to_int(depot_id: str) -> int | None:
    """The integer ``_id_to_int`` renders for ``depot_id``, or None when it is not a Depot CI id."""
    if not 0 < len(depot_id) <= _MAX_ID_LENGTH or any(char not in _ID_ALPHABET for char in depot_id):
        return None
    value = 0
    for char in depot_id:
        value = value * len(_ID_ALPHABET) + _ID_ALPHABET.index(char)
    return value


def depot_github_run_id(run_id: str, workflow_id: str, run_workflow_count: int) -> int | None:
    """The integer ``_attempts`` gives a Depot workflow's runs row, or None when it has none."""
    return depot_id_to_int(run_id if run_workflow_count == 1 else workflow_id)


def _id_to_int(column: str) -> str:
    # ClickHouse cannot sum an array of Nullable values, so the Nullable column is unwrapped first.
    value = f"ifNull({column}, '')"
    chars = f"splitByString('', {value})"
    digits = f"arrayMap((c, i) -> (position('{_ID_ALPHABET}', c) - 1) * pow(30, length({value}) - i), {chars}, arrayEnumerate({chars}))"
    return f"toInt(arraySum({digits}))"


def _conclusion(status: str) -> str:
    # Depot's terminal statuses in GitHub's conclusion vocabulary. `cancelled` and `skipped` are
    # already the same word in both.
    return f"multiIf({status} = 'finished', 'success', {status} = 'failed', 'failure', {status})"


def _attempts(depot: DepotJobAttempts, pull_requests_table: str | None) -> str:
    # Depot reports no branch, so a PR run takes its head branch from the PR snapshot, and branch
    # filters then match it like a GitHub run of the same PR.
    pr_number = "ifNull(toInt(extract(a.ref, '^refs/pull/([0-9]+)/')), 0)"
    if pull_requests_table:
        head_branch = "nullIf(pr.head_branch, '')"
        branch_join = f"""
            LEFT JOIN (
                SELECT number, any(JSONExtractString(ifNull(head, '{{}}'), 'ref')) AS head_branch
                FROM {pull_requests_table}
                GROUP BY number
            ) AS pr ON {pr_number} = pr.number"""
    else:
        head_branch = "NULL"
        branch_join = ""
    # A push run's id carries a prefix outside the alphabet, and such a run holds no workflows.
    return f"""(
        SELECT
            {_id_to_int("if(a.run_workflow_count = 1, a.run_id, a.workflow_id)")} AS github_run_id,
            {_id_to_int("a.attempt_id")} AS github_job_id,
            {pr_number} AS pr_number,
            {head_branch} AS head_branch,
            a.repo AS repo,
            a.head_sha AS head_sha,
            a.workflow_name AS workflow_name,
            a.workflow_status AS workflow_status,
            a.workflow_created_at AS workflow_created_at,
            a.workflow_started_at AS workflow_started_at,
            a.workflow_finished_at AS workflow_finished_at,
            a.job_id AS depot_job_id,
            a.job_key AS job_key,
            a.job_display_name AS job_display_name,
            a.attempt AS attempt,
            a.attempt_status AS attempt_status,
            a.attempt_started_at AS attempt_started_at,
            a.attempt_finished_at AS attempt_finished_at,
            a.sandbox_id AS sandbox_id
        FROM {depot.table} AS a
        {branch_join}
        WHERE lower(ifNull(a.repo, '')) = '{depot.repository.lower()}'
            AND {_is_id("a.run_id")} AND {_is_id("a.workflow_id")} AND {_is_id("a.attempt_id")}
    )"""


def _runs(attempts: str) -> str:
    return f"""
        SELECT
            github_run_id AS id,
            any(workflow_name) AS name,
            any(head_sha) AS head_sha,
            any(head_branch) AS head_branch,
            'completed' AS status,
            {_conclusion("any(workflow_status)")} AS conclusion,
            any(workflow_created_at) AS created_at,
            any(workflow_started_at) AS run_started_at,
            any(workflow_finished_at) AS updated_at,
            max(attempt) AS run_attempt,
            if(
                any(pr_number) > 0,
                concat('[{{"number":', toString(any(pr_number)), ',"base":{{"repo":{{"id":{_REPOSITORY_ID}}}}}}}]'),
                '[]'
            ) AS pull_requests,
            concat('{{"id":{_REPOSITORY_ID},"full_name":"', any(repo), '"}}') AS repository,
            NULL AS head_commit,
            NULL AS actor
        FROM {attempts}
        GROUP BY github_run_id
    """


def _jobs(attempts: str) -> str:
    # GitHub lists every job of a run under each run attempt. A job that a run attempt did not re-run keeps
    # the timestamps of the attempt that ran, and the jobs builder flags that row as a copy. Depot numbers
    # attempts per job, so each job's last attempt is listed again under every later attempt of its run.
    return f"""
        SELECT
            a.github_job_id AS id,
            a.github_run_id AS run_id,
            toInt(arrayJoin(range(a.attempt, if(a.attempt = last.job_attempt, last.run_attempt, a.attempt) + 1))) AS run_attempt,
            if(ifNull(a.job_display_name, '') != '', a.job_display_name, a.job_key) AS name,
            a.workflow_name AS workflow_name,
            if(ifNull(a.attempt_finished_at, '') != '', 'completed', 'in_progress') AS status,
            {_conclusion("a.attempt_status")} AS conclusion,
            a.head_sha AS head_sha,
            a.head_branch AS head_branch,
            '{_DEFAULT_SANDBOX_LABELS}' AS labels,
            a.sandbox_id AS runner_name,
            NULL AS runner_group_name,
            -- Depot reports no queue time for an attempt, so it counts as created when it starts.
            a.attempt_started_at AS created_at,
            a.attempt_started_at AS started_at,
            a.attempt_finished_at AS completed_at,
            NULL AS steps
        FROM {attempts} AS a
        INNER JOIN (
            SELECT jobs.depot_job_id AS depot_job_id, jobs.job_attempt AS job_attempt, runs.run_attempt AS run_attempt
            FROM (
                SELECT github_run_id, depot_job_id, max(attempt) AS job_attempt
                FROM {attempts}
                GROUP BY github_run_id, depot_job_id
            ) AS jobs
            INNER JOIN (
                SELECT github_run_id, max(attempt) AS run_attempt FROM {attempts} GROUP BY github_run_id
            ) AS runs ON jobs.github_run_id = runs.github_run_id
        ) AS last ON a.depot_job_id = last.depot_job_id
    """


def _union(github_table: str, columns: dict[str, dict[str, str]], depot_select: str) -> str:
    # UNION ALL matches columns by position, so the GitHub side names them in the contract order the
    # Depot side follows.
    return f"(SELECT {', '.join(columns)} FROM {github_table} UNION ALL {depot_select})"


def with_depot_runs(runs_table: str, depot: DepotJobAttempts | None, pull_requests_table: str | None) -> str:
    """The GitHub runs table, or a subquery that also holds the Depot CI runs when they are synced."""
    if depot is None:
        return runs_table
    return _union(runs_table, WORKFLOW_RUNS_COLUMNS, _runs(_attempts(depot, pull_requests_table)))


def with_depot_jobs(jobs_table: str, depot: DepotJobAttempts | None) -> str:
    """The GitHub jobs table, or a subquery that also holds the Depot CI job attempts when they are synced.

    Depot job rows carry no branch: the jobs builder scans its source twice, so a PR snapshot lookup here
    would cost two PR scans per jobs read. A reader that joins a job to its run reads the branch through
    ``workflow_jobs.branch``, which falls back to the run's.
    """
    if depot is None:
        return jobs_table
    return _union(jobs_table, WORKFLOW_JOBS_COLUMNS, _jobs(_attempts(depot, pull_requests_table=None)))
