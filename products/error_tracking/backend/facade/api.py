"""Facade API for error tracking.

This is the ONLY module other apps are allowed to import.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from .. import logic, weekly_digest
from . import types as contracts

IssueNotFoundError = logic.ErrorTrackingIssueNotFoundError


def _to_issue_assignee(assignment) -> contracts.ErrorTrackingIssueAssignee | None:
    if assignment is None:
        return None

    assignee_id = assignment.user_id if assignment.user_id else str(assignment.role_id) if assignment.role_id else None
    assignee_type = "role" if assignment.role_id else "user"

    return contracts.ErrorTrackingIssueAssignee(id=assignee_id, type=assignee_type)


def _to_external_reference(reference) -> contracts.ErrorTrackingExternalReference:
    integration = reference.integration
    return contracts.ErrorTrackingExternalReference(
        id=reference.id,
        integration=contracts.ErrorTrackingExternalReferenceIntegration(
            id=integration.id,
            kind=integration.kind,
            display_name=integration.display_name,
        ),
        external_url=logic.build_external_issue_url(reference),
    )


def _to_issue_cohort(issue) -> contracts.ErrorTrackingIssueCohort | None:
    for issue_cohort in issue.cohorts.all():
        cohort = issue_cohort.cohort
        if not cohort.deleted:
            return contracts.ErrorTrackingIssueCohort(id=issue_cohort.cohort_id, name=cohort.name)
    return None


def _to_issue_preview(issue) -> contracts.ErrorTrackingIssuePreview:
    return contracts.ErrorTrackingIssuePreview(
        id=issue.id,
        status=issue.status,
        name=issue.name,
        description=issue.description,
        first_seen=getattr(issue, "first_seen", None),
        assignee=_to_issue_assignee(getattr(issue, "assignment", None)),
    )


def _to_issue(issue) -> contracts.ErrorTrackingIssue:
    return contracts.ErrorTrackingIssue(
        id=issue.id,
        status=issue.status,
        name=issue.name,
        description=issue.description,
        first_seen=getattr(issue, "first_seen", None),
        assignee=_to_issue_assignee(getattr(issue, "assignment", None)),
        external_issues=[_to_external_reference(reference) for reference in issue.external_issues.all()],
        cohort=_to_issue_cohort(issue),
    )


def _to_issue_assignment_notification(assignment) -> contracts.ErrorTrackingIssueAssignmentNotification:
    role_member_user_ids: list[int] = []
    if assignment.role_id:
        role_member_user_ids = list(assignment.role.members.values_list("id", flat=True))

    issue = assignment.issue
    return contracts.ErrorTrackingIssueAssignmentNotification(
        id=assignment.id,
        created_at=assignment.created_at,
        issue=contracts.ErrorTrackingIssueForAssignmentNotification(
            id=issue.id,
            team_id=issue.team_id,
            status=issue.status,
            name=issue.name,
            description=issue.description,
        ),
        assigned_user_id=assignment.user_id,
        role_id=assignment.role_id,
        role_member_user_ids=role_member_user_ids,
    )


def list_issues(team_id: int) -> list[contracts.ErrorTrackingIssuePreview]:
    issues = logic.list_issues(team_id)
    return [_to_issue_preview(issue) for issue in issues]


def get_issue(issue_id: UUID, team_id: int) -> contracts.ErrorTrackingIssue:
    issue = logic.get_issue(issue_id=issue_id, team_id=team_id)
    return _to_issue(issue)


def issue_exists(team_id: int) -> bool:
    return logic.issue_exists(team_id=team_id)


def get_issue_id_for_fingerprint(team_id: int, fingerprint: str) -> UUID | None:
    return logic.get_issue_id_for_fingerprint(team_id=team_id, fingerprint=fingerprint)


def get_issue_values(team_id: int, key: str | None, value: str | None) -> list[str]:
    return logic.get_issue_values(team_id=team_id, key=key, value=value)


def count_issues_created_since(team_id: int, since: datetime) -> int:
    return logic.count_issues_created_since(team_id=team_id, since=since)


def get_issue_counts_by_team() -> list[tuple[int, int]]:
    return logic.get_issue_counts_by_team()


def get_symbol_set_counts_by_team(*, resolved_only: bool = False) -> list[tuple[int, int]]:
    return logic.get_symbol_set_counts_by_team(resolved_only=resolved_only)


def get_issue_assignment_for_notification(
    assignment_id: UUID | str,
) -> contracts.ErrorTrackingIssueAssignmentNotification:
    assignment = logic.get_issue_assignment(assignment_id=assignment_id)
    return _to_issue_assignment_notification(assignment)


def get_org_ids_with_exceptions() -> list[str]:
    return weekly_digest.get_org_ids_with_exceptions()


def get_exception_counts(team_ids: list[int] | None = None) -> list[Any]:
    return weekly_digest.get_exception_counts(team_ids=team_ids)


def get_exception_summary_for_team(team: Any) -> dict[str, Any]:
    return weekly_digest.get_exception_summary_for_team(team)


def get_top_issues_for_team(team: Any) -> list[dict[str, Any]]:
    return weekly_digest.get_top_issues_for_team(team)


def get_new_issues_for_team(team: Any) -> list[dict[str, Any]]:
    return weekly_digest.get_new_issues_for_team(team)


def get_daily_exception_counts(team: Any) -> list[dict[str, Any]]:
    return weekly_digest.get_daily_exception_counts(team)


def get_crash_free_sessions(team: Any) -> dict[str, Any]:
    return weekly_digest.get_crash_free_sessions(team)


def auto_select_project_for_user(user: Any, org_id: int, team_exception_counts: dict[int, dict[str, Any]]) -> bool:
    return weekly_digest.auto_select_project_for_user(
        user=user,
        org_id=org_id,
        team_exception_counts=team_exception_counts,
    )


def build_ingestion_failures_url(team_id: int) -> str:
    return weekly_digest.build_ingestion_failures_url(team_id)
