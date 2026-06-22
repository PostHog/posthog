"""Resolve implementation PR URLs linked to signal reports."""

from products.signals.backend.models import SignalReportTask
from products.signals.backend.task_run_artefacts import TASK_RUN_TYPE_IMPLEMENTATION
from products.tasks.backend.facade import api as tasks_facade


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL from the latest implementation task run for each report, when available.

    A report has a single implementation task in practice; the facade resolves the latest
    PR-bearing run for each task, so multiple runs of that task collapse to the newest PR.
    """
    if not report_ids:
        return {}

    # report_id -> task_id for the report's implementation task(s); signals owns this mapping.
    pairs = list(
        SignalReportTask.objects.filter(
            report_id__in=report_ids,
            relationship=TASK_RUN_TYPE_IMPLEMENTATION,
        )
        .order_by("report_id")
        .values_list("report_id", "task_id")
    )
    if not pairs:
        return {}

    pr_url_by_task = tasks_facade.get_latest_pr_url_by_task([task_id for _, task_id in pairs])

    result: dict[str, str] = {}
    for report_id, task_id in pairs:
        pr_url = pr_url_by_task.get(str(task_id))
        if pr_url and str(report_id) not in result:
            result[str(report_id)] = pr_url
    return result
