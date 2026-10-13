"""Tells one person when PostHog files a suggestion on a workflow, in the app and by email."""

from uuid import UUID

import structlog

from posthog.email import EmailMessage, get_email_team_and_org_context, is_email_available
from posthog.helpers.email_utils import sanitize_display_name, sanitize_email_string
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization_notification_lock import effective_notification_settings, notification_locks_for_users

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    RecipientsResolver,
    TargetType,
    create_notification,
)
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.workflow_proposal import WorkflowProposal

logger = structlog.get_logger(__name__)

EMAIL_SETTING = "workflow_suggestions"


def _candidate_user_ids(hog_flow: HogFlow, filed_by_user_id: int | None) -> list[int]:
    # The opt-in has no column of its own; the workflow's activity log is where it records who turned it on.
    opted_in_by = (
        ActivityLog.objects.filter(
            team_id=hog_flow.team_id,
            scope="HogFlow",
            item_id=str(hog_flow.id),
            activity="optimization_enabled",
            user__isnull=False,
            was_impersonated=False,
        )
        .order_by("-created_at")
        .values_list("user_id", flat=True)
        .first()
    )
    # Last comes the person the scout files as: turning suggestions on for any workflow in the project made them that.
    candidates = [opted_in_by, hog_flow.created_by_id, filed_by_user_id]
    return list(dict.fromkeys(user_id for user_id in candidates if user_id is not None))


def _recipient(team: Team, hog_flow: HogFlow, filed_by_user_id: int | None) -> User | None:
    for user_id in _candidate_user_ids(hog_flow, filed_by_user_id):
        user = team.all_users_with_access().filter(id=user_id, is_active=True).first()
        if user is None or not UserAccessControl(user=user, team=team).check_access_level_for_object(
            hog_flow, "viewer"
        ):
            continue
        # The in-app notification drops anyone without resource-level access, so a person who can see only
        # this workflow would get nothing; pass over them to the next candidate.
        if RecipientsResolver().filter_by_access_control([user.id], "hog_flow", team):
            return user
    return None


def _send_email(user: User, team: Team, hog_flow: HogFlow, proposal: WorkflowProposal, path: str) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    locks = notification_locks_for_users([user.id], organization_id=team.organization_id).get(user.id, {})
    if not effective_notification_settings(user, locks=locks).get(EMAIL_SETTING, True):
        return
    workflow_name = sanitize_display_name(
        hog_flow.name or "",
        fallback="your workflow",
        context={"helper": "workflow_suggestion_email", "field": "workflow_name"},
    )
    message = EmailMessage(
        # One send per proposal and recipient: the email transport skips a campaign key it already delivered.
        campaign_key=f"workflow_suggestion_{proposal.id}",
        template_name="workflow_suggestion_filed",
        subject=f"PostHog suggested a change to {workflow_name}",
        template_context={
            "workflow_name": workflow_name,
            # Escaped and defanged here, so the template renders them with `safe`: a URL in scout text must not
            # become a link in a PostHog email.
            "suggestion_title": sanitize_email_string(proposal.title),
            "suggestion_rationale": sanitize_email_string(proposal.rationale),
            "suggestion_path": path,
            **get_email_team_and_org_context(team=team),
        },
    )
    message.add_user_recipient(user)
    message.send(send_async=True)


def notify_proposal_filed(*, team_id: int, proposal_id: UUID, filed_by_user_id: int | None) -> None:
    proposal = (
        WorkflowProposal.objects.for_team(team_id)
        .select_related("hog_flow")
        .filter(id=proposal_id, status=WorkflowProposal.Status.SUGGESTED)
        .first()
    )
    if proposal is None:
        return
    hog_flow = proposal.hog_flow
    team = Team.objects.get(id=team_id)
    recipient = _recipient(team, hog_flow, filed_by_user_id)
    if recipient is None:
        logger.info("workflow_suggestion_notification.no_recipient", team_id=team_id, proposal_id=str(proposal_id))
        return

    path = f"/project/{team_id}/workflows/{hog_flow.id}/self-driving"
    try:
        create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.WORKFLOW_SUGGESTION,
                title=f"New suggestion for {hog_flow.name or 'your workflow'}"[:100],
                body=proposal.title,
                target_type=TargetType.USER,
                target_id=str(recipient.id),
                resource_type="hog_flow",
                resource_id=str(hog_flow.id),
                source_url=path,
                idempotency_key=f"workflow_proposal:{proposal.id}",
            )
        )
    except Exception:
        logger.exception("workflow_suggestion_notification.in_app_failed", proposal_id=str(proposal_id))
    try:
        _send_email(recipient, team, hog_flow, proposal, path)
    except Exception:
        logger.exception("workflow_suggestion_notification.email_failed", proposal_id=str(proposal_id))
