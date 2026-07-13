"""HogQL assembly of a pull request's CI failure logs from the Logs product.

The CI job-logs worker emits one Logs record per failure-line, tagged with the GitHub ``run_id`` /
``job_id`` (service ``github-ci-logs``). This resolves a PR to its workflow runs via the same
``pull_requests`` attribution as ``pr_runs`` (SPEC §7 — never a head-SHA join, so every push is
captured), then reads the Logs product joined on ``run_id`` and groups the lines per failed job.

Two caps bound the response: ``_PER_JOB_CAP`` lines per job, and ``_LINE_CAP`` lines overall. Rows
come back newest-run-first, so when the overall cap bites it drops the *oldest* runs (the newest push
— what a caller usually wants — is returned whole) and the tail job it clips is flagged ``truncated``.

Reads the ``logs`` table, not the warehouse — the failure logs live in the Logs product.
"""

import dataclasses
from itertools import groupby

from posthog.hogql import ast

from posthog.clickhouse.workload import Workload

from products.engineering_analytics.backend.facade.contracts import (
    CIFailureLogLine,
    CIFailureLogs,
    CIJobFailureLog,
    RepoRef,
    RunFailureLogs,
)
from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME as _SERVICE_NAME
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pr_runs import query_pr_runs

# Overall safety bound on lines pulled per call (one Logs record == one line) — an incident across
# many runs mustn't return an unbounded body.
_LINE_CAP = 2000
# Per-job line cap so one job can't crowd the others out of the overall cap.
_PER_JOB_CAP = 300

# Newest run first (so the overall LIMIT drops the oldest runs, not the latest push), then job, then
# seq — the emitter's 0-based emit order, since omission markers carry no timestamp to order by.
# run_id / job_id / orig_total / orig_line are string map values; one record is one line.
_SELECT = """
    SELECT
        attributes['run_id'] AS run_id,
        attributes['job_id'] AS job_id,
        attributes['conclusion'] AS conclusion,
        attributes['branch'] AS branch,
        attributes['orig_total'] AS orig_total,
        attributes['orig_line'] AS orig_line,
        body
    FROM logs
    WHERE service_name = {service_name} AND attributes['run_id'] IN {run_ids}
    ORDER BY toInt(attributes['run_id']) DESC, toInt(attributes['job_id']), toInt(attributes['seq'])
    LIMIT {line_cap}
"""


def _to_int(value: str | None) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _group_jobs(rows: list[tuple]) -> list[CIJobFailureLog]:
    # Rows arrive grouped by (run_id, job_id) and ordered by seq within a job, so consecutive rows of a
    # job are contiguous and in order — group them, cap the lines, and carry the per-job conclusion /
    # branch / orig_total (same on every line of a job) from the first row.
    jobs: list[CIJobFailureLog] = []
    for (run_id, job_id), group in groupby(rows, key=lambda row: (row[0], row[1])):
        group_rows = list(group)
        first = group_rows[0]
        # orig_line is absent ('' from the map) on omission markers, and a real line is 1-based, so
        # `or None` maps the empty/zero case to "no original line".
        lines = [CIFailureLogLine(original_line=_to_int(row[5]) or None, text=row[6]) for row in group_rows]
        capped = lines[:_PER_JOB_CAP]
        jobs.append(
            CIJobFailureLog(
                job_id=_to_int(job_id),
                run_id=_to_int(run_id),
                conclusion=first[2] or "",
                branch=first[3] or "",
                original_total_lines=_to_int(first[4]),
                line_count=len(capped),
                lines=capped,
                truncated=len(lines) > _PER_JOB_CAP,
            )
        )
    return jobs


def query_ci_failure_logs(
    *,
    curated: CuratedGitHubSource,
    pr_number: int,
    repo_owner: str,
    repo_name: str,
) -> CIFailureLogs:
    repo = RepoRef(provider="github", owner=repo_owner, name=repo_name)
    runs = query_pr_runs(curated=curated, pr_number=pr_number, repo_owner=repo_owner, repo_name=repo_name)
    run_ids = [run.id for run in runs]
    if not run_ids:
        # No runs attributed (CI hasn't run, or a fork PR with no association) — nothing to join on.
        return CIFailureLogs(
            pr_number=pr_number, repo=repo, runs_attributed=0, logs_available=False, jobs=[], truncated=False
        )

    response = curated.run(
        _SELECT,
        query_type="engineering_analytics.ci_failure_logs",
        placeholders={
            "service_name": ast.Constant(value=_SERVICE_NAME),
            "run_ids": ast.Constant(value=[str(run_id) for run_id in run_ids]),
            # +1 so a full page tells us the overall cap was hit (more lines exist than returned).
            "line_cap": ast.Constant(value=_LINE_CAP + 1),
        },
        # The logs table lives on the LOGS ClickHouse cluster, not the warehouse default.
        workload=Workload.LOGS,
    )
    rows = response.results or []
    overall_truncated = len(rows) > _LINE_CAP
    jobs = _group_jobs(rows[:_LINE_CAP])
    if overall_truncated and jobs:
        # The overall cap clips the tail of the oldest run still in range (rows are newest-run-first),
        # so that last job's lines are an undercount, not a complete log — flag it rather than let its
        # per-job `truncated` read False and pass as whole.
        jobs[-1] = dataclasses.replace(jobs[-1], truncated=True)
    return CIFailureLogs(
        pr_number=pr_number,
        repo=repo,
        runs_attributed=len(run_ids),
        logs_available=bool(rows),
        jobs=jobs,
        truncated=overall_truncated,
    )


# Existence probe for the source-authorization check below.
_RUN_IN_SOURCE = """
    SELECT 1
    FROM __RUNS_SOURCE__ AS r
    WHERE id = {run_id}
    LIMIT 1
"""


def query_run_failure_logs(*, curated: CuratedGitHubSource, run_id: int) -> RunFailureLogs:
    """Same log substrate as ``query_ci_failure_logs``, keyed directly by one run id — for surfaces
    that aren't PR-scoped (the default-branch failures feed and the run page)."""
    # The Logs table is team-scoped, not source-scoped — prove the run exists in the caller's
    # authorized source before reading its logs, or a known run id would leak another source's logs.
    in_source = curated.run(
        _RUN_IN_SOURCE.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.run_failure_logs_source_check",
        placeholders={"run_id": ast.Constant(value=run_id)},
    )
    if not in_source.results:
        return RunFailureLogs(run_id=run_id, logs_available=False, jobs=[], truncated=False)

    response = curated.run(
        _SELECT,
        query_type="engineering_analytics.run_failure_logs",
        placeholders={
            "service_name": ast.Constant(value=_SERVICE_NAME),
            "run_ids": ast.Constant(value=[str(run_id)]),
            "line_cap": ast.Constant(value=_LINE_CAP + 1),
        },
        workload=Workload.LOGS,
    )
    rows = response.results or []
    overall_truncated = len(rows) > _LINE_CAP
    jobs = _group_jobs(rows[:_LINE_CAP])
    if overall_truncated and jobs:
        jobs[-1] = dataclasses.replace(jobs[-1], truncated=True)
    return RunFailureLogs(run_id=run_id, logs_available=bool(rows), jobs=jobs, truncated=overall_truncated)
