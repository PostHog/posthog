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

While a repository moves a workflow to Depot CI, GitHub Actions decides per pull request which engine
runs it, and both engines record a run of the same commit. The engine that did not run the tests
leaves a hand-off shell: a GitHub run whose hand-off job succeeded and whose gate only relays Depot's
verdict, or a Depot workflow that waited for a hand-off that never came and skipped everything else.
The union drops successful shells with their jobs. A GitHub relay stays unless a successful Depot
workflow took the hand-off for the same PR and commit. Failed and unsettled relays stay because the
synced tables carry no exact event link, and another event's Depot verdict cannot replace theirs.
"""

import re

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DECISIVE_FAILURE_CONCLUSIONS_SQL,
    SUCCESSFUL_RUN_CONDITION,
)
from products.engineering_analytics.backend.logic.views import workflow_jobs, workflow_runs
from products.engineering_analytics.backend.logic.views.created_window import CreatedWindow
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

# The hand-off between the engines, as .github/workflows/ci-backend.yml and .depot/workflows/ci-backend.yml
# name its two ends.
_GITHUB_HANDOFF_JOB = "Hand off backend tests to Depot CI"
_GITHUB_RELAY_JOB = "Django Tests Pass"
_DEPOT_WAIT_JOB_KEY_SUFFIX = ":wait-for-handoff"


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


def _attempts(depot: DepotJobAttempts, pull_requests_table: str | None, where: str = "1") -> str:
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
            coalesce(nullIf(extract(ifNull(a.ref, ''), '^refs/heads/(.+)$'), ''), {head_branch}) AS head_branch,
            a.repo AS repo,
            coalesce(nullIf(a.head_sha, ''), a.sha) AS head_sha,
            a.run_id AS native_run_id,
            a.workflow_id AS native_workflow_run_id,
            a.job_id AS native_job_id,
            a.attempt_id AS native_attempt_id,
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
            AND ({where})
    )"""


def _runs(attempts: str, extra_columns: str = "") -> str:
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
            NULL AS actor,
            'depot_ci' AS ci_engine,
            any(native_run_id) AS native_run_id,
            any(native_workflow_run_id) AS native_workflow_run_id{extra_columns}
        FROM {attempts}
        GROUP BY github_run_id
    """


def _jobs(attempts: str, run_attempts: str | None = None) -> str:
    """``run_attempts`` holds every attempt of the runs in ``attempts``. It defaults to ``attempts``."""
    run_attempts = run_attempts or attempts
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
            NULL AS steps,
            'depot_ci' AS ci_engine,
            a.native_run_id AS native_run_id,
            a.native_workflow_run_id AS native_workflow_run_id,
            a.native_job_id AS native_job_id,
            a.native_attempt_id AS native_attempt_id
        FROM {attempts} AS a
        INNER JOIN (
            SELECT jobs.depot_job_id AS depot_job_id, jobs.job_attempt AS job_attempt, runs.run_attempt AS run_attempt
            FROM (
                SELECT github_run_id, depot_job_id, max(attempt) AS job_attempt
                FROM {run_attempts}
                GROUP BY github_run_id, depot_job_id
            ) AS jobs
            INNER JOIN (
                SELECT github_run_id, max(attempt) AS run_attempt FROM {run_attempts} GROUP BY github_run_id
            ) AS runs ON jobs.github_run_id = runs.github_run_id
        ) AS last ON a.depot_job_id = last.depot_job_id
    """


def _handoff_workflows(depot: DepotJobAttempts, where: str = "1") -> str:
    # Depot lists no attempt for a skipped job, so a workflow that declined the hand-off holds the wait job alone.
    is_wait = f"endsWith(ifNull(job_key, ''), '{_DEPOT_WAIT_JOB_KEY_SUFFIX}')"
    return f"""(
        SELECT
            github_run_id,
            any(head_sha) AS head_sha,
            any(pr_number) AS pr_number,
            any(workflow_status) AS workflow_status,
            min(parseDateTimeBestEffort(workflow_created_at)) AS created_at,
            countIf(NOT {is_wait}) > 0 AS took_handoff
        FROM {_attempts(depot, pull_requests_table=None, where=where)}
        GROUP BY github_run_id
        HAVING countIf({is_wait}) > 0
    )"""


def _declined_handoffs(handoffs: str) -> str:
    """The Depot workflows that waited for a hand-off that never came, and passed."""
    return f"SELECT github_run_id FROM {handoffs} WHERE NOT took_handoff AND workflow_status = 'finished'"


