"""Write-path operations for error tracking issues.

These encapsulate the transaction boundaries, activity logging, ClickHouse sync and
assignment side effects that previously lived in the presentation layer, so the views
can stay thin (parse -> facade -> serialize).
"""

from typing import Any
from uuid import UUID

from django.db import transaction

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.cohorts.backend.models.cohort import Cohort
from products.error_tracking.backend.logic import ErrorTrackingIssueNotFoundError, get_issue
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueCohort,
    ErrorTrackingIssueMergeResult,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.notifications import dispatch_issue_assigned_realtime

from ee.models.rbac.role import Role


class CohortNotFoundError(Exception):
    pass


class AssigneeValidationError(Exception):
    pass


class InvalidIssueStatusError(Exception):
    pass


def _get_issue(team_id: int, issue_id: UUID | str, *, select_related: tuple[str, ...] = ()) -> ErrorTrackingIssue:
    qs = ErrorTrackingIssue.objects.all()
    if select_related:
        qs = qs.select_related(*select_related)
    try:
        return qs.get(team_id=team_id, id=issue_id)
    except ErrorTrackingIssue.DoesNotExist as err:
        raise ErrorTrackingIssueNotFoundError from err


def _status_from_string(status: str) -> "ErrorTrackingIssue.Status | None":
    match status:
        case "active":
            return ErrorTrackingIssue.Status.ACTIVE
        case "resolved":
            return ErrorTrackingIssue.Status.RESOLVED
        case "suppressed":
            return ErrorTrackingIssue.Status.SUPPRESSED
    return None


def update_issue(
    team_id: int, issue_id: UUID, *, fields: dict[str, Any], user: User, was_impersonated: bool
) -> ErrorTrackingIssue:
    # Fetch via the detail queryset so the returned instance is response-ready
    # (first_seen, assignment, external issues, cohorts) without a second read.
    issue = get_issue(issue_id=issue_id, team_id=team_id)
    status_before = issue.status
    name_before = issue.name
    status_after = fields.get("status")
    name_after = fields.get("name")
    status_updated = "status" in fields and status_after != status_before
    name_updated = "name" in fields and name_after != name_before

    for key in ("status", "name", "description"):
        if key in fields:
            setattr(issue, key, fields[key])
    issue.save()

    changes = []
    if status_updated:
        changes.append(
            Change(
                type="ErrorTrackingIssue", field="status", before=status_before, after=status_after, action="changed"
            )
        )
    if name_updated:
        changes.append(
            Change(type="ErrorTrackingIssue", field="name", before=name_before, after=name_after, action="changed")
        )

    if changes:
        log_activity(
            organization_id=issue.team.organization.id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=str(issue.id),
            scope="ErrorTrackingIssue",
            activity="updated",
            detail=Detail(name=issue.name, changes=changes),
        )
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team_id)

    return issue


def merge_issues(team_id: int, issue_id: UUID, source_ids: list[str]) -> ErrorTrackingIssueMergeResult:
    issue = _get_issue(team_id, issue_id)
    # Make sure we don't delete the issue being merged into (defensive of frontend bugs)
    ids = [x for x in source_ids if x != str(issue.id)]
    return issue.merge(issue_ids=ids)


def split_issue(team_id: int, issue_id: UUID, fingerprints: list[dict]) -> list[UUID]:
    issue = _get_issue(team_id, issue_id)
    new_issues = issue.split(fingerprints=fingerprints)
    return [new_issue.id for new_issue in new_issues]


def set_issue_cohort(team_id: int, issue_id: UUID, cohort_id: int) -> None:
    issue = _get_issue(team_id, issue_id)
    cohort = Cohort.objects.filter(team_id=team_id, id=cohort_id).first()
    if cohort is None:
        raise CohortNotFoundError
    # Upsert cohort_id as a cohort might have been soft deleted.
    # nosemgrep: idor-lookup-without-team (cohort scoped to team before use)
    ErrorTrackingIssueCohort.objects.update_or_create(issue=issue, defaults={"cohort_id": cohort.id})


