"""Write-path operations for error tracking issues.

These encapsulate the transaction boundaries, activity logging, ClickHouse sync and
assignment side effects that previously lived in the presentation layer, so the views
can stay thin (parse -> facade -> serialize).
"""

from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.access_control.backend.models.role import Role
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


class CohortNotFoundError(Exception):
    pass


class AssigneeValidationError(Exception):
    pass


class InvalidIssueStatusError(Exception):
    pass


_CLICKHOUSE_VISIBLE_ISSUE_STATE_FIELDS = ("status", "severity", "name", "description")


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


def _has_clickhouse_visible_state_change(issue: ErrorTrackingIssue, fields: dict[str, Any]) -> bool:
    return any(
        field in fields and fields[field] != getattr(issue, field) for field in _CLICKHOUSE_VISIBLE_ISSUE_STATE_FIELDS
    )


def _stamp_issue_state(*, team_id: int, issue_ids: list[UUID]) -> None:
    if issue_ids:
        ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids).update(state_updated_at=timezone.now())


def update_issue(
    team_id: int, issue_id: UUID, *, fields: dict[str, Any], user: User, was_impersonated: bool
) -> ErrorTrackingIssue:
    # Fetch via the detail queryset so the returned instance is response-ready
    # (first_seen, assignment, external issues, cohorts) without a second read.
    issue = get_issue(issue_id=issue_id, team_id=team_id)
    status_before = issue.status
    severity_before = issue.severity
    name_before = issue.name
    status_after = fields.get("status")
    severity_after = fields.get("severity")
    name_after = fields.get("name")
    status_updated = "status" in fields and status_after != status_before
    severity_updated = "severity" in fields and severity_after != severity_before
    name_updated = "name" in fields and name_after != name_before
    state_updated = _has_clickhouse_visible_state_change(issue, fields)

    for key in ("status", "severity", "name", "description"):
        if key in fields:
            setattr(issue, key, fields[key])

    changes = []
    if status_updated:
        changes.append(
            Change(
                type="ErrorTrackingIssue",
                field="status",
                before=status_before,
                after=status_after,
                action="changed",
            )
        )
    if severity_updated:
        changes.append(
            Change(
                type="ErrorTrackingIssue",
                field="severity",
                before=severity_before,
                after=severity_after,
                action="changed",
            )
        )
    if name_updated:
        changes.append(
            Change(type="ErrorTrackingIssue", field="name", before=name_before, after=name_after, action="changed")
        )

    with transaction.atomic():
        if state_updated:
            issue.state_updated_at = timezone.now()
        issue.save()

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

    if state_updated:
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
    with transaction.atomic():
        issue = _get_issue(team_id, issue_id, select_related=("team__organization",))
        assignment_changed = _assign_one(issue, assignee, issue.team.organization, user, team_id, was_impersonated)
        if assignment_changed:
            _stamp_issue_state(team_id=team_id, issue_ids=[issue.id])

    if assignment_changed:
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
    issues = list(
        ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=issue_ids).select_related("team__organization")
    )
    changed_issue_ids: list[UUID] = []

    with transaction.atomic():
        if action == "set_status":
            new_status = _status_from_string(status) if status is not None else None
            if new_status is None:
                raise InvalidIssueStatusError
            for issue in issues:
                if issue.status == new_status:
                    continue
                changed_issue_ids.append(issue.id)
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
            if changed_issue_ids:
                ErrorTrackingIssue.objects.filter(team_id=team_id, id__in=changed_issue_ids).update(
                    status=new_status, state_updated_at=timezone.now()
                )
        elif action == "assign":
            for issue in issues:
                if _assign_one(issue, assignee, issue.team.organization, user, team_id, was_impersonated):
                    changed_issue_ids.append(issue.id)
            _stamp_issue_state(team_id=team_id, issue_ids=changed_issue_ids)

    sync_issues_to_clickhouse(issue_ids=changed_issue_ids, team_id=team_id)


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
) -> bool:
    assignment_before = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).first()
    serialized_assignment_before = _assignment_repr(assignment_before)

    if assignee:
        if assignee["type"] == "user":
            if not OrganizationMembership.objects.filter(user_id=assignee["id"], organization=organization).exists():
                raise AssigneeValidationError("Assignee user does not belong to this organization.")
        elif assignee["type"] == "role":
            if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
                raise AssigneeValidationError("Assignee role does not belong to this organization.")

        serialized_assignment_after = {
            "id": int(assignee["id"]) if assignee["type"] == "user" else str(assignee["id"]),
            "type": assignee["type"],
        }
        if serialized_assignment_before == serialized_assignment_after:
            return False

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
    else:
        if assignment_before is None:
            return False
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
    return True
