"""Facade for error tracking issue write operations.

Kept separate from ``facade/api.py`` so the assignment/cohort side-effect imports
(ee RBAC roles, cohorts models, realtime notifications, email tasks) stay off the
django.setup() path of the read-oriented main facade.
"""

from typing import Any
from uuid import UUID

from posthog.models.integration import Integration
from posthog.models.user import User

from ..logic import (
    issue_mutations as _mutations,
    slack_actions as _slack_actions,
)
from ..models import ErrorTrackingIssueMergeResult
from . import api, contracts

CohortNotFoundError = _mutations.CohortNotFoundError
AssigneeValidationError = _mutations.AssigneeValidationError
InvalidIssueStatusError = _mutations.InvalidIssueStatusError


SlackActionOutcome = _slack_actions.SlackActionOutcome


def update_issue(
    team_id: int, issue_id: UUID, *, fields: dict[str, Any], user: Any, was_impersonated: bool
) -> contracts.ErrorTrackingIssue:
    issue = _mutations.update_issue(team_id, issue_id, fields=fields, user=user, was_impersonated=was_impersonated)
    return api._to_issue(issue)


def merge_issues(
    team_id: int, issue_id: UUID, source_ids: list[str], *, user: User, was_impersonated: bool
) -> ErrorTrackingIssueMergeResult:
    return _mutations.merge_issues(team_id, issue_id, source_ids, user=user, was_impersonated=was_impersonated)


def split_issue(
    team_id: int, issue_id: UUID, fingerprints: list[dict], *, user: User, was_impersonated: bool
) -> list[UUID]:
    return _mutations.split_issue(team_id, issue_id, fingerprints, user=user, was_impersonated=was_impersonated)


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


def resolve_issue_from_slack(issue_id: UUID, *, integration: Integration, user: User) -> SlackActionOutcome:
    """Resolve an issue from a button on its alert thread. See logic.slack_actions for the checks."""
    return _slack_actions.resolve_issue_from_slack(issue_id, integration=integration, user=user)


def assign_issue_to_user_from_slack(issue_id: UUID, *, integration: Integration, user: User) -> SlackActionOutcome:
    """Assign an issue to the clicking user from a button on its alert thread."""
    return _slack_actions.assign_issue_to_user_from_slack(issue_id, integration=integration, user=user)
