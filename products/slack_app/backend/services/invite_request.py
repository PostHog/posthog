import json
import time
from typing import Any, Literal

from django.conf import settings

from rest_framework.exceptions import ValidationError

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.email import is_email_available
from posthog.event_usage import report_team_member_invited
from posthog.helpers.email_utils import EmailNormalizer, reject_plus_addressed_email
from posthog.models import Organization, OrganizationDomain, OrganizationInvite, OrganizationMembership, User
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user_integration import UserIntegration
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.tasks.email import send_invite

from products.slack_app.backend.services.slack_user_info import lookup_slack_user_id_by_email

INVITE_REQUEST_CONTEXT_KIND = "invite_request"
INVITE_REQUEST_BLOCK_ID_PREFIX = "slack_app_invite_request"
INVITE_REQUEST_ACTION_APPROVE = "slack_app_invite_request_approve"
INVITE_REQUEST_ACTION_DECLINE = "slack_app_invite_request_decline"
INVITE_REQUEST_TTL_SECONDS = 24 * 60 * 60
# Each lookup is a Slack API call inside the webhook, so the admin search stops early.
_ADMIN_LOOKUPS_MAX = 5

ApproverPath = Literal["installer", "linked_admin", "looked_up_admin"]
InviteRejection = Literal["existing_member", "plus_address", "domain_not_allowed", "no_email_delivery"]

REQUEST_EXPIRED_MESSAGE = "This invite request expired. The person can mention me again to send a new one."
REQUEST_DECLINED_MESSAGE = "Okay, no invite was sent."
APPROVER_LOST_PERMISSION_MESSAGE = "You can no longer send invites for this organization, so nothing was sent."
REJECTION_MESSAGES: dict[str, str] = {
    "existing_member": "That person already belongs to the organization, so no invite was needed.",
    "plus_address": "PostHog can't invite an address with a plus sign in it, so nothing was sent.",
    "domain_not_allowed": "This organization only allows invites to its verified email domains, so nothing was sent.",
    "no_email_delivery": "This PostHog instance can't send email, so nothing was sent.",
}


@frozen
class Approver:
    user: User
    slack_user_id: str
    path: ApproverPath


def _first_name(user: User) -> str:
    return user.first_name or user.email.split("@")[0]


def can_invite(membership: OrganizationMembership, organization: Organization) -> bool:
    """Mirrors ``UserCanInvitePermission``: admins always may, members only when the organization allows."""
    if not organization.is_feature_available(AvailableFeature.ORGANIZATION_INVITE_SETTINGS):
        return True
    return membership.level >= OrganizationMembership.Level.ADMIN or bool(organization.members_can_invite)


def single_organization(candidates: list[Integration]) -> Organization | None:
    """The one organization behind the workspace's installs, or None when there are several."""
    organizations = {candidate.team.organization_id: candidate.team.organization for candidate in candidates}
    return next(iter(organizations.values())) if len(organizations) == 1 else None


def jit_signin_available(organization: Organization, email: str) -> bool:
    """Whether signing in with this email joins the organization without an invite."""
    domain = email.rsplit("@", 1)[-1]
    return (
        OrganizationDomain.objects.verified_domains()
        .filter(organization=organization, domain__iexact=domain, jit_provisioning_enabled=True)
        .exists()
    )


def jit_signin_followup(organization: Organization, email: str) -> str:
    return (
        f"sign in to PostHog at {settings.SITE_URL}/login with {email}, using Google, GitHub or your company's "
        f"SSO, and you'll join {escape_slack_mrkdwn(organization.name)} automatically. Then mention me again."
    )


def approver_followup(approver: Approver) -> str:
    return f"I've asked {escape_slack_mrkdwn(_first_name(approver.user))} to invite you. Mention me again once you've joined."


def repeat_request_followup(approver_name: str) -> str:
    return f"I've already asked {escape_slack_mrkdwn(approver_name)} to invite you today. Mention me again once you've joined."


def _linked_slack_user_id(user_id: int, slack_team_id: str) -> str | None:
    link = (
        UserIntegration.objects.filter(
            kind=UserIntegration.IntegrationKind.SLACK, user_id=user_id, config__slack_team_id=slack_team_id
        )
        .order_by("-created_at")
        .first()
    )
    return link.integration_id if link is not None and isinstance(link.integration_id, str) else None


def pick_approver(
    organization: Organization, integration: Integration, *, requester_slack_user_id: str
) -> Approver | None:
    """The first person who may invite into the organization and whom the app can reach in Slack.

    The installer comes first, then admins who linked their Slack identity, then admins the
    workspace directory knows by email.
    """
    slack_team_id = integration.integration_id
    slack = SlackIntegration(integration)

    def reachable(user: User, path: ApproverPath, slack_user_id: str | None) -> Approver | None:
        if not slack_user_id:
            slack_user_id = _linked_slack_user_id(user.id, slack_team_id) or lookup_slack_user_id_by_email(
                slack, integration, user.email
            )
        if not slack_user_id or slack_user_id == requester_slack_user_id:
            return None
        return Approver(user=user, slack_user_id=slack_user_id, path=path)

    installer = integration.created_by
    if installer is not None and installer.is_active:
        membership = OrganizationMembership.objects.filter(organization=organization, user=installer).first()
        if membership is not None and can_invite(membership, organization):
            authed_user = ((integration.config or {}).get("authed_user") or {}).get("id")
            approver = reachable(installer, "installer", authed_user if isinstance(authed_user, str) else None)
            if approver is not None:
                return approver

    admin_memberships = list(
        OrganizationMembership.objects.filter(
            organization=organization, level__gte=OrganizationMembership.Level.ADMIN, user__is_active=True
        )
        .select_related("user")
        .order_by("joined_at")
    )
    admins_by_id = {membership.user_id: membership.user for membership in admin_memberships}
    linked = (
        UserIntegration.objects.filter(
            kind=UserIntegration.IntegrationKind.SLACK,
            user_id__in=list(admins_by_id),
            config__slack_team_id=slack_team_id,
        )
        .order_by("-created_at")
        .values_list("user_id", "integration_id")
    )
    for user_id, slack_user_id in linked:
        approver = reachable(admins_by_id[user_id], "linked_admin", slack_user_id)
        if approver is not None:
            return approver

    for membership in admin_memberships[:_ADMIN_LOOKUPS_MAX]:
        approver = reachable(membership.user, "looked_up_admin", None)
        if approver is not None:
            return approver
    return None


