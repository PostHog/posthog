"""Resolve implementation PR URLs linked to signal reports."""

from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.tasks.backend.facade import api as tasks_facade


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL from the latest implementation task run for each report, when available.

    The task↔report association comes from `SignalReport.associated_task_runs_for_reports` (the
    unified view of the `task_run` artefact log + legacy gate rows, batched over the whole page);
    the facade then resolves the latest PR-bearing run for each task, so multiple runs of a task
    collapse to the newest PR.
    """
    if not report_ids:
        return {}

    # (report_id, task_id) for each report's implementation task(s); signals owns this mapping.
    # Batched across the whole page so association costs two queries, not two per report (N+1).
    runs_by_report = SignalReport.associated_task_runs_for_reports(
        report_ids=[str(report_id) for report_id in report_ids],
        product=SIGNALS_PRODUCT,
        type=TASK_RUN_TYPE_IMPLEMENTATION,
    )
    pairs: list[tuple[str, str]] = [
        (report_id, run.task_id) for report_id, runs in runs_by_report.items() for run in runs
    ]
    if not pairs:
        return {}

    pr_url_by_task = tasks_facade.get_latest_pr_url_by_task([task_id for _, task_id in pairs])

    result: dict[str, str] = {}
    for report_id, task_id in pairs:
        pr_url = pr_url_by_task.get(task_id)
        if pr_url and report_id not in result:
            result[report_id] = pr_url
    return result