def assign_issue(
    team_id: int, issue_id: UUID, assignee: dict[str, Any] | None, *, user: User, was_impersonated: bool
) -> None:
    issue = _get_issue(team_id, issue_id, select_related=("team__organization",))
    _assign_one(issue, assignee, issue.team.organization, user, team_id, was_impersonated)
    sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team_id)


def bulk_update_issues(
    team_id: int,
    issue_ids: list[str],
    *,
    action: str | None,
    status: str | None,
    assignee: dict[str, Any] | None,
    user: User,
    was_impersonated: bool,
) -> None:
    issues = ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids).select_related("team__organization")

    with transaction.atomic():
        if action == "set_status":
            new_status = _status_from_string(status) if status is not None else None
            if new_status is None:
                raise InvalidIssueStatusError
            for issue in issues:
                log_activity(
                    organization_id=issue.team.organization_id,
                    team_id=team_id,
                    user=user,
                    was_impersonated=was_impersonated,
                    item_id=issue.id,
                    scope="ErrorTrackingIssue",
                    activity="updated",
                    detail=Detail(
                        name=issue.name,
                        changes=[
                            Change(
                                type="ErrorTrackingIssue",
                                action="changed",
                                field="status",
                                before=issue.status,
                                after=new_status,
                            )
                        ],
                    ),
                )
            issues.update(status=new_status)
        elif action == "assign":
            for issue in issues:
                _assign_one(issue, assignee, issue.team.organization, user, team_id, was_impersonated)

    sync_issues_to_clickhouse(issue_ids=[issue.id for issue in issues], team_id=team_id)


def _assignment_repr(assignment: ErrorTrackingIssueAssignment | None) -> dict[str, Any] | None:
    if assignment is None:
        return None
    return {
        "id": assignment.user_id if assignment.user_id else str(assignment.role_id) if assignment.role_id else None,
        "type": "role" if assignment.role_id else "user",
    }


def _assign_one(
    issue: ErrorTrackingIssue,
    assignee: dict[str, Any] | None,
    organization: Any,
    user: User,
    team_id: int,
    was_impersonated: bool,
) -> None:
    assignment_before = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).first()
    serialized_assignment_before = _assignment_repr(assignment_before)

    if assignee:
        if assignee["type"] == "user":
            if not OrganizationMembership.objects.filter(user_id=assignee["id"], organization=organization).exists():
                raise AssigneeValidationError("Assignee user does not belong to this organization.")
        elif assignee["type"] == "role":
            if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
                raise AssigneeValidationError("Assignee role does not belong to this organization.")

        # nosemgrep: idor-lookup-without-team (assignee validated against org above)
        assignment_after, _ = ErrorTrackingIssueAssignment.objects.update_or_create(
            issue_id=issue.id,
            defaults={
                "team_id": issue.team_id,
                "user_id": None if assignee["type"] != "user" else assignee["id"],
                "role_id": None if assignee["type"] != "role" else assignee["id"],
            },
        )

        send_error_tracking_issue_assigned.delay(assignment_after.id, user.id)

        dispatch_issue_assigned_realtime(
            assignment=assignment_after,
            assignee=assignee,
            assigner=user,
        )

        serialized_assignment_after = _assignment_repr(assignment_after)
    else:
        if assignment_before:
            assignment_before.delete()
        serialized_assignment_after = None

    log_activity(
        organization_id=organization.id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(issue.id),
        scope="ErrorTrackingIssue",
        activity="assigned",
        detail=Detail(
            name=issue.name,
            changes=[
                Change(
                    type="ErrorTrackingIssue",
                    field="assignee",
                    before=serialized_assignment_before,
                    after=serialized_assignment_after,
                    action="changed",
                )
            ],
        ),
    )
