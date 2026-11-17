from collections.abc import Iterable, Iterator, Mapping
from functools import cache

from django.db import transaction
from django.utils import timezone
from django.utils.text import Truncator

import structlog
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.integrations import CrossTeamFilter, IntegrationManager, IntegrationPatch, IntegrationRecord, UpdatedRows
from posthog.models.integration.email import SES_SENDING_FAILED, SES_SENDING_STATUS_KEY
from posthog.models.team import Team
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

_NOTICE_PENDING_KEY = "ses_sending_notice_pending"

_MARK = IntegrationPatch(config_patch={SES_SENDING_STATUS_KEY: SES_SENDING_FAILED})
_UNMARK = IntegrationPatch(config_remove=(SES_SENDING_STATUS_KEY, _NOTICE_PENDING_KEY))
_NOTICE_SENT = IntegrationPatch(config_remove=(_NOTICE_PENDING_KEY,))


def record_ses_sending_status(failed_domains: Iterable[str]) -> None:
    """Mark the verified senders of the domains SES stopped sending from, and unmark every other marked sender.

    Only projects in the rollout get marks, so switching the flag off clears them on the next check.
    A check that cannot evaluate the flag for a project keeps that project's marks as they are.
    """
    failed = tuple(sorted({domain.lower() for domain in failed_domains}))
    rolled_out = cache(_rolled_out)
    for sender in _one_sender_per_project_domain(where_in={"domain": failed}):
        if rolled_out(sender.team_id) is not True:
            continue
        stopped_at = _mark_stop_awaiting_notice(sender)
        if stopped_at and _queue_sending_stopped_email(sender.team_id, sender.config["domain"], stopped_at):
            _settle_notice_with_notification(sender, stopped_at)
    for sender in _one_sender_per_project_domain(where={SES_SENDING_STATUS_KEY: SES_SENDING_FAILED}):
        if sender.config["domain"] not in failed or rolled_out(sender.team_id) is False:
            _patch_domain(sender, _UNMARK)


def _rolled_out(team_id: int) -> bool | None:
    team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    organization_id = str(team.organization_id)
    return posthoganalytics.feature_enabled(
        SES_SENDER_HEALTH_FLAG,
        str(team.uuid),
        groups={"organization": organization_id, "project": str(team_id)},
        group_properties={"organization": {"id": organization_id}, "project": {"id": str(team_id)}},
        send_feature_flag_events=False,
    )


def _mark_stop_awaiting_notice(sender: IntegrationRecord) -> str | None:
    with transaction.atomic():
        marked = _patch_domain(sender, _MARK)
        if marked.changed_ids:
            stopped_at = timezone.now().isoformat()
            _patch_domain(sender, IntegrationPatch(config_patch={_NOTICE_PENDING_KEY: stopped_at}))
            return stopped_at
    return next((row.config[_NOTICE_PENDING_KEY] for row in marked.records if _NOTICE_PENDING_KEY in row.config), None)


def _patch_domain(
    sender: IntegrationRecord, patch: IntegrationPatch, *, pending_since: str | None = None
) -> UpdatedRows:
    where = {"domain": sender.config["domain"], "provider": "ses", "verified": True}
    if pending_since is not None:
        where[_NOTICE_PENDING_KEY] = pending_since
    return IntegrationManager.email.credentials.update_where(sender.team_id, where=where, patch=patch)


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


def _queue_sending_stopped_email(team_id: int, domain: str, stopped_at: str) -> bool:
    try:
        send_email_sender_domain_sending_stopped.delay(team_id=team_id, domain=domain, stopped_at=stopped_at)
    except Exception as error:
        logger.exception("ses_sending_stopped_email_dispatch_failed", team_id=team_id, domain=domain)
        capture_exception(error, {"team_id": team_id, "domain": domain})
        return False
    return True


def _settle_notice_with_notification(sender: IntegrationRecord, stopped_at: str) -> None:
    team_id, domain = sender.team_id, sender.config["domain"]
    try:
        with transaction.atomic():
            if _patch_domain(sender, _NOTICE_SENT, pending_since=stopped_at).changed_ids:
                _create_sending_stopped_notification(team_id, domain)
    except Exception as error:
        logger.exception("ses_sending_stopped_notification_failed", team_id=team_id, domain=domain)
        capture_exception(error, {"team_id": team_id, "domain": domain})


def _create_sending_stopped_notification(team_id: int, domain: str) -> None:
    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.EMAIL_REPUTATION,
            priority=Priority.NORMAL,
            title=Truncator(f"Emails from {domain} are failing").chars(255),
            body=(
                f"The DNS records of {domain} can no longer be verified, so every email sent from it fails. "
                "Fix the records with your DNS provider, then verify the domain again in Channels."
            ),
            target_type=TargetType.TEAM,
            target_id=str(team_id),
            source_url=f"/project/{team_id}/workflows/channels",
        )
    )
