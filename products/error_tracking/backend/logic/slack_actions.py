"""Issue mutations triggered from buttons on alert Slack threads.

The Slack interactivity handler (products.slack_app) has already verified the request
signature and resolved the clicking Slack user to a PostHog user who is a member of the
integration's organization. Everything else is re-derived here from the issue row: the
issue id in a button value is untrusted, so the workspace must be connected to the issue's
project and the user must have access to that project before anything changes.
"""

from typing import Literal
from uuid import UUID

import structlog

from posthog.models.integration import Integration
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.error_tracking.backend.logic import issue_mutations
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment

logger = structlog.get_logger(__name__)

SlackActionOutcome = Literal["ok", "already", "not_found", "no_access"]


def _authorized_issue(issue_id: UUID, integration: Integration, user: User) -> ErrorTrackingIssue | SlackActionOutcome:
    # Slack webhook: no team in the request; the issue row is the source of the team, and
    # the checks below decide whether this workspace and user may touch it.
    issue = (
        ErrorTrackingIssue.objects.filter(id=issue_id).select_related("team").first()
    )  # nosemgrep: idor-lookup-without-team
    if issue is None:
        return "not_found"
    if integration.team.project_id != issue.team.project_id:
        logger.warning(
            "error_tracking_slack_action_workspace_mismatch", issue_id=str(issue_id), integration_id=integration.id
        )
        return "not_found"
    # Mirrors TeamMemberAccessPermission: an org member without membership in a private
    # project must be denied.
    if UserPermissions(user).team(issue.team).effective_membership_level is None:
        logger.warning("error_tracking_slack_action_no_access", issue_id=str(issue_id), user_id=user.id)
        return "no_access"
    return issue


def resolve_issue_from_slack(issue_id: UUID, *, integration: Integration, user: User) -> SlackActionOutcome:
    authorized = _authorized_issue(issue_id, integration, user)
    if not isinstance(authorized, ErrorTrackingIssue):
        return authorized
    issue = authorized
    if issue.status == ErrorTrackingIssue.Status.RESOLVED:
        return "already"
    issue_mutations.update_issue(
        issue.team_id,
        issue.id,
        fields={"status": ErrorTrackingIssue.Status.RESOLVED},
        user=user,
        was_impersonated=False,
    )
    return "ok"


def assign_issue_to_user_from_slack(issue_id: UUID, *, integration: Integration, user: User) -> SlackActionOutcome:
    authorized = _authorized_issue(issue_id, integration, user)
    if not isinstance(authorized, ErrorTrackingIssue):
        return authorized
    issue = authorized
    if ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id, user_id=user.id).exists():
        return "already"
    issue_mutations.assign_issue(
        issue.team_id, issue.id, {"type": "user", "id": user.id}, user=user, was_impersonated=False
    )
    return "ok"
