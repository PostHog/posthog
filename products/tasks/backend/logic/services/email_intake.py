"""Start a task from an email sent to a project's task inbox address.

A project opts in by creating an inbox address, ``code-<token>@<inbound domain>``.
Mail to that address arrives through the conversations product's Mailgun webhook,
which hands the parsed message to :func:`start_task_from_email`. The sender must
authenticate (SPF or aligned DKIM, checked by the webhook) and match a member of the
project's organization. The task then runs as that member in the shape of a PostHog AI
conversation: no repository, full MCP scopes, filed in the member's personal channel.
"""

import re
import secrets
from email.utils import parseaddr
from typing import Literal
from uuid import UUID

from django.db import IntegrityError

import structlog

from posthog.dataclasses import frozen
from posthog.email import EmailMessage, is_email_available
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.utils import absolute_uri

from products.tasks.backend.facade.api import create_and_run_task, ensure_personal_channel_id
from products.tasks.backend.models import Task, TeamTasksConfig

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, is_team_limited

logger = structlog.get_logger(__name__)

INBOX_ADDRESS_PATTERN = re.compile(r"^code-([a-f0-9]{32})@")
INBOUND_DOMAIN_SETTING = "CONVERSATIONS_EMAIL_INBOUND_DOMAIN"

IntakeOutcome = Literal[
    "created", "duplicate", "unauthenticated", "unknown_sender", "quota_exceeded", "empty", "auto_reply"
]

_REPLY_PREFIX = re.compile(r"^\s*(re|fwd?|aw|wg)\s*:\s*", re.IGNORECASE)


@frozen
class InboundTaskEmail:
    message_id: str
    sender_email: str
    sender_name: str
    subject: str
    body: str
    sender_authenticated: bool
    quoted_body: str = ""
    # An out-of-office reply to the acknowledgement must not start a task.
    is_auto_reply: bool = False


@frozen
class EmailTaskIntake:
    outcome: IntakeOutcome
    task_id: UUID | None = None


@frozen
class _TaskText:
    title: str
    description: str


def extract_inbox_token(recipient: str) -> str | None:
    _, address = parseaddr(recipient)
    match = INBOX_ADDRESS_PATTERN.match(address.strip().lower())
    return match.group(1) if match else None


def _address_for_token(token: str | None) -> str | None:
    domain = get_instance_setting(INBOUND_DOMAIN_SETTING)
    if not token or not domain:
        return None
    return f"code-{token}@{domain}"


def get_inbox_address(team: Team) -> str | None:
    token = TeamTasksConfig.objects.filter(team_id=team.id).values_list("email_inbound_token", flat=True).first()
    return _address_for_token(token)


def is_inbound_email_configured() -> bool:
    return bool(get_instance_setting(INBOUND_DOMAIN_SETTING))


def ensure_inbox_address(team: Team, *, rotate: bool = False) -> str | None:
    """Return the project's inbox address, minting a token when there is none. ``rotate`` mints a new one regardless.

    Returns None without minting when the instance has no inbound domain, since no mail could ever arrive.
    """
    if not is_inbound_email_configured():
        return None
    config = get_or_create_team_extension(team, TeamTasksConfig)
    if rotate or not config.email_inbound_token:
        config.email_inbound_token = secrets.token_hex(16)
        config.save(update_fields=["email_inbound_token", "updated_at"])
    return _address_for_token(config.email_inbound_token)


def clear_inbox_address(team: Team) -> None:
    TeamTasksConfig.objects.filter(team_id=team.id).update(email_inbound_token=None)


def find_team_by_inbox_token(token: str) -> Team | None:
    config = TeamTasksConfig.objects.select_related("team").filter(email_inbound_token=token).first()
    return config.team if config else None


def start_task_from_email(team: Team, email: InboundTaskEmail) -> EmailTaskIntake:
    if email.is_auto_reply:
        return EmailTaskIntake(outcome="auto_reply")
    if not email.sender_authenticated:
        return EmailTaskIntake(outcome="unauthenticated")

    user_id = _resolve_member_user_id(team, email.sender_email)
    if user_id is None:
        return EmailTaskIntake(outcome="unknown_sender")

    text = _task_text(email)
    if text is None:
        return EmailTaskIntake(outcome="empty")

    origin_key = _origin_key(email.message_id)
    existing_id = _task_id_for_origin_key(origin_key)
    if existing_id is not None:
        return EmailTaskIntake(outcome="duplicate", task_id=existing_id)

    if is_team_limited(team.api_token, QuotaResource.AI_CREDITS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY):
        return EmailTaskIntake(outcome="quota_exceeded")

    try:
        created = create_and_run_task(
            team=team,
            title=text.title,
            description=text.description,
            origin_product=Task.OriginProduct.EMAIL,
            user_id=user_id,
            repository=None,
            create_pr=False,
            channel_id=ensure_personal_channel_id(team.id, user_id),
            origin_key=origin_key,
            title_manually_set=True,
            interaction_origin="email",
        )
    except IntegrityError:
        # A Mailgun retry raced the first delivery; the unique origin_key index gives the first insert the task.
        existing_id = _task_id_for_origin_key(origin_key)
        if existing_id is None:
            raise
        return EmailTaskIntake(outcome="duplicate", task_id=existing_id)

    _send_started_email(email, team, text.title, created.task_id)
    return EmailTaskIntake(outcome="created", task_id=created.task_id)


def _resolve_member_user_id(team: Team, sender_email: str) -> int | None:
    return (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id, user__email__iexact=sender_email, user__is_active=True
        )
        .values_list("user_id", flat=True)
        .first()
    )


def _task_text(email: InboundTaskEmail) -> _TaskText | None:
    subject = " ".join(email.subject.split())
    body = email.body.strip()
    if not subject and not body:
        return None
    title = _REPLY_PREFIX.sub("", subject) or body.splitlines()[0]
    description = body or subject
    quoted = email.quoted_body.strip()
    if quoted:
        description = f"{description}\n\nThe sender replied to this email:\n\n{quoted}"
    return _TaskText(title=title[:255], description=description)


def _origin_key(message_id: str) -> str:
    return f"email:{message_id.strip()}"[:128]


def _task_id_for_origin_key(origin_key: str) -> UUID | None:
    return Task.objects.filter(origin_key=origin_key).values_list("id", flat=True).first()


def _send_started_email(email: InboundTaskEmail, team: Team, title: str, task_id: UUID) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    message_id = email.message_id.strip()
    if not message_id.startswith("<"):
        message_id = f"<{message_id}>"
    try:
        message = EmailMessage(
            campaign_key=f"task_email_started_{task_id}",
            template_name="task_email_started",
            subject=f"Started: {title}",
            template_context={"task_title": title, "task_url": absolute_uri(f"/code/task/{task_id}")},
            headers={"In-Reply-To": message_id, "References": message_id, "Auto-Submitted": "auto-replied"},
        )
        message.add_recipient(email=email.sender_email, name=email.sender_name or email.sender_email)
        message.send()
    except Exception:
        # The task is already running; a failed acknowledgement must not fail the webhook.
        logger.exception("task_email_started_send_failed", team_id=team.id, task_id=str(task_id))
