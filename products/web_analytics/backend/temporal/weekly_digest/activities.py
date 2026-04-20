from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity

from posthog.email import EmailMessage, is_email_available
from posthog.models import Team
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.tasks.email import NotificationSetting, should_send_notification
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.user_permissions import UserPermissions

from products.web_analytics.backend.temporal.weekly_digest.types import (
    BuildAndSendDigestForOrgInput,
    SendTestDigestInput,
)
from products.web_analytics.backend.weekly_digest import auto_select_project_for_user, build_team_digest

logger = structlog.get_logger(__name__)


def _get_orgs_for_wa_digest() -> list[str]:
    """Synchronous implementation: discover orgs with the digest flag enabled."""
    close_old_connections()
    org_ids = [str(oid) for oid in Organization.objects.values_list("id", flat=True)]

    targeted_org_ids = [
        org_id
        for org_id in org_ids
        if posthoganalytics.feature_enabled(
            "web-analytics-weekly-digest",
            distinct_id=f"digest-worker-{org_id}",
            groups={"organization": org_id},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    ]

    logger.info(
        "Discovered orgs for WA digest",
        targeted=len(targeted_org_ids),
        total=len(org_ids),
    )
    return targeted_org_ids


@activity.defn(name="wa-digest-get-orgs")
async def get_orgs_for_wa_digest() -> list[str]:
    """Discover orgs where the web-analytics-weekly-digest flag is enabled."""
    return await database_sync_to_async(_get_orgs_for_wa_digest, thread_sensitive=False)()


def _send_digest_for_user(
    *,
    user: User,
    org: Organization,
    membership: OrganizationMembership,
    team_digest_data: dict[int, dict],
    date_suffix: str,
    dry_run: bool = False,
    test: bool = False,
) -> bool:
    """`test=True` bypasses notification opt-ins and forces a unique campaign_key so
    dedupe never blocks delivery. The team-access check is always enforced.
    """
    if not test and not should_send_notification(user, NotificationSetting.WEB_ANALYTICS_WEEKLY_DIGEST.value):
        return False

    user_perms = UserPermissions(user)
    accessible_team_data: dict[int, dict] = {}
    for team_id, data in team_digest_data.items():
        team = data["team"]
        if user_perms.team(team).effective_membership_level_for_parent_membership(org, membership) is not None:
            accessible_team_data[team_id] = data

    if not accessible_team_data:
        return False

    if auto_select_project_for_user(user, accessible_team_data):
        user.refresh_from_db(fields=["partial_notification_settings"])

    user_team_sections = []
    disabled_team_names = []
    for team_id, data in accessible_team_data.items():
        if test or should_send_notification(user, NotificationSetting.WEB_ANALYTICS_WEEKLY_DIGEST.value, team_id):
            user_team_sections.append(data)
        else:
            disabled_team_names.append(data["team"].name)

    if not user_team_sections:
        return False

    user_team_sections.sort(key=lambda d: d.get("visitors", {}).get("current", 0), reverse=True)

    campaign_key = f"web_analytics_weekly_digest_{org.id}_{user.uuid}_{date_suffix}"
    if test:
        campaign_key = f"{campaign_key}_test_{int(timezone.now().timestamp())}"

    if dry_run:
        return True

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"Web analytics weekly digest for {org.name}",
        template_name="web_analytics_weekly_digest",
        template_context={
            "organization": org,
            "project_sections": user_team_sections,
            "disabled_project_names": disabled_team_names,
            "settings_url": f"{settings.SITE_URL}/settings/user-notifications?highlight=wa-weekly-digest",
        },
    )
    message.add_user_recipient(user)
    message.send()
    return True


