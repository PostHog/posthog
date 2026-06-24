"""HogQL assembly of a run's jobs, for the expandable job breakdown on the run rows.

Reads the curated jobs subquery (``_curated.jobs_source``) for one ``run_id``. Job-level data is an
optional source — when it isn't synced, ``jobs_source()`` is None and this returns ``[]`` so the UI
degrades to an empty breakdown instead of erroring. Per-job cost is derived from the runner tier
(parsed from ``labels``) and elapsed time via the pure cost model (``logic.cost``).
"""

import json
from typing import Any

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowJob
from products.engineering_analytics.backend.logic.cost import classify_runner, estimate_job_cost_usd
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_SELECT = """
    SELECT id, run_id, name, status, conclusion, labels, runner_name, started_at, completed_at, duration_seconds
    FROM __JOBS_SOURCE__ AS j
    WHERE run_id = {run_id}
    ORDER BY started_at ASC, id ASC
"""


def query_workflow_jobs(*, curated: CuratedGitHubSource, run_id: int) -> list[WorkflowJob]:
    jobs_source = curated.jobs_source()
    if jobs_source is None:
        # The optional job-level source isn't synced for this team yet.
        return []
    response = curated.run(
        _SELECT.replace("__JOBS_SOURCE__", jobs_source),
        query_type="engineering_analytics.workflow_jobs",
        placeholders={"run_id": ast.Constant(value=run_id)},
    )
    return [_to_job(row) for row in (response.results or [])]


def _to_job(row: tuple[Any, ...]) -> WorkflowJob:
    job_id, job_run_id, name, status, conclusion, labels_raw, runner_name, started_at, completed_at, duration = row
    labels = _parse_labels(labels_raw)
    tier = classify_runner(labels)
    duration_seconds = int(duration) if duration is not None else None
    runner_label = f"{tier.vcpu}-core" if tier else (labels[0] if labels else (runner_name or ""))
    return WorkflowJob(
        id=int(job_id),
        run_id=int(job_run_id) if job_run_id is not None else 0,
        name=name or "",
        status=status or "",
        conclusion=conclusion or None,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration_seconds,
        runner_label=runner_label,
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
