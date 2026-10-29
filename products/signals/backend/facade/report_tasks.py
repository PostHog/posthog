"""Report and task links for the tasks product, which creates and runs the tasks a report starts.

The cap and record writes do not open a transaction. The tasks product creates the task row in
the same transaction, so the caller owns it. Each function calls its implementation through the
module attribute, so a test that patches the implementation also changes what callers see.
"""

from products.signals.backend import report_task_actions, task_run_artefacts, tracker_issues
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.task_run_artefacts import ReportTaskCapExceeded

__all__ = [
    "ReportTaskCapExceeded",
    "create_tracker_issue_for_report",
    "delete_report_task_artefact",
    "enforce_report_implementation_rerun_cap",
    "enforce_report_task_cap",
    "is_pull_request_run_request",
    "is_report_implementation_task",
    "record_report_task",
    "release_quota_cancelled_implementation",
    "report_task_ids",
]


def is_pull_request_run_request(description: str | None) -> bool:
    return report_task_actions.is_pull_request_run_request(description)


def enforce_report_task_cap(
    *,
    team_id: int,
    report_id: str,
    relationship: str | None,
    description: str | None = None,
    created_by_id: int | None = None,
) -> None:
    """Raise ``ReportTaskCapExceeded`` at the limit.

    Call it inside the transaction that creates the task, because it locks the report row until
    commit. That lock makes concurrent creates for one report wait for each other.
    """
    task_run_artefacts.enforce_report_task_cap(
        team_id=team_id,
        report_id=report_id,
        relationship=relationship,
        description=description,
        created_by_id=created_by_id,
    )


def record_report_task(*, team_id: int, report_id: str, task_id: str, relationship: str | None = None) -> str:
    """Record that the task belongs to the report. Return the id of the work-log artefact it writes."""
    artefact = task_run_artefacts.record_report_task(
        team_id=team_id, report_id=report_id, task_id=task_id, relationship=relationship
    )
    return str(artefact.id)


def delete_report_task_artefact(*, team_id: int, artefact_id: str) -> None:
    """Delete the work-log artefact that ``record_report_task`` wrote, when the task fails to start."""
    SignalReportArtefact.objects.filter(team_id=team_id, id=artefact_id).delete()


def report_task_ids(*, team_id: int, report_id: str) -> list[str]:
    """The ids of the tasks linked to the report, from the work log and the legacy gate rows."""
    return [str(entry.task_id) for entry in SignalReport.associated_task_runs(report_id=report_id, team_id=team_id)]


def is_report_implementation_task(*, team_id: int, report_id: str, task_id: str) -> bool:
    return task_run_artefacts.is_report_implementation_task(team_id=team_id, report_id=report_id, task_id=task_id)


def enforce_report_implementation_rerun_cap(*, team_id: int, report_id: str, task_id: str) -> None:
    task_run_artefacts.enforce_report_implementation_rerun_cap(team_id=team_id, report_id=report_id, task_id=task_id)


def release_quota_cancelled_implementation(*, team_id: int, task_id: str) -> list[str]:
    """Remove the implementation records of a quota-cancelled task so its reports can run again.

    Return the ids of the affected reports.
    """
    return task_run_artefacts.release_quota_cancelled_implementation(team_id=team_id, task_id=task_id)


def create_tracker_issue_for_report(*, team_id: int, report_id: str, repository: str) -> None:
    """Open the tracker issue for the report's upcoming pull request. A provider failure does not raise."""
    tracker_issues.create_tracker_issue_for_report(team_id=team_id, report_id=report_id, repository=repository)
