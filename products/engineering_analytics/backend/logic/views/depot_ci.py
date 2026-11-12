"""Depot CI job attempts reshaped into rows of the GitHub runs and jobs tables and unioned onto them.

Each Depot workflow becomes one runs row. A hand-off shell is the run of the engine that did not run
the tests. The union drops successful shells. SPEC.md sections 6 and 7 have the rules.
"""

import re

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    DECISIVE_FAILURE_CONCLUSIONS_SQL,
    SUCCESSFUL_RUN_CONDITION,
)
from products.engineering_analytics.backend.logic.views import incremental_floor, workflow_jobs, workflow_runs
from products.engineering_analytics.backend.logic.views.source_schema import (
    OPTIONAL_WORKFLOW_RUNS_COLUMNS,
    WORKFLOW_JOBS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)

# Depot CI sets GITHUB_RUN_ID to the run id read as a base-30 number over this alphabet. The decoded
# id is what joins a run to the test traces its jobs emit.
_ID_ALPHABET = "0123456789bcdfghjklmnpqrstvwxz"

# The repository is written into HogQL as a string literal, so only a plain owner/name qualifies.
_PLAIN_REPOSITORY = re.compile(r"\A[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")


@frozen
class DepotJobAttempts:
    """A Depot ``job_attempts`` table and the one repository to read from it. A source moved to
    another repository keeps the rows it synced before the move."""

    table: str
    repository: str

    def __post_init__(self) -> None:
        if not _PLAIN_REPOSITORY.match(self.repository):
            raise ValueError(f"Not a plain owner/name repository: {self.repository!r}")

    @classmethod
    def for_repository(cls, table: str, repository: str) -> "DepotJobAttempts | None":
        """None when ``repository`` is not a plain owner/name."""
        return cls(table=table, repository=repository) if _PLAIN_REPOSITORY.match(repository) else None


# Ten base-30 digits stay below 2^53, so the Float64 powers in ``_id_to_int`` sum exactly.
_MAX_ID_LENGTH = 10

# Depot's API does not report a job's runs-on, so every attempt is costed as the default sandbox.
_DEFAULT_SANDBOX_LABELS = '["depot-ubuntu-24.04"]'

# Depot reports no repository id. The runs builder accepts a pull request association only when its
# base repository id equals the run's, so both sides get the same positive id.
_REPOSITORY_ID = 1

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
    """The integer id of a Depot workflow's runs row, or None when the id does not decode.

    A run with several workflows keys each by its workflow id, because one shared run id would fan
    out every join on it.
    """
    return depot_id_to_int(run_id if run_workflow_count == 1 else workflow_id)


def _id_to_int(column: str) -> str:
    # ClickHouse cannot sum an array of Nullable values, so the Nullable column is unwrapped first.
    value = f"ifNull({column}, '')"
    chars = f"splitByString('', {value})"
    digits = f"arrayMap((c, i) -> (position('{_ID_ALPHABET}', c) - 1) * pow(30, length({value}) - i), {chars}, arrayEnumerate({chars}))"
    return f"toInt(arraySum({digits}))"


def _conclusion(status: str) -> str:
    # `cancelled` and `skipped` are the same word in Depot's statuses and GitHub's conclusions.
    return f"multiIf({status} = 'finished', 'success', {status} = 'failed', 'failure', {status})"


def _of_repository(depot: DepotJobAttempts) -> str:
    return f"lower(ifNull(a.repo, '')) = '{depot.repository.lower()}'"


def build_billed_seconds_query(depot: DepotJobAttempts) -> str:
    """Seconds run by the finished attempts that started in ``[{window_from}, {window_to})``.

    Hand-off shells count, because Depot bills them.
    """
    return f"""
        SELECT sum(dateDiff('millisecond', started_at, finished_at)) / 1000
        FROM (
            SELECT
                parseDateTimeBestEffort(a.attempt_started_at) AS started_at,
                parseDateTimeBestEffort(a.attempt_finished_at) AS finished_at
            FROM {depot.table} AS a
            WHERE {_of_repository(depot)}
                AND ifNull(a.attempt_started_at, '') != ''
                AND ifNull(a.attempt_finished_at, '') != ''
        )
        WHERE started_at >= {{window_from}} AND started_at < {{window_to}} AND finished_at >= started_at
    """


