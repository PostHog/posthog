"""HogQL assembly of a pull request's CI failure logs from the Logs product.

The CI job-logs worker emits one Logs record per failure-line, tagged with ``ci_engine`` / ``run_id`` /
``job_id`` (service ``github-ci-logs``). This resolves a PR to its workflow runs via the same
``pull_requests`` attribution as ``pr_runs`` (SPEC §6 — never a head-SHA join, so every push is
captured), then reads the Logs product joined on engine-qualified run identity and groups the lines per failed job.

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
    CIEngine,
    CIFailureLogLine,
    CIFailureLogs,
    CIJobFailureLog,
    RepoRef,
    RunFailureLogs,
)
from products.engineering_analytics.backend.logic.job_logs.constants import CI_LOGS_SERVICE_NAME as _SERVICE_NAME
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.pr_runs import query_pr_runs
from products.engineering_analytics.backend.logic.queries.workflow_run import query_workflow_run

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
        body,
        attributes['ci_engine'] AS ci_engine
    FROM logs
    WHERE service_name = {service_name} AND lower(attributes['repo']) = lower({repository})
        AND (
            (attributes['ci_engine'], attributes['run_id']) IN {run_keys}
            OR (attributes['ci_engine'] = '' AND attributes['run_id'] IN {legacy_run_ids})
        )
    ORDER BY toInt(attributes['run_id']) DESC, attributes['ci_engine'], toInt(attributes['job_id']), toInt(attributes['seq'])
    LIMIT {line_cap}
"""


def _to_int(value: str | None) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _group_jobs(rows: list[tuple]) -> list[CIJobFailureLog]:
    # Rows arrive grouped by (ci_engine, run_id, job_id) and ordered by seq within a job, so consecutive rows of a
    # job are contiguous and in order — group them, cap the lines, and carry the per-job conclusion /
    # branch / orig_total (same on every line of a job) from the first row.
    jobs: list[CIJobFailureLog] = []
    for (ci_engine, run_id, job_id), group in groupby(rows, key=lambda row: (row[7], row[0], row[1])):
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
                ci_engine=CIEngine(ci_engine) if ci_engine else None,
                conclusion=first[2] or "",
                branch=first[3] or "",
                original_total_lines=_to_int(first[4]),
                line_count=len(capped),
                lines=capped,
                truncated=len(lines) > _PER_JOB_CAP,
            )
        )
    return jobs


def _legacy_run_ids(*, curated: CuratedGitHubSource, run_ids: list[int]) -> list[str]:
    # Old records did not stamp an engine. Keep them only for IDs with one engine in the source.
    response = curated.run(
        f"SELECT id FROM {curated.run_source()} AS r WHERE id IN {{run_ids}} "
        "GROUP BY id HAVING uniq(ci_engine) = 1 LIMIT 1000000",
        query_type="engineering_analytics.failure_logs_legacy_identity",
        placeholders={"run_ids": ast.Constant(value=run_ids)},
    )
    return [str(row[0]) for row in response.results or []]


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
            "repository": ast.Constant(value=f"{repo_owner}/{repo_name}"),
            "run_keys": ast.Constant(
                value=[(run.ci_engine.value if run.ci_engine is not None else None, str(run.id)) for run in runs]
            ),
            "legacy_run_ids": ast.Constant(value=_legacy_run_ids(curated=curated, run_ids=run_ids)),
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


def query_run_failure_logs(
    *, curated: CuratedGitHubSource, run_id: int, ci_engine: CIEngine | None = None
) -> RunFailureLogs:
    """Same log substrate as ``query_ci_failure_logs``, keyed directly by one run id — for surfaces
    that aren't PR-scoped (the default-branch failures feed and the run page)."""
    # The Logs table is team-scoped, not source-scoped — prove the run exists in the caller's
    # authorized source before reading its logs, or a known run id would leak another source's logs.
    run = query_workflow_run(curated=curated, run_id=run_id, ci_engine=ci_engine)
    if run is None:
        return RunFailureLogs(run_id=run_id, logs_available=False, jobs=[], truncated=False)

    response = curated.run(
        _SELECT,
        query_type="engineering_analytics.run_failure_logs",
        placeholders={
            "service_name": ast.Constant(value=_SERVICE_NAME),
            "repository": ast.Constant(value=f"{run.repo.owner}/{run.repo.name}"),
            "run_keys": ast.Constant(value=[(run.ci_engine.value if run.ci_engine is not None else None, str(run_id))]),
            "legacy_run_ids": ast.Constant(value=_legacy_run_ids(curated=curated, run_ids=[run_id])),
            "line_cap": ast.Constant(value=_LINE_CAP + 1),
        },
        workload=Workload.LOGS,
    )
    rows = response.results or []
    overall_truncated = len(rows) > _LINE_CAP
    jobs = _group_jobs(rows[:_LINE_CAP])
    if overall_truncated and jobs:
        jobs[-1] = dataclasses.replace(jobs[-1], truncated=True)
    return RunFailureLogs(
        run_id=run_id, ci_engine=run.ci_engine, logs_available=bool(rows), jobs=jobs, truncated=overall_truncated
    )
