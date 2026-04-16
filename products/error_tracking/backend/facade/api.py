"""Facade API for error tracking.

This is the ONLY module other apps are allowed to import.
"""

from uuid import UUID

from .. import logic
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