def request_dedupe_key(organization_id: object, email: str) -> str:
    return f"slack_app:invite_request:v1:{organization_id}:{email.lower()}"


def build_context(
    *,
    integration: Integration,
    organization: Organization,
    approver: Approver,
    requester_slack_user_id: str,
    requester_email: str,
    mention_channel: str,
    mention_thread_ts: str,
) -> dict[str, Any]:
    return {
        "kind": INVITE_REQUEST_CONTEXT_KIND,
        # The interactivity handler reads this key to claim the click for this region.
        "integration_id": integration.id,
        "organization_id": str(organization.id),
        "approver_user_id": approver.user.id,
        "approver_slack_user_id": approver.slack_user_id,
        "approver_path": approver.path,
        "requester_slack_user_id": requester_slack_user_id,
        "requester_email": requester_email,
        "mention_channel": mention_channel,
        "mention_thread_ts": mention_thread_ts,
        "created_at": int(time.time()),
    }


def build_dm_blocks(
    *,
    context_token: str,
    integration: Integration,
    organization: Organization,
    approver_slack_user_id: str,
    requester_slack_user_id: str,
    requester_email: str,
    mention_channel: str,
) -> list[dict[str, Any]]:
    value = json.dumps({"integration_id": integration.id, "approver_slack_user_id": approver_slack_user_id})
    return [
        {
            "type": "section",
            "block_id": f"{INVITE_REQUEST_BLOCK_ID_PREFIX}:{context_token}",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"<@{requester_slack_user_id}> mentioned PostHog in <#{mention_channel}> but has no PostHog "
                    f"account yet. Invite {requester_email} to {escape_slack_mrkdwn(organization.name)} as a member?"
                ),
            },
        },
        {
            "type": "actions",
            "block_id": f"{INVITE_REQUEST_BLOCK_ID_PREFIX}_actions:{context_token}",
            "elements": [
                {
                    "type": "button",
                    "action_id": INVITE_REQUEST_ACTION_APPROVE,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Send invite"},
                    "value": value,
                },
                {
                    "type": "button",
                    "action_id": INVITE_REQUEST_ACTION_DECLINE,
                    "text": {"type": "plain_text", "text": "Not now"},
                    "value": value,
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Only you see this. The invite email goes to the address above, and this request expires in a day.",
                }
            ],
        },
    ]


def is_invite_request_action(action_id: object) -> bool:
    return action_id in (INVITE_REQUEST_ACTION_APPROVE, INVITE_REQUEST_ACTION_DECLINE)


def extract_hint(payload: dict[str, Any]) -> int | None:
    """The integration id a request button carries, so an expired click still routes to its region."""
    for action in payload.get("actions", []):
        if not is_invite_request_action(action.get("action_id")):
            continue
        try:
            integration_id = json.loads(action.get("value") or "").get("integration_id")
        except (json.JSONDecodeError, AttributeError):
            return None
        return integration_id if isinstance(integration_id, int) else None
    return None


def create_invite(
    organization: Organization, *, email: str, approver: User, mention_channel: str
) -> OrganizationInvite | InviteRejection:
    """Create and send a member invite, with the checks the invite API applies."""
    if not is_email_available(with_absolute_urls=True):
        return "no_email_delivery"
    email = EmailNormalizer.normalize(email)
    try:
        reject_plus_addressed_email(email)
    except ValidationError:
        return "plus_address"
    if OrganizationDomain.objects.is_email_blocked_by_domain_enforcement(email, organization):
        return "domain_not_allowed"
    if OrganizationMembership.objects.filter(organization=organization, user__email__iexact=email).exists():
        return "existing_member"

    OrganizationInvite.objects.filter(organization=organization, target_email__iexact=email).delete()
    invite = OrganizationInvite.objects.create(
        organization=organization,
        target_email=email,
        created_by=approver,
        level=OrganizationMembership.Level.MEMBER,
        message=f"Requested through PostHog for Slack in #{mention_channel}",
        emailing_attempt_made=True,
    )
    # Sent from a worker because this runs inside the Slack interactivity request.
    send_invite.apply_async(kwargs={"invite_id": str(invite.id)})
    report_team_member_invited(
        approver,
        invite_id=str(invite.id),
        name_provided=False,
        current_invite_count=organization.active_invites.count(),
        current_member_count=OrganizationMembership.objects.filter(organization=organization).count(),
        is_bulk=False,
        email_available=True,
    )
    return invite


def invite_sent_message(approver: User, email: str) -> str:
    return f"{escape_slack_mrkdwn(_first_name(approver))} sent an invite to {email}. Check your inbox, then mention me again."


def approver_confirmation(email: str) -> str:
    return f"Invite sent to {email}."
