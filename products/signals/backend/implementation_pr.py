"""Resolve implementation PR URLs linked to signal reports."""

from django.db.models.fields.json import KeyTextTransform

from products.signals.backend.models import SignalReportTask
from products.tasks.backend.models import TaskRun


def fetch_implementation_pr_urls_for_reports(report_ids: list[str]) -> dict[str, str]:
    """PR URL from the latest implementation task run for each report, when available."""
    if not report_ids:
        return {}

    latest_runs = (
        TaskRun.objects.filter(
            task__signal_report_tasks__report_id__in=report_ids,
            task__signal_report_tasks__relationship=SignalReportTask.Relationship.IMPLEMENTATION,
            output__pr_url__isnull=False,
        )
        .exclude(output__pr_url="")
        .order_by("task__signal_report_tasks__report_id", "-created_at", "-id")
        .annotate(output_pr_url_text=KeyTextTransform("pr_url", "output"))
        .values("task__signal_report_tasks__report_id", "output_pr_url_text")
        .distinct("task__signal_report_tasks__report_id")
    )

    return {
        str(row["task__signal_report_tasks__report_id"]): row["output_pr_url_text"]
        for row in latest_runs
        if row["task__signal_report_tasks__report_id"] and row["output_pr_url_text"]
    }