def _executed_attempts(depot: DepotJobAttempts, handoffs: str, pull_requests_table: str | None) -> str:
    return f"""(
        SELECT * FROM {_attempts(depot, pull_requests_table)}
        WHERE github_run_id NOT IN ({_declined_handoffs(handoffs)})
    )"""


@frozen
class _ShellScan:
    """Predicates over the raw GitHub rows that bound the scans of ``_github_shells``."""

    runs: str
    jobs: str
    handoff_jobs: str


def _whole_history_shell_scan(jobs_table: str, handoffs: str) -> _ShellScan:
    # No hand-off job predates Depot's first hand-off, so the day before it floors the hand-off and relay jobs.
    floor = f"(SELECT toString(subtractDays(toDate(min(created_at)), 1)) FROM {handoffs})"
    handoff_jobs = f"created_at >= {floor}"
    # A run can recover weeks after its failed attempt, so the failure check has no date floor. Every attempt
    # keeps the id of its run, so an id bound cannot cut an attempt. Run ids grow with time, so the first run
    # that handed off is a bound a scan can skip files on.
    first_run = f"""(
        SELECT min(run_id) FROM {jobs_table}
        WHERE name = '{_GITHUB_HANDOFF_JOB}' AND conclusion = 'success' AND {handoff_jobs}
    )"""
    return _ShellScan(runs=f"id >= {first_run}", jobs=f"run_id >= {first_run}", handoff_jobs=handoff_jobs)


def _windowed_shell_scan(window: CreatedWindow) -> _ShellScan:
    # A job is created after its run, so the jobs of the runs in the window start at the window. The
    # failure check reads the attempts of a re-run only as far as the window reaches after its end.
    return _ShellScan(runs=window.rows(), jobs=window.rows_and_later(), handoff_jobs="1")


def _github_shells(jobs_table: str, runs_table: str, handoffs: str, scan: _ShellScan) -> str:
    handed_off = f"name = '{_GITHUB_HANDOFF_JOB}' AND conclusion = 'success' AND {scan.handoff_jobs}"
    relays = f"""
        SELECT run_id
        FROM {jobs_table}
        WHERE {scan.jobs}
        GROUP BY run_id
        HAVING countIf({handed_off}) > 0
            AND argMaxIf(
                ifNull(conclusion, ''), tuple(run_attempt, id), name = '{_GITHUB_RELAY_JOB}' AND {scan.handoff_jobs}
            ) = 'success'
            AND countIf(conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})) = 0
    """
    # The runs builder parses JSON columns on every row, so the raw columns narrow its input first.
    successful_relays = f"{scan.runs} AND {SUCCESSFUL_RUN_CONDITION} AND id IN ({relays})"
    return f"""
        SELECT r.id
        FROM ({workflow_runs.build_query(f"({_github_runs(runs_table, successful_relays)})")}) AS r
        WHERE (r.head_sha, r.pr_number) IN (
            SELECT head_sha, pr_number FROM {handoffs}
            WHERE took_handoff AND pr_number > 0 AND workflow_status = 'finished'
        )
    """


# UNION ALL matches columns by position, so the GitHub selects name them in the contract order the
# Depot side follows.
def _github_runs(table: str, where: str = "1", extra_columns: str = "") -> str:
    return f"""SELECT {", ".join(WORKFLOW_RUNS_COLUMNS)}, 'github_actions' AS ci_engine,
        toString(id) AS native_run_id, toString(id) AS native_workflow_run_id{extra_columns}
        FROM {table} WHERE {where}"""


def _github_jobs(table: str, where: str = "1") -> str:
    return f"""SELECT {", ".join(WORKFLOW_JOBS_COLUMNS)}, 'github_actions' AS ci_engine,
        toString(run_id) AS native_run_id, toString(run_id) AS native_workflow_run_id,
        toString(id) AS native_job_id, toString(id) AS native_attempt_id
        FROM {table} WHERE {where}"""


def with_depot_runs(
    runs_table: str, depot: DepotJobAttempts | None, pull_requests_table: str | None, jobs_table: str | None
) -> str:
    """The GitHub runs table, or a subquery that also holds the Depot CI runs when they are synced.

    Successful hand-off shells are left out. Without ``jobs_table`` the GitHub shells stay.
    """
    if depot is None:
        return f"({_github_runs(runs_table)})"
    handoffs = _handoff_workflows(depot)
    where = "1"
    if jobs_table:
        scan = _whole_history_shell_scan(jobs_table, handoffs)
        where = f"id NOT IN ({_github_shells(jobs_table, runs_table, handoffs, scan)})"
    depot_runs = _runs(_executed_attempts(depot, handoffs, pull_requests_table))
    return f"({_github_runs(runs_table, where)} UNION ALL {depot_runs})"


