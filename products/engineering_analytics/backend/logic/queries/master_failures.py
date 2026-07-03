"""Curated query: default-branch failures grouped by workflow + failing job.

At this repo's volume a flat failure feed is a firehose (thousands of failing runs a
day across all branches), so the triage view groups instead — error-tracking style:
one row per (workflow, de-sharded failing job name) on the default branch, with a run
count and first/last seen. PR-branch failures are deliberately out of scope here; they
surface on their PR pages.

Two-step like the failure-logs query: fetch the window's failed default-branch runs
first (small — the branch filter does the heavy lifting), then their failed jobs by
``run_id IN``, then group in Python where the shard-stripping regex lives.
"""

import re
from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import MasterFailureGroup, RepoRef
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# Failed default-branch runs in the window is a triage view, not an archive — cap it.
_RUN_CAP = 500

_FAILED_RUNS_SELECT = f"""
    SELECT id, repo_owner, repo_name, workflow_name, run_started_at
    FROM __RUNS_SOURCE__ AS r
    WHERE run_started_at >= {{date_from}} __DATE_TO__
        AND head_branch = {{branch}}
        AND status = 'completed' AND conclusion IN ('failure', 'timed_out')
    ORDER BY run_started_at DESC
    LIMIT {_RUN_CAP}
"""

_FAILED_JOBS_SELECT = """
    SELECT run_id, name
    FROM __JOBS_SOURCE__ AS j
    WHERE run_id IN {run_ids} AND conclusion IN ('failure', 'timed_out')
"""

# Trailing "(G/N)" shard suffix, incl. nested parens ("Product tests (experiments (1/2))") —
# same rule as the frontend's jobGroups.stripShardSuffix, so both sides group identically.
_SHARD_SUFFIX = re.compile(r"\s*\((\d+)/(\d+)\)(\))?$")


def strip_shard_suffix(name: str) -> str:
    return _SHARD_SUFFIX.sub(lambda m: ")" if m.group(3) else "", name)


def query_master_failures(
    *,
    curated: CuratedGitHubSource,
    date_from: datetime,
    date_to: datetime | None,
    branch: str,
) -> list[MasterFailureGroup]:
    date_to_clause = "AND run_started_at <= {date_to}" if date_to is not None else ""
    placeholders: dict[str, ast.Expr] = {
        "date_from": ast.Constant(value=date_from),
        "branch": ast.Constant(value=branch),
    }
    if date_to is not None:
        placeholders["date_to"] = ast.Constant(value=date_to)

    runs_response = curated.run(
        _FAILED_RUNS_SELECT.replace("__RUNS_SOURCE__", curated.run_source()).replace("__DATE_TO__", date_to_clause),
        query_type="engineering_analytics.master_failures_runs",
        placeholders=placeholders,
    )
    runs = runs_response.results or []
    if not runs:
        return []

    # Failed job names per run — empty when the jobs source isn't synced, in which case
    # groups degrade to workflow-level (failed_job = '').
    jobs_by_run: dict[int, list[str]] = {}
    jobs_source = curated.jobs_source()
    if jobs_source is not None:
        jobs_response = curated.run(
            _FAILED_JOBS_SELECT.replace("__JOBS_SOURCE__", jobs_source),
            query_type="engineering_analytics.master_failures_jobs",
            placeholders={"run_ids": ast.Constant(value=[run_id for run_id, *_ in runs])},
        )
        for run_id, job_name in jobs_response.results or []:
            jobs_by_run.setdefault(run_id, []).append(job_name)

    groups: dict[tuple[str, str, str, str], dict] = {}
    for run_id, repo_owner, repo_name, workflow_name, run_started_at in runs:
        failed_jobs = {strip_shard_suffix(name) for name in jobs_by_run.get(run_id, [])} or {""}
        for failed_job in failed_jobs:
            key = (repo_owner, repo_name, workflow_name, failed_job)
            group = groups.setdefault(
                key,
                {
                    "run_ids": set(),
                    "first_seen": run_started_at,
                    "last_seen": run_started_at,
                    "latest_run_id": run_id,
                },
            )
            group["run_ids"].add(run_id)
            if run_started_at < group["first_seen"]:
                group["first_seen"] = run_started_at
            if run_started_at > group["last_seen"]:
                group["last_seen"] = run_started_at
                group["latest_run_id"] = run_id

    return sorted(
        (
            MasterFailureGroup(
                repo=RepoRef(provider="github", owner=repo_owner, name=repo_name),
                workflow_name=workflow_name,
                failed_job=failed_job,
                run_count=len(group["run_ids"]),
                first_seen=group["first_seen"],
                last_seen=group["last_seen"],
                latest_run_id=group["latest_run_id"],
            )
            for (repo_owner, repo_name, workflow_name, failed_job), group in groups.items()
        ),
        key=lambda g: g.last_seen,
        reverse=True,
    )
