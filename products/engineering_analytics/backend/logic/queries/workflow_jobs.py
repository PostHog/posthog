"""HogQL assembly of a run's jobs, for the expandable job breakdown on the run rows.

Reads the curated jobs subquery (``_curated.jobs_source``) for one ``run_id``. Job-level data is an
optional source — when it isn't synced, ``jobs_source()`` is None and this returns ``[]`` so the UI
degrades to an empty breakdown instead of erroring. Per-job cost is derived from the runner tier
(parsed from ``labels``) and elapsed time via the pure cost model (``logic.cost``).

A re-run carries several attempts under one ``run_id``; scoping to a single ``run_attempt`` keeps a
row's statuses, durations, and costs from merging across attempts (and double-counting cost). The
caller passes the attempt it's showing; when omitted, the run's latest attempt is read from the runs
source (not the synced job rows) so a default lookup tracks the canonical attempt even when only older
attempts' jobs have synced — returning an empty breakdown rather than stale jobs for that case.
"""

import json
from typing import Any

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowJob
from products.engineering_analytics.backend.logic.cost import estimate_job_cost_usd, runner_descriptor
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# Explicit high LIMIT: without it HogQL caps at DEFAULT_RETURNED_ROWS (100), and since the rows are ordered
# by start, a run with >100 jobs (matrix builds, re-run attempts) would silently drop its latest-starting
# jobs — the breakdown would then miss jobs and not add up to the run's cost.
_SELECT = """
    SELECT id, run_id, run_attempt, name, status, conclusion, labels, runner_name, started_at, completed_at, duration_seconds
    FROM __JOBS_SOURCE__ AS j
    WHERE run_id = {run_id}
    ORDER BY started_at ASC, id ASC
    LIMIT 1000000
"""

_LATEST_ATTEMPT_SELECT = """
    SELECT max(run_attempt)
    FROM __RUNS_SOURCE__ AS r
    WHERE id = {run_id}
"""


def query_workflow_jobs(
    *, curated: CuratedGitHubSource, run_id: int, run_attempt: int | None = None
) -> list[WorkflowJob]:
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        # The optional job-level source isn't synced for this team yet.
        return []
    response = curated.run(
        _SELECT.replace("__JOBS_SOURCE__", jobs_source),
        query_type="engineering_analytics.workflow_jobs",
        placeholders={"run_id": ast.Constant(value=run_id)},
    )
    rows = list(response.results or [])
    target_attempt = run_attempt
    if target_attempt is None:
        # Default to the run's latest attempt per the runs source, not the synced job rows — those can
        # trail the run table during sync lag and silently serve an older attempt's jobs as current.
        target_attempt = _latest_run_attempt(curated=curated, run_id=run_id)
        if target_attempt is None:
            # Run isn't in the runs source (shouldn't normally happen); fall back to the jobs rows.
            attempts = [int(row[2]) for row in rows if row[2] is not None]
            target_attempt = max(attempts) if attempts else None
    if target_attempt is not None:
        rows = [row for row in rows if row[2] is not None and int(row[2]) == target_attempt]
    return [_to_job(row) for row in rows]


def _latest_run_attempt(*, curated: CuratedGitHubSource, run_id: int) -> int | None:
    response = curated.run(
        _LATEST_ATTEMPT_SELECT.replace("__RUNS_SOURCE__", curated.run_source()),
        query_type="engineering_analytics.workflow_jobs_latest_attempt",
        placeholders={"run_id": ast.Constant(value=run_id)},
    )
    rows = response.results or []
    if not rows or rows[0][0] is None:
        return None
    return int(rows[0][0])


def _to_job(row: tuple[Any, ...]) -> WorkflowJob:
    (
        job_id,
        job_run_id,
        _run_attempt,
        name,
        status,
        conclusion,
        labels_raw,
        runner_name,
        started_at,
        completed_at,
        duration,
    ) = row
    labels = _parse_labels(labels_raw)
    duration_seconds = int(duration) if duration is not None else None
    provider, runner_label = runner_descriptor(labels)
    return WorkflowJob(
        id=int(job_id),
        run_id=int(job_run_id) if job_run_id is not None else 0,
        name=name or "",
        status=status or "",
        conclusion=conclusion or None,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration_seconds,
        runner_provider=provider,
        runner_label=runner_label or (runner_name or ""),
        estimated_cost_usd=estimate_job_cost_usd(labels, duration_seconds),
    )


def _parse_labels(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []
