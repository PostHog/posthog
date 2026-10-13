"""Facade for error tracking issue write operations.

Kept separate from ``facade/api.py`` so the assignment/cohort side-effect imports
(ee RBAC roles, cohorts models, realtime notifications, email tasks) stay off the
django.setup() path of the read-oriented main facade.
"""

from typing import Any
from uuid import UUID

from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..logic import issue_mutations as _mutations
from . import api, contracts

CohortNotFoundError = _mutations.CohortNotFoundError
AssigneeValidationError = _mutations.AssigneeValidationError
InvalidIssueStatusError = _mutations.InvalidIssueStatusError


def user_can_mutate_issues(*, team: Team, user: User) -> bool:
    """Whether ``user`` may change issues in this team — the editor check the issue API enforces."""
    return UserAccessControl(user=user, team=team).check_access_level_for_resource("error_tracking", "editor")


def update_issue(
    team_id: int, issue_id: UUID, *, fields: dict[str, Any], user: Any, was_impersonated: bool
) -> contracts.ErrorTrackingIssueUpdate:
    outcome = _mutations.update_issue(team_id, issue_id, fields=fields, user=user, was_impersonated=was_impersonated)
    return contracts.ErrorTrackingIssueUpdate(
        issue=api._to_issue(outcome.issue), changed_fields=list(outcome.changed_fields)
    )


def merge_issues(
    team_id: int, issue_id: UUID, source_ids: list[str], *, user: User, was_impersonated: bool
) -> contracts.ErrorTrackingIssueMerge:
    outcome = _mutations.merge_issues(team_id, issue_id, source_ids, user=user, was_impersonated=was_impersonated)
    return contracts.ErrorTrackingIssueMerge(result=outcome.result.value, merged_issue_count=outcome.merged_issue_count)


def split_issue(
    team_id: int, issue_id: UUID, fingerprints: list[dict], *, user: User, was_impersonated: bool
) -> list[UUID]:
    return _mutations.split_issue(team_id, issue_id, fingerprints, user=user, was_impersonated=was_impersonated)


def set_issue_cohort(team_id: int, issue_id: UUID, cohort_id: int) -> None:
    _mutations.set_issue_cohort(team_id, issue_id, cohort_id)


def assign_issue(
    team_id: int, issue_id: UUID, assignee: dict[str, Any] | None, *, user: Any, was_impersonated: bool
) -> bool:
    return _mutations.assign_issue(team_id, issue_id, assignee, user=user, was_impersonated=was_impersonated)


def bulk_update_issues(
    team_id: int,
    issue_ids: list[str],
    *,
    action: str | None,
    status: str | None,
    assignee: dict[str, Any] | None,
    user: Any,
    was_impersonated: bool,
) -> int:
    return _mutations.bulk_update_issues(
        team_id,
        issue_ids,
        action=action,
        status=status,
        assignee=assignee,
        user=user,
        was_impersonated=was_impersonated,
    )
