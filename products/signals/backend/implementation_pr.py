"""Resolve implementation PR URLs linked to signal reports."""

from django.db.models.fields.json import KeyTextTransform

from products.signals.backend.models import SignalReportArtefact
from products.tasks.backend.models import TaskRun


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL from the latest task run with one, across each report's associated tasks.

    Association is derived from `task_run` artefacts (their `task` attribution FK is always the
    task they record), so this is simply the newest PR produced by any task working on the
    report — matching `_annotate_implementation_pr_url` on the report viewset.
    """
    if not report_ids:
        return {}

    report_task_pairs = list(
        SignalReportArtefact.objects.filter(
            report_id__in=report_ids,
            type=SignalReportArtefact.ArtefactType.TASK_RUN,
            task_id__isnull=False,
        ).values_list("report_id", "task_id")
    )
    if not report_task_pairs:
        return {}

    task_ids = {task_id for _, task_id in report_task_pairs}
    latest_runs = (
        TaskRun.objects.filter(task_id__in=task_ids, output__pr_url__isnull=False)
        .exclude(output__pr_url="")
        .order_by("task_id", "-created_at", "-id")
        .annotate(output_pr_url_text=KeyTextTransform("pr_url", "output"))
        .values("task_id", "output_pr_url_text", "created_at")
        .distinct("task_id")
    )
    latest_by_task = {row["task_id"]: (row["created_at"], row["output_pr_url_text"]) for row in latest_runs}

    result: dict[str, str] = {}
    newest: dict[str, object] = {}
    for report_id, task_id in report_task_pairs:
        run = latest_by_task.get(task_id)
        if run is None or not run[1]:
            continue
        key = str(report_id)
        if key not in result or run[0] > newest[key]:
            result[key] = run[1]
            newest[key] = run[0]
    return result
