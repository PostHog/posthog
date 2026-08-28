"""Facade for error tracking issue write operations.

Kept separate from ``facade/api.py`` so the assignment/cohort side-effect imports
(ee RBAC roles, cohorts models, realtime notifications, email tasks) stay off the
django.setup() path of the read-oriented main facade.
"""

from typing import Any
from uuid import UUID

from ..logic import issue_mutations as _mutations
from ..models import ErrorTrackingIssueMergeResult
from . import api, contracts

CohortNotFoundError = _mutations.CohortNotFoundError
AssigneeValidationError = _mutations.AssigneeValidationError
InvalidIssueStatusError = _mutations.InvalidIssueStatusError


def update_issue(
    team_id: int, issue_id: UUID, *, fields: dict[str, Any], user: Any, was_impersonated: bool
) -> contracts.ErrorTrackingIssue:
    issue = _mutations.update_issue(team_id, issue_id, fields=fields, user=user, was_impersonated=was_impersonated)
    return api._to_issue(issue)


def merge_issues(team_id: int, issue_id: UUID, source_ids: list[str]) -> ErrorTrackingIssueMergeResult:
    return _mutations.merge_issues(team_id, issue_id, source_ids)


def split_issue(team_id: int, issue_id: UUID, fingerprints: list[dict]) -> list[UUID]:
    return _mutations.split_issue(team_id, issue_id, fingerprints)


def set_issue_cohort(team_id: int, issue_id: UUID, cohort_id: int) -> None:
    _mutations.set_issue_cohort(team_id, issue_id, cohort_id)


def assign_issue(
    team_id: int, issue_id: UUID, assignee: dict[str, Any] | None, *, user: Any, was_impersonated: bool
) -> None:
    _mutations.assign_issue(team_id, issue_id, assignee, user=user, was_impersonated=was_impersonated)


def bulk_update_issues(
    team_id: int,
    issue_ids: list[str],
    *,
    action: str | None,
    status: str | None,
    assignee: dict[str, Any] | None,
    user: Any,
    was_impersonated: bool,
) -> None:
    _mutations.bulk_update_issues(
        team_id,
        issue_ids,
        action=action,
        status=status,
        assignee=assignee,
        user=user,
        was_impersonated=was_impersonated,
    )