def ref_pr_number_expr(column: str) -> str:
    return f"ifNull(toInt(extract({column}, '^refs/pull/([0-9]+)/')), 0)"


def github_run_id_expr(alias: str = "") -> str:
    """The integer id of a raw attempt's runs row. ``alias`` ends with a dot."""
    return _id_to_int(f"if({alias}run_workflow_count = 1, {alias}run_id, {alias}workflow_id)")


def head_sha_expr(alias: str = "") -> str:
    """The commit a raw attempt ran. ``alias`` ends with a dot."""
    return f"coalesce(nullIf({alias}head_sha, ''), {alias}sha)"


def _attempts(depot: DepotJobAttempts, pull_requests_table: str | None, where: str = "1") -> str:
    # Depot reports no branch, so a PR run takes its head branch from the PR snapshot.
    pr_number = ref_pr_number_expr("a.ref")
    if pull_requests_table:
        head_branch = "nullIf(pr.head_branch, '')"
        actor = "nullIf(pr.author, '')"
        branch_join = f"""
            LEFT JOIN (
                SELECT
                    number,
                    any(JSONExtractString(ifNull(head, '{{}}'), 'ref')) AS head_branch,
                    any(user) AS author
                FROM {pull_requests_table}
                GROUP BY number
            ) AS pr ON {pr_number} = pr.number"""
    else:
        head_branch = "NULL"
        actor = "NULL"
        branch_join = ""
    # A push run's id carries a prefix outside the alphabet, and such a run holds no workflows.
    return f"""(
        SELECT
            {github_run_id_expr("a.")} AS github_run_id,
            {_id_to_int("a.attempt_id")} AS github_job_id,
            {pr_number} AS pr_number,
            coalesce(nullIf(extract(ifNull(a.ref, ''), '^refs/heads/(.+)$'), ''), {head_branch}) AS head_branch,
            a.repo AS repo,
            {actor} AS actor,
            {head_sha_expr("a.")} AS head_sha,
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
        WHERE {_of_repository(depot)}
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
            any(actor) AS actor,
            {OPTIONAL_WORKFLOW_RUNS_COLUMNS["workflow_id"]} AS workflow_id,
            {OPTIONAL_WORKFLOW_RUNS_COLUMNS["event"]} AS event,
            'depot_ci' AS ci_engine,
            any(native_run_id) AS native_run_id,
            any(native_workflow_run_id) AS native_workflow_run_id{extra_columns}
        FROM {attempts}
        GROUP BY github_run_id
    """


def _jobs(attempts: str, run_attempts: str | None = None) -> str:
    """``run_attempts`` holds every attempt of the runs in ``attempts``."""
    run_attempts = run_attempts or attempts
    # Depot numbers attempts per job, and GitHub lists every job under each run attempt. To match, a
    # job's last attempt is listed again under every later attempt of its run, and the jobs builder
    # flags those rows as copies.
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


def _shell_scan(jobs_table: str, handoffs: str, *, prescoped: bool) -> _ShellScan:
    # A caller that narrowed the Depot attempts to its own runs would move the floor later, past a
    # hand-off job that the whole-history read counts.
    if prescoped:
        return _ShellScan(runs="1", jobs="1", handoff_jobs="1")
    return _whole_history_shell_scan(jobs_table, handoffs)


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
    # Depot's ref names the PR of the run's own association, not the PR a merge queue is landing, so
    # the comparison uses ASSOCIATION_PR_NUMBER. The raw-column predicates come first, so the JSON
    # parse runs only on successful relays.
    return f"""
        SELECT id
        FROM {runs_table}
        WHERE {scan.runs} AND {SUCCESSFUL_RUN_CONDITION} AND id IN ({relays})
            AND (head_sha, {workflow_runs.ASSOCIATION_PR_NUMBER}) IN (
                SELECT head_sha, pr_number FROM {handoffs}
                WHERE took_handoff AND pr_number > 0 AND workflow_status = 'finished'
            )
    """