# The two columns a stored run row adds to the raw runs contract.
WINDOWED_RUN_COLUMNS = ("run_started_at_raw", "is_handoff_shell")


def windowed_runs(
    runs_table: str,
    depot: DepotJobAttempts | None,
    pull_requests_table: str | None,
    jobs_table: str,
    window: CreatedWindow,
) -> str:
    """The runs of both engines that were created inside ``window``, with ``WINDOWED_RUN_COLUMNS``.

    A hand-off shell stays and is flagged, where ``with_depot_runs`` drops it. A stored job row
    cannot tell a dropped run from a run that never synced, and it needs that to leave the jobs of a
    shell out.
    """
    raw_start = ", run_started_at AS run_started_at_raw"
    if depot is None:
        return f"({_github_runs(runs_table, window.rows(), f'{raw_start}, 0 AS is_handoff_shell')})"
    handoffs = _handoff_workflows(depot, window.rows_and_around("a.workflow_created_at"))
    shells = _github_shells(jobs_table, runs_table, handoffs, _windowed_shell_scan(window))
    github_runs = _github_runs(runs_table, window.rows(), f"{raw_start}, id IN ({shells}) AS is_handoff_shell")
    depot_runs = _runs(
        _attempts(depot, pull_requests_table, window.rows("a.workflow_created_at")),
        f""",
            any(workflow_started_at) AS run_started_at_raw,
            github_run_id IN ({_declined_handoffs(handoffs)}) AS is_handoff_shell""",
    )
    return f"({github_runs} UNION ALL {depot_runs})"


def windowed_jobs(jobs_table: str, depot: DepotJobAttempts | None, window: CreatedWindow) -> workflow_jobs.JobsTable:
    """The job attempts of both engines that were created inside ``window``.

    The jobs of a hand-off shell stay. A reader leaves them out through the flag on their run. The
    source of the duplicate scan starts earlier, because the first listing of a job row can be older
    than its re-listed copy.
    """
    rows = _github_jobs(jobs_table, window.rows())
    duplicates = _github_jobs(jobs_table, window.rows_and_earlier())
    if depot is None:
        return workflow_jobs.JobsTable(rows=f"({rows})", duplicates=f"({duplicates})")
    # Depot lists the copies of an attempt next to it, under the same start time, so its rows hold
    # their own duplicates. A later attempt of the run decides how many copies an attempt gets.
    depot_jobs = _jobs(
        _attempts(depot, pull_requests_table=None, where=window.rows("a.attempt_started_at")),
        run_attempts=_attempts(depot, pull_requests_table=None, where=window.rows_and_later("a.attempt_started_at")),
    )
    return workflow_jobs.JobsTable(
        rows=f"({rows} UNION ALL {depot_jobs})",
        duplicates=f"({duplicates} UNION ALL {depot_jobs})",
    )


def with_depot_jobs(jobs_table: str, depot: DepotJobAttempts | None, runs_table: str) -> workflow_jobs.JobsTable:
    """The GitHub jobs table, or a subquery that also holds the Depot CI job attempts when they are synced.

    Hand-off shells are left out of the rows, as in ``with_depot_runs``. They stay in the source of the
    duplicate scan, so a jobs read builds the shell filter once. Depot job rows carry no branch: the jobs
    builder scans its source twice, so a PR snapshot lookup here would cost two PR scans per jobs read. A
    reader that joins a job to its run reads the branch through ``workflow_jobs.branch``, which falls back
    to the run's.
    """
    if depot is None:
        return workflow_jobs.JobsTable.of(f"({_github_jobs(jobs_table)})")
    handoffs = _handoff_workflows(depot)
    scan = _whole_history_shell_scan(jobs_table, handoffs)
    where = f"run_id NOT IN ({_github_shells(jobs_table, runs_table, handoffs, scan)})"
    depot_jobs = _jobs(_executed_attempts(depot, handoffs, pull_requests_table=None))
    every_depot_job = _jobs(_attempts(depot, pull_requests_table=None))
    return workflow_jobs.JobsTable(
        rows=f"({_github_jobs(jobs_table, where)} UNION ALL {depot_jobs})",
        duplicates=f"({_github_jobs(jobs_table)} UNION ALL {every_depot_job})",
    )
