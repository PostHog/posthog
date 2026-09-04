"""Issue mutations triggered from buttons on alert Slack threads.

The Slack interactivity handler (products.slack_app) has already verified the request
signature and resolved the clicking Slack user to a PostHog user who is a member of the
integration's organization. Everything else is re-derived here from the issue row: the
issue id in a button value is untrusted, so the workspace must be connected to the issue's
project and the user must be allowed to edit issues there, under the same domain and
resource access rules the API applies, before anything changes.
"""

from typing import Literal
from uuid import UUID

from django.db import transaction

import structlog

from posthog.models.integration import Integration
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.error_tracking.backend.logic import issue_mutations
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)

logger = structlog.get_logger(__name__)

SlackActionOutcome = Literal["ok", "already", "not_found", "no_access"]


def _find_issue(issue_id: UUID, fingerprint: str | None, team_id: int | None) -> ErrorTrackingIssue | None:
    # Slack webhook: no team in the request; the issue row is the source of the team, and
    # _authorized_issue decides whether this workspace and user may touch it.
    if fingerprint and team_id is not None:
        # The root's View issue link follows the fingerprint, so the buttons act on the same
        # issue it opens: the survivor after a merge, the new issue after a split.
        owner = (
            ErrorTrackingIssueFingerprintV2.objects.filter(team_id=team_id, fingerprint=fingerprint)
            .select_related("issue__team")
            .first()
        )
        if owner is not None:
            return owner.issue
    return (
        ErrorTrackingIssue.objects.filter(id=issue_id).select_related("team").first()
    )  # nosemgrep: idor-lookup-without-team


def _authorized_issue(
    issue_id: UUID, fingerprint: str | None, team_id: int | None, integration: Integration, user: User
) -> ErrorTrackingIssue | SlackActionOutcome:
    issue = _find_issue(issue_id, fingerprint, team_id)
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
    # Mirrors VerifiedDomainEnforcementPermission: an org that enforces verified domains blocks
    # members outside them from every write, Slack included.
    if OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(user.email, issue.team.organization):
        logger.warning("error_tracking_slack_action_domain_blocked", issue_id=str(issue_id), user_id=user.id)
        return "no_access"
    # The API requires editor access on the error tracking resource to change an issue; so does Slack.
    if not UserAccessControl(user, team=issue.team).check_access_level_for_resource("error_tracking", "editor"):
        logger.warning("error_tracking_slack_action_not_editor", issue_id=str(issue_id), user_id=user.id)
        return "no_access"
    return issue


def resolve_issue_from_slack(
    issue_id: UUID,
    *,
    fingerprint: str | None = None,
    team_id: int | None = None,
    integration: Integration,
    user: User,
) -> SlackActionOutcome:
    authorized = _authorized_issue(issue_id, fingerprint, team_id, integration, user)
    if not isinstance(authorized, ErrorTrackingIssue):
        return authorized
    # Two quick clicks land on different workers; the row lock makes check-and-change one step
    # so only the first produces a lifecycle reply.
    with transaction.atomic():
        issue = _lock(authorized)
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


def assign_issue_to_user_from_slack(
    issue_id: UUID,
    *,
    fingerprint: str | None = None,
    team_id: int | None = None,
    integration: Integration,
    user: User,
) -> SlackActionOutcome:
    authorized = _authorized_issue(issue_id, fingerprint, team_id, integration, user)
    if not isinstance(authorized, ErrorTrackingIssue):
        return authorized
    with transaction.atomic():
        issue = _lock(authorized)
        if ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id, user_id=user.id).exists():
            return "already"
        issue_mutations.assign_issue(
            issue.team_id, issue.id, {"type": "user", "id": user.id}, user=user, was_impersonated=False
        )
    return "ok"


def _lock(issue: ErrorTrackingIssue) -> ErrorTrackingIssue:
    return ErrorTrackingIssue.objects.select_for_update().select_related("team").get(id=issue.id, team_id=issue.team_id)
