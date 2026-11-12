"""The jobs of a workflow run. Job rows are an optional source, so every read returns its empty
value when they are not synced."""

import json
from datetime import UTC, datetime
from typing import Any

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import CIEngine, WorkflowJob, WorkflowJobStep
from products.engineering_analytics.backend.logic.cost import (
    billed_elapsed_seconds,
    estimate_job_cost_usd,
    runner_descriptor,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._workflow_filters import (
    UNPAGED_SCAN_LIMIT,
    run_windowed_job_created_floor_constant,
)

# HogQL returns 100 rows when a query names no LIMIT, which would drop the latest-starting jobs of a
# large run. A date floor could hide an earlier attempt's failure or make a re-listed job look billable.
_SELECT = """
    SELECT id, run_id, run_attempt, name, status, conclusion, labels, runner_name, started_at, completed_at, duration_seconds, provisioning_seconds, is_rerun_copy,
        ci_engine, native_run_id, native_workflow_run_id, native_job_id, native_attempt_id, steps
    FROM __JOBS_SOURCE__ AS j
    WHERE run_id = {run_id} AND ({ci_engine} IS NULL OR ci_engine = {ci_engine})
        AND ({job_id} IS NULL OR id = {job_id})
    ORDER BY started_at ASC, id ASC
    LIMIT 1000000
"""

# A re-listed row can keep the creation time of the attempt that ran it, which is before its run's
# newest start. This read therefore takes the wide scan floor, so an attempt keeps its whole job list.
# is_rerun_copy and the cost are not exact under a floor, so callers must not rely on them here.
_RUN_ATTEMPTS_SELECT = f"""
    SELECT id, run_id, run_attempt, name, status, conclusion, labels, runner_name, started_at, completed_at, duration_seconds, provisioning_seconds, is_rerun_copy,
        ci_engine, native_run_id, native_workflow_run_id, native_job_id, native_attempt_id, __STEPS__
    FROM __JOBS_SOURCE__ AS j
    WHERE run_id IN {{run_ids}} AND ci_engine = {{ci_engine}} __JOB_NAME__
    ORDER BY started_at ASC, id ASC
    LIMIT {UNPAGED_SCAN_LIMIT}
"""

_LATEST_ATTEMPT_SELECT = """
    SELECT ci_engine, max(run_attempt)
    FROM __RUNS_SOURCE__ AS r
    WHERE id = {run_id}
    GROUP BY ci_engine
"""


def query_workflow_jobs(
    *, curated: CuratedGitHubSource, run_id: int, run_attempt: int | None = None, ci_engine: CIEngine | None = None
) -> list[WorkflowJob]:
    jobs_source = curated.jobs_source(include_steps=True, scoped=True)
    if jobs_source is None:
        return []
    # Without an engine, the runs read is also what rejects a run id that two engines share.
    latest_attempt = (
        _latest_run_attempt(curated=curated, run_id=run_id, ci_engine=ci_engine)
        if run_attempt is None or ci_engine is None
        else None
    )
    response = curated.run(
        curated.scoped_to_run(_SELECT.replace("__JOBS_SOURCE__", jobs_source)),
        query_type="engineering_analytics.workflow_jobs",
        placeholders={
            "run_id": ast.Constant(value=run_id),
            "ci_engine": ast.Constant(value=ci_engine.value if ci_engine is not None else None),
            "job_id": ast.Constant(value=None),
        },
    )
    rows = list(response.results or [])
    if len({row[13] for row in rows}) > 1:
        raise ValueError("Ambiguous run_id; specify ci_engine.")
    target_attempt = run_attempt
    if target_attempt is None:
        # The latest attempt comes from the runs source, because job rows can sync later than the run
        # and would then show an older attempt's jobs as current.
        target_attempt = latest_attempt
        if target_attempt is None:
            attempts = [int(row[2]) for row in rows if row[2] is not None]
            target_attempt = max(attempts) if attempts else None
    if target_attempt is not None:
        rows = [row for row in rows if row[2] is not None and int(row[2]) == target_attempt]
    return [_to_job(row) for row in rows]


def query_workflow_job(
    *, curated: CuratedGitHubSource, run_id: int, job_id: int, ci_engine: CIEngine | None = None
) -> WorkflowJob | None:
    """One job of a run, whichever attempt it belongs to, or None when the source has no such job."""
    jobs_source = curated.jobs_source(include_steps=True, scoped=True)
    if jobs_source is None:
        return None
    response = curated.run(
        curated.scoped_to_run(_SELECT.replace("__JOBS_SOURCE__", jobs_source)),
        query_type="engineering_analytics.workflow_job",
        placeholders={
            "run_id": ast.Constant(value=run_id),
            "ci_engine": ast.Constant(value=ci_engine.value if ci_engine is not None else None),
            "job_id": ast.Constant(value=job_id),
        },
    )
    rows = list(response.results or [])
    if len({row[13] for row in rows}) > 1:
        raise ValueError("Ambiguous job_id; specify ci_engine.")
    if not rows:
        return None
    # A Depot CI job that a later run attempt did not re-run is listed again under that attempt with the
    # same id. The row that ran sorts first, then the latest attempt.
    return _to_job(min(rows, key=lambda row: (bool(row[12]), -int(row[2] or 0))))


def query_jobs_by_run(
    *,
    curated: CuratedGitHubSource,
    ci_engine: CIEngine,
    run_attempts: dict[int, int],
    earliest_run_started_at: datetime,
    job_name: str | None = None,
    include_steps: bool = False,
) -> dict[int, list[WorkflowJob]]:
    """Jobs keyed by run id, for the attempt ``run_attempts`` names per run. ``earliest_run_started_at``
    must be no later than any of those runs' starts. Steps are empty unless ``include_steps`` is set."""
    jobs_source = curated.jobs_source(created_floor=True, since=earliest_run_started_at, include_steps=include_steps)
    if jobs_source is None or not run_attempts:
        return {}
    placeholders: dict[str, ast.Expr] = {
        "run_ids": ast.Constant(value=sorted(run_attempts)),
        "ci_engine": ast.Constant(value=ci_engine.value),
        "job_created_floor": run_windowed_job_created_floor_constant(earliest_run_started_at),
    }
    if job_name is not None:
        placeholders["job_name"] = ast.Constant(value=job_name)
    response = curated.run(
        _RUN_ATTEMPTS_SELECT.replace("__JOBS_SOURCE__", jobs_source)
        .replace("__STEPS__", "steps" if include_steps else "'' AS steps")
        .replace("__JOB_NAME__", "AND name = {job_name}" if job_name is not None else ""),
        query_type="engineering_analytics.workflow_jobs_by_run",
        placeholders=placeholders,
    )
    jobs_by_run: dict[int, list[WorkflowJob]] = {}
    for row in response.results or []:
        row_run_id, row_attempt = row[1], row[2]
        if row_run_id is None or row_attempt is None or run_attempts.get(int(row_run_id)) != int(row_attempt):
            continue
        jobs_by_run.setdefault(int(row_run_id), []).append(_to_job(row))
    return jobs_by_run


def _latest_run_attempt(*, curated: CuratedGitHubSource, run_id: int, ci_engine: CIEngine | None) -> int | None:
    response = curated.run(
        curated.scoped_to_run(
            _LATEST_ATTEMPT_SELECT.replace("__RUNS_SOURCE__", curated.run_source(live=True, scoped=True))
        ),
        query_type="engineering_analytics.workflow_jobs_latest_attempt",
        placeholders={"run_id": ast.Constant(value=run_id)},
    )
    rows = response.results or []
    if ci_engine is not None:
        rows = [row for row in rows if row[0] == ci_engine]
    if len(rows) > 1:
        raise ValueError("Ambiguous run_id; specify ci_engine.")
    if not rows or rows[0][1] is None:
        return None
    return int(rows[0][1])


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
        provisioning,
        is_rerun_copy,
        ci_engine,
        native_run_id,
        native_workflow_run_id,
        native_job_id,
        native_attempt_id,
        steps_raw,
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
        ci_engine=CIEngine(ci_engine),
        native_run_id=native_run_id,
        native_workflow_run_id=native_workflow_run_id,
        native_job_id=native_job_id,
        native_attempt_id=native_attempt_id,
        steps=_parse_steps(steps_raw),
        # Cost uses the billed clock, which is duration_seconds minus runner boot. A row that was
        # listed again under this attempt without running costs nothing.
        estimated_cost_usd=estimate_job_cost_usd(
            labels,
            billed_elapsed_seconds(duration_seconds, provisioning),
            is_rerun_copy=bool(is_rerun_copy),
        ),
    )


def _parse_labels(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _parse_steps(raw: Any) -> list[WorkflowJobStep]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    steps = [_to_step(item, position) for position, item in enumerate(parsed, start=1) if isinstance(item, dict)]
    return sorted(steps, key=lambda step: step.number)


def _to_step(item: dict[str, Any], position: int) -> WorkflowJobStep:
    number = item.get("number")
    started_at = _parse_timestamp(item.get("started_at"))
    completed_at = _parse_timestamp(item.get("completed_at"))
    return WorkflowJobStep(
        number=number if isinstance(number, int) else position,
        name=str(item.get("name") or ""),
        status=str(item.get("status") or ""),
        conclusion=str(item["conclusion"]) if item.get("conclusion") else None,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=(
            max(int((completed_at - started_at).total_seconds()), 0) if started_at and completed_at else None
        ),
    )


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    # A step duration subtracts two of these, and Python raises TypeError when only one of them has an offset.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
