from collections.abc import Iterable, Iterator, Mapping
from functools import cache

from django.utils import timezone

import structlog

from posthog.integrations import CrossTeamFilter, IntegrationManager, IntegrationPatch, IntegrationRecord, UpdatedRows
from posthog.models.integration.email import SES_SENDING_FAILED, SES_SENDING_STATUS_KEY
from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.tasks.email import send_email_sender_domain_sending_stopped

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)

logger = structlog.get_logger(__name__)

SES_SENDER_HEALTH_FLAG = "workflows-ses-sender-health"

_PAGE_SIZE = 500

_MARK = IntegrationPatch(config_patch={SES_SENDING_STATUS_KEY: SES_SENDING_FAILED})
_UNMARK = IntegrationPatch(config_remove=(SES_SENDING_STATUS_KEY,))


def record_ses_sending_status(failed_domains: Iterable[str]) -> None:
    """Mark the verified senders of the domains SES stopped sending from, and unmark every other marked sender.

    Only projects in the rollout get marks, so switching the flag off clears them on the next check.
    """
    failed = tuple(sorted({domain.lower() for domain in failed_domains}))
    rolled_out = cache(_rolled_out)
    for sender in _one_sender_per_project_domain(where_in={"domain": failed}):
        if rolled_out(sender.team_id) and _patch_domain(sender, _MARK).changed_ids:
            _notify_sending_stopped(sender.team_id, sender.config["domain"])
    for sender in _one_sender_per_project_domain(where={SES_SENDING_STATUS_KEY: SES_SENDING_FAILED}):
        if sender.config["domain"] not in failed or not rolled_out(sender.team_id):
            _patch_domain(sender, _UNMARK)


def _rolled_out(team_id: int) -> bool:
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    organization_id = str(team.organization_id)
    return feature_enabled_or_false(
        SES_SENDER_HEALTH_FLAG,
        str(team.uuid),
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={"organization": {"id": organization_id}, "project": {"id": str(team_id)}},
        send_feature_flag_events=False,
    )


def _patch_domain(sender: IntegrationRecord, patch: IntegrationPatch) -> UpdatedRows:
    return IntegrationManager.email.credentials.update_where(
        sender.team_id,
        where={"domain": sender.config["domain"], "provider": "ses", "verified": True},
        patch=patch,
    )


def _one_sender_per_project_domain(
    *, where: Mapping[str, str] | None = None, where_in: Mapping[str, tuple[str, ...]] | None = None
) -> Iterator[IntegrationRecord]:
    seen: set[tuple[int, str]] = set()
    after_id: int | None = None
    while page := IntegrationManager.email.any.list_across_teams(
        CrossTeamFilter(
            where={"provider": "ses", "verified": True, **(where or {})},
            where_in=where_in or {},
            limit=_PAGE_SIZE,
            after_id=after_id,
        )
    ):
        for sender in page:
            key = (sender.team_id, sender.config["domain"])
            if key not in seen:
                seen.add(key)
                yield sender
        after_id = page[-1].id


# The mark is already stored, so a failed notice must not stop the notices of other domains.
def _notify_sending_stopped(team_id: int, domain: str) -> None:
    try:
        send_email_sender_domain_sending_stopped.delay(
            team_id=team_id, domain=domain, stopped_at=timezone.now().isoformat()
        )
    except Exception:
        logger.exception("ses_sending_stopped_email_dispatch_failed", team_id=team_id)
    try:
        create_notification(
            NotificationData(
                team_id=team_id,
                notification_type=NotificationType.EMAIL_REPUTATION,
                priority=Priority.NORMAL,
                title=f"Emails from {domain} are failing",
                body=(
                    f"The DNS records of {domain} can no longer be verified, so every email sent from it fails. "
                    "Fix the records with your DNS provider, then verify the domain again in Channels."
                ),
                target_type=TargetType.TEAM,
                target_id=str(team_id),
                source_url="/workflows/channels",
            )
        )
    except Exception:
        logger.exception("ses_sending_stopped_notification_failed", team_id=team_id)