def _build_and_send_for_org(org_id: str, dry_run: bool = False) -> dict:
    """Synchronous implementation: compute digests per team, send email per member.

    Runs on a thread via database_sync_to_async.
    """
    close_old_connections()

    if not is_email_available(with_absolute_urls=True):
        return {"sent_count": 0, "team_count": 0, "skipped": "email_unavailable"}

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        logger.warning("Organization not found for WA weekly digest", org_id=org_id)
        return {"sent_count": 0, "team_count": 0, "skipped": "org_not_found"}

    memberships = list(OrganizationMembership.objects.prefetch_related("user").filter(organization_id=org.id))
    targeted_memberships = [
        m
        for m in memberships
        if posthoganalytics.feature_enabled(
            "web-analytics-weekly-digest",
            distinct_id=str(m.user.distinct_id),
            groups={"organization": str(org.id)},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    ]
    if not targeted_memberships:
        return {"sent_count": 0, "team_count": 0, "skipped": "no_targeted_memberships"}

    all_org_teams = list(Team.objects.filter(organization_id=org.id))
    if not all_org_teams:
        return {"sent_count": 0, "team_count": 0, "skipped": "no_teams"}

    team_digest_data: dict[int, dict] = {team.id: build_team_digest(team) for team in all_org_teams}
    date_suffix = timezone.now().strftime("%Y-%W")
    sent_count = 0

    for membership in targeted_memberships:
        if _send_digest_for_user(
            user=membership.user,
            org=org,
            membership=membership,
            team_digest_data=team_digest_data,
            date_suffix=date_suffix,
            dry_run=dry_run,
        ):
            sent_count += 1

    logger.info(
        "Sent WA weekly digest for org",
        org_id=org_id,
        sent_count=sent_count,
        team_count=len(team_digest_data),
    )
    return {"sent_count": sent_count, "team_count": len(team_digest_data)}


@activity.defn(name="wa-digest-build-and-send-for-org")
async def build_and_send_wa_digest_for_org(input: BuildAndSendDigestForOrgInput) -> dict:
    """Process a single org: compute digests per team, send email per member."""
    async with Heartbeater():
        return await database_sync_to_async(_build_and_send_for_org, thread_sensitive=False)(
            input.org_id, input.dry_run
        )


def _send_test_digest(email: str, team_id: int | None = None) -> None:
    """The recipient is the matched user's stored email, never the input string,
    so this cannot be used to redirect a team's data to an arbitrary inbox.
    """
    close_old_connections()

    if not is_email_available(with_absolute_urls=True):
        raise RuntimeError("Email is not available — check EMAIL_HOST in instance settings")

    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if not user:
        raise ValueError(f"No active user found with email {email}")

    date_suffix = timezone.now().strftime("%Y-%W")

    if team_id is not None:
        team = Team.objects.select_related("organization").filter(id=team_id).first()
        if not team:
            raise ValueError(f"Team {team_id} not found")

        membership = OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            user_id=user.id,
        ).first()
        if not membership:
            raise PermissionError(f"User {email} is not a member of the organization that owns team {team_id}")

        sent = _send_digest_for_user(
            user=user,
            org=team.organization,
            membership=membership,
            team_digest_data={team.id: build_team_digest(team)},
            date_suffix=date_suffix,
            test=True,
        )
        if not sent:
            raise PermissionError(f"User {email} does not have access to team {team_id}")

        logger.info(
            "Sent test WA digest",
            mode="single_team",
            team_id=team_id,
            team_name=team.name,
            email=email,
        )
        return

    memberships = list(OrganizationMembership.objects.select_related("organization").filter(user_id=user.id))
    if not memberships:
        raise ValueError(f"User {email} has no organization memberships")

    sent_count = 0
    for membership in memberships:
        org = membership.organization
        org_teams = list(Team.objects.filter(organization_id=org.id))
        if not org_teams:
            continue
        team_digest_data = {t.id: build_team_digest(t) for t in org_teams}
        if _send_digest_for_user(
            user=user,
            org=org,
            membership=membership,
            team_digest_data=team_digest_data,
            date_suffix=date_suffix,
            test=True,
        ):
            sent_count += 1

    if sent_count == 0:
        raise PermissionError(f"User {email} has no accessible teams in any of their organizations")

    logger.info(
        "Sent test WA digest",
        mode="full_user_digest",
        email=email,
        emails_sent=sent_count,
    )


@activity.defn(name="wa-digest-send-test")
async def send_test_wa_digest(input: SendTestDigestInput) -> None:
    await database_sync_to_async(_send_test_digest, thread_sensitive=False)(input.email, input.team_id)