# UNION ALL matches columns by position, so the GitHub selects name them in the contract order the
# Depot side follows.
def _github_runs(
    table: str, where: str = "1", *, optional_columns: frozenset[str] = frozenset(), extra_columns: str = ""
) -> str:
    columns = [
        column
        if column not in OPTIONAL_WORKFLOW_RUNS_COLUMNS or column in optional_columns
        else f"{OPTIONAL_WORKFLOW_RUNS_COLUMNS[column]} AS {column}"
        for column in WORKFLOW_RUNS_COLUMNS
    ]
    return f"""SELECT {", ".join(columns)}, 'github_actions' AS ci_engine,
        toString(id) AS native_run_id, toString(id) AS native_workflow_run_id{extra_columns}
        FROM {table} WHERE {where}"""


def _github_jobs(table: str, where: str = "1") -> str:
    return f"""SELECT {", ".join(WORKFLOW_JOBS_COLUMNS)}, 'github_actions' AS ci_engine,
        toString(run_id) AS native_run_id, toString(run_id) AS native_workflow_run_id,
        toString(id) AS native_job_id, toString(id) AS native_attempt_id
        FROM {table} WHERE {where}"""


def with_depot_runs(
    runs_table: str,
    depot: DepotJobAttempts | None,
    pull_requests_table: str | None,
    jobs_table: str | None,
    *,
    optional_columns: frozenset[str] = frozenset(),
    prescoped: bool = False,
) -> str:
    """The runs of both engines without successful hand-off shells. Without ``jobs_table`` the
    GitHub shells stay.

    ``optional_columns`` names the ``OPTIONAL_WORKFLOW_RUNS_COLUMNS`` that ``runs_table`` has. The
    others read as NULL. ``prescoped`` says the caller already bounded every table to the runs it reads.
    """
    if depot is None:
        return f"({_github_runs(runs_table, optional_columns=optional_columns)})"
    handoffs = _handoff_workflows(depot)
    where = "1"
    if jobs_table:
        scan = _shell_scan(jobs_table, handoffs, prescoped=prescoped)
        where = f"id NOT IN ({_github_shells(jobs_table, runs_table, handoffs, scan)})"
    depot_runs = _runs(_executed_attempts(depot, handoffs, pull_requests_table))
    return f"({_github_runs(runs_table, where, optional_columns=optional_columns)} UNION ALL {depot_runs})"


STORED_RUN_COLUMNS = ("created_at_raw", "run_started_at_raw", "is_handoff_shell")


def stored_runs(
    runs_table: str,
    depot: DepotJobAttempts | None,
    pull_requests_table: str | None,
    jobs_table: str,
    *,
    optional_columns: frozenset[str] = frozenset(),
    full_history: bool = False,
) -> str:
    """The runs of both engines with ``STORED_RUN_COLUMNS``, floored at the stored window unless
    ``full_history``.

    A hand-off shell stays and is flagged, because a stored job row cannot tell a dropped run from a
    run that never synced.
    """
    floor = "1" if full_history else incremental_floor.stored_rows()
    if depot is None:
        github_runs = _github_runs(
            runs_table,
            floor,
            optional_columns=optional_columns,
            extra_columns=_stored_run_columns("0"),
        )
        return f"({github_runs})"
    handoffs = _handoff_workflows(
        depot, "1" if full_history else incremental_floor.stored_rows_and_earlier("a.workflow_created_at")
    )
    # A job is created after its run, so the jobs of the runs in the window start at the window too.
    scan = (
        _whole_history_shell_scan(jobs_table, handoffs)
        if full_history
        else _ShellScan(runs=floor, jobs=incremental_floor.stored_rows(), handoff_jobs="1")
    )
    github_runs = _github_runs(
        runs_table,
        floor,
        optional_columns=optional_columns,
        extra_columns=_stored_run_columns(f"id IN ({_github_shells(jobs_table, runs_table, handoffs, scan)})"),
    )
    depot_runs = _runs(
        _attempts(
            depot, pull_requests_table, "1" if full_history else incremental_floor.stored_rows("a.workflow_created_at")
        ),
        f""",
            ifNull(any(workflow_created_at), '') AS created_at_raw,
            ifNull(any(workflow_started_at), '') AS run_started_at_raw,
            github_run_id IN ({_declined_handoffs(handoffs)}) AS is_handoff_shell""",
    )
    return f"({github_runs} UNION ALL {depot_runs})"


