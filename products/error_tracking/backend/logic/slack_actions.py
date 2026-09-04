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

import structlog

from posthog.models.integration import Integration
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.user import User
from posthog.redis import get_client
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.error_tracking.backend.logic import issue_mutations
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)

logger = structlog.get_logger(__name__)

# "ok_moved": the clicked thread's issue was merged away and the action landed on the survivor,
# so the thread itself will not update.
SlackActionOutcome = Literal["ok", "ok_moved", "already", "not_found", "no_access"]

# Two quick clicks land on different workers; a short claim per (issue, action) makes the
# second one report "already" instead of producing a second lifecycle reply.
CLICK_CLAIM_SECONDS = 10


def _find_issue(
    issue_id: UUID, fingerprint: str | None, team_id: int | None, project_id: int
) -> tuple[ErrorTrackingIssue | None, bool]:
    """The issue a click targets, and whether it had to follow the fingerprint to get there.

    The thread belongs to the clicked issue, so that is the target while it exists. Only a
    merge deletes it; the fingerprint then names the survivor in the same environment.
    """
    # Slack webhook: no team in the request. The workspace's integration pins the project,
    # so an issue from any other project does not exist as far as this click is concerned.
    issue = ErrorTrackingIssue.objects.filter(id=issue_id, team__project_id=project_id).select_related("team").first()
    if issue is not None or not fingerprint or team_id is None:
        return issue, False
    owner = (
        ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=team_id, team__project_id=project_id, fingerprint=fingerprint
        )
        .select_related("issue__team")
        .first()
    )
    return (owner.issue, True) if owner is not None else (None, False)


def _authorized_issue(
    issue_id: UUID, fingerprint: str | None, team_id: int | None, integration: Integration, user: User
) -> tuple[ErrorTrackingIssue, bool] | SlackActionOutcome:
    issue, moved = _find_issue(issue_id, fingerprint, team_id, integration.team.project_id)
    if issue is None:
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
    return issue, moved


def _claim_key(issue: ErrorTrackingIssue, action: str) -> str:
    return f"error_tracking:slack_action:{issue.id}:{action}"


def _claim_click(issue: ErrorTrackingIssue, action: str) -> bool:
    try:
        return bool(get_client().set(_claim_key(issue, action), "1", nx=True, ex=CLICK_CLAIM_SECONDS))
    except Exception:
        # The claim only dedupes double clicks; without Redis the click still counts.
        logger.exception("error_tracking_slack_action_claim_failed", issue_id=str(issue.id))
        return True


def _release_click(issue: ErrorTrackingIssue, action: str) -> None:
    # A failed mutation must not block an immediate retry for the rest of the window.
    try:
        get_client().delete(_claim_key(issue, action))
    except Exception:
        logger.exception("error_tracking_slack_action_release_failed", issue_id=str(issue.id))


def resolve_issue_from_slack(
    issue_id: UUID,
    *,
    fingerprint: str | None = None,
    team_id: int | None = None,
    integration: Integration,
    user: User,
) -> SlackActionOutcome:
    authorized = _authorized_issue(issue_id, fingerprint, team_id, integration, user)
    if isinstance(authorized, str):
        return authorized
    issue, moved = authorized
    if issue.status == ErrorTrackingIssue.Status.RESOLVED or not _claim_click(issue, "resolve"):
        return "already"
    # No transaction around this: the mutation syncs ClickHouse after its own commit.
    try:
        issue_mutations.update_issue(
            issue.team_id,
            issue.id,
            fields={"status": ErrorTrackingIssue.Status.RESOLVED},
            user=user,
            was_impersonated=False,
        )
    except Exception:
        _release_click(issue, "resolve")
        raise
    return "ok_moved" if moved else "ok"


def assign_issue_to_user_from_slack(
    issue_id: UUID,
    *,
    fingerprint: str | None = None,
    team_id: int | None = None,
    integration: Integration,
    user: User,
) -> SlackActionOutcome:
    authorized = _authorized_issue(issue_id, fingerprint, team_id, integration, user)
    if isinstance(authorized, str):
        return authorized
    issue, moved = authorized
    already_assigned = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id, user_id=user.id).exists()
    if already_assigned or not _claim_click(issue, f"assign:{user.id}"):
        return "already"
    try:
        issue_mutations.assign_issue(
            issue.team_id, issue.id, {"type": "user", "id": user.id}, user=user, was_impersonated=False
        )
    except Exception:
        _release_click(issue, f"assign:{user.id}")
        raise
    return "ok_moved" if moved else "ok"