def _stored_run_columns(is_handoff_shell: str) -> str:
    # The stored columns are plain strings, so a run that has not started stores ''.
    return (
        ", ifNull(created_at, '') AS created_at_raw, ifNull(run_started_at, '') AS run_started_at_raw"
        f", {is_handoff_shell} AS is_handoff_shell"
    )


def stored_jobs(jobs_table: str, depot: DepotJobAttempts | None) -> workflow_jobs.JobsTable:
    """The job attempts of both engines created in the stored window, including the jobs of hand-off
    shells.

    The source of the duplicate scan starts earlier, because the first listing of a job row can be
    older than its re-listed copy.
    """
    rows = _github_jobs(jobs_table, incremental_floor.stored_rows())
    duplicates = _github_jobs(jobs_table, incremental_floor.stored_rows_and_earlier())
    if depot is None:
        return workflow_jobs.JobsTable(rows=f"({rows})", duplicates=f"({duplicates})")
    # Depot lists the copies of an attempt next to it, so its rows hold their own duplicates. The highest
    # attempt of the run sets the number of copies, and another job can reach it on an earlier day.
    depot_jobs = _jobs(
        _attempts(depot, pull_requests_table=None, where=incremental_floor.stored_rows("a.attempt_started_at")),
        run_attempts=_attempts(
            depot, pull_requests_table=None, where=incremental_floor.stored_rows_and_earlier("a.attempt_started_at")
        ),
    )
    return workflow_jobs.JobsTable(
        rows=f"({rows} UNION ALL {depot_jobs})",
        duplicates=f"({duplicates} UNION ALL {depot_jobs})",
    )


def with_depot_jobs(
    jobs_table: str, depot: DepotJobAttempts | None, runs_table: str, *, prescoped: bool = False
) -> workflow_jobs.JobsTable:
    """The job attempts of both engines without the jobs of successful hand-off shells. The shells
    stay in the source of the duplicate scan.

    Depot job rows carry no branch, because a PR snapshot lookup here would add two PR scans to every
    jobs read. Read the branch through ``workflow_jobs.branch``, which falls back to the run's.
    ``prescoped`` is as in ``with_depot_runs``.
    """
    if depot is None:
        return workflow_jobs.JobsTable.of(f"({_github_jobs(jobs_table)})")
    handoffs = _handoff_workflows(depot)
    scan = _shell_scan(jobs_table, handoffs, prescoped=prescoped)
    where = f"run_id NOT IN ({_github_shells(jobs_table, runs_table, handoffs, scan)})"
    depot_jobs = _jobs(_executed_attempts(depot, handoffs, pull_requests_table=None))
    every_depot_job = _jobs(_attempts(depot, pull_requests_table=None))
    return workflow_jobs.JobsTable(
        rows=f"({_github_jobs(jobs_table, where)} UNION ALL {depot_jobs})",
        duplicates=f"({_github_jobs(jobs_table)} UNION ALL {every_depot_job})",
    )
