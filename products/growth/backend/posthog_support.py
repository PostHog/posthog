"""Drafts of tickets to PostHog's own support team, written by a person's agent for the person to approve.

An agent stores a draft and shows it to the person in chat. When they approve it, the agent sends it.
A draft becomes at most one ticket.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict

from django.core.cache import caches
from django.utils import timezone

from dateutil.relativedelta import relativedelta
from django_redis.exceptions import ConnectionInterrupted
from redis.exceptions import RedisError

from posthog.cloud_utils import get_cached_instance_license
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

from products.growth.backend.facade.posthog_support_types import (
    MAX_SEND_ATTEMPTS,
    MAX_TICKETS_PER_TOPIC,
    DraftedVia,
    DraftRefusal,
    FilingReason,
    SendFailure,
    SupportPlan,
    SupportPlanTier,
    TicketPermission,
    TicketTopic,
)
from products.growth.backend.posthog_support_widget import (
    PostHogSupportWidgetClient,
    SentSupportTicket,
    SupportTicketNotSent,
    SupportTicketOutcomeUnknown,
    resolve_support_widget_target,
)

from ee.billing.billing_manager import BillingManager

DRAFT_TTL_SECONDS = 24 * 60 * 60
TOPIC_WINDOW_SECONDS = 72 * 60 * 60
NEW_ORGANIZATION_SUPPORT_MONTHS = 3
SUPPORT_TRIAL_TARGETS = frozenset({"boost", "scale", "enterprise"})
BILLING_TIMEOUT_SECONDS = (3.0, 5.0)
# Renders as a horizontal line. It needs the blank lines, because `---` right under text turns that
# text into a Markdown heading.
SECTION_SEPARATOR = "\n\n---\n\n"
# A horizontal rule in the person's text could pass for the separator above the ticket note and fake a note under it.
HORIZONTAL_RULE_LINE = re.compile(r"\s*([-*_])(?:\s*\1){2,}\s*")


ANY_PLAN_TOPICS = frozenset({TicketTopic.BILLING, TicketTopic.PRIVACY_OR_SECURITY_DELETION})
ORG_ADMIN_TOPICS = frozenset({TicketTopic.PRIVACY_OR_SECURITY_DELETION, TicketTopic.OTHER_DELETION})


def _is_new_organization(organization: Organization) -> bool:
    return organization.created_at > timezone.now() - relativedelta(months=NEW_ORGANIZATION_SUPPORT_MONTHS)


def _billing_plan(organization: Organization, user: User) -> SupportPlan:
    instance_license = get_cached_instance_license()
    if instance_license is None:
        # Without a license there is no billing account, and the web app shows such an instance as free.
        return SupportPlan(tier=SupportPlanTier.FREE, support_included=False)
    try:
        billing = BillingManager(instance_license, user).get_billing_read_only(
            organization, timeout=BILLING_TIMEOUT_SECONDS
        )
    except Exception as e:
        capture_exception(e)
        return SupportPlan(tier=SupportPlanTier.UNKNOWN, support_included=None)
    trial = billing.get("trial") or {}
    if billing.get("subscription_level") in ("paid", "custom"):
        return SupportPlan(tier=SupportPlanTier.PAID, support_included=True)
    if trial.get("status") == "active":
        return SupportPlan(tier=SupportPlanTier.TRIAL, support_included=trial.get("target") in SUPPORT_TRIAL_TARGETS)
    return SupportPlan(tier=SupportPlanTier.FREE, support_included=False)


def get_support_plan(organization: Organization, user: User) -> SupportPlan:
    plan = _billing_plan(organization, user)
    if _is_new_organization(organization):
        return SupportPlan(tier=plan.tier, support_included=True)
    return plan


def _check_plan(organization: Organization, user: User) -> TicketPermission:
    """Keep this rule the same as canCreateTicket in sidepanelTicketsLogic.ts, which the web app's
    support form applies in the browser."""
    if _is_new_organization(organization):
        return TicketPermission.ALLOWED
    support_included = _billing_plan(organization, user).support_included
    if support_included is None:
        return TicketPermission.PLAN_UNKNOWN
    return TicketPermission.ALLOWED if support_included else TicketPermission.PLAN_EXCLUDES_SUPPORT


def check_ticket_permission(
    organization: Organization, user: User, topic: TicketTopic, membership_level: OrganizationMembership.Level | None
) -> TicketPermission:
    """Whether an agent can file a ticket on this topic for this organization.

    The agent picks the topic, so this limits what a well-behaved agent files. It does not stop one that
    mislabels a ticket.
    """
    permission = TicketPermission.ALLOWED if topic in ANY_PLAN_TOPICS else _check_plan(organization, user)
    if permission == TicketPermission.PLAN_EXCLUDES_SUPPORT:
        return permission
    if topic in ORG_ADMIN_TOPICS and (
        membership_level is None or membership_level < OrganizationMembership.Level.ADMIN
    ):
        return TicketPermission.NEEDS_ORG_ADMIN
    if topic == TicketTopic.OTHER:
        return TicketPermission.TOPIC_EXCLUDED
    return permission


@frozen
class SupportTicketDraft:
    id: str
    message: str
    topic: TicketTopic
    filing_reason: FilingReason
    expires_at: int
    drafted_via: DraftedVia = DraftedVia.API
    mcp_session_id: str | None = None
    mcp_conversation_id: str | None = None

    def ticket_context(self, team: Team, membership_level: OrganizationMembership.Level | None) -> str:
        # The person cannot see or edit this note, so it holds only text the server writes. The MCP ids
        # come from request headers, so the API keeps a value only when it has the form of an id.
        lines = [
            # The server cannot see the person's yes in chat, so this does not claim one.
            f"{DraftedVia(self.drafted_via).label}, then sent by the agent. PostHog did not verify the person's approval.",
            f"Topic: {TicketTopic(self.topic).label}.",
            f"Why it was drafted: {FilingReason(self.filing_reason).label}.",
            f"Organization role: {OrganizationMembership.Level(membership_level).label if membership_level else 'none'}.",
            f"Organization id: {team.organization_id}",
            f"Project id: {team.id}",
            f"Draft id: {self.id}",
        ]
        # Support finds the agent's tool calls by these ids, under $mcp_session_id and $mcp_conversation_id.
        if self.mcp_session_id:
            lines.append(f"MCP session id: {self.mcp_session_id}")
        if self.mcp_conversation_id:
            lines.append(f"MCP conversation id: {self.mcp_conversation_id}")
        return "\n".join(lines)

    def outgoing_message(self, team: Team, membership_level: OrganizationMembership.Level | None) -> str:
        # The same layout as appendTicketContext in supportLogic.ts, so support reads one note layout on every ticket.
        return f"{self.message}\n\n-----\n{self.ticket_context(team, membership_level)}"


def compose_ticket_message(
    *,
    title: str,
    request: str,
    details: str | None = None,
    already_checked: str | None = None,
    error: str | None = None,
) -> str:
    """Lay the ticket out in the shape the writing-posthog-support-tickets skill teaches, so every
    agent-drafted ticket reads the same way to support."""
    sections = [
        ("Request", request),
        ("Details", details),
        ("Already checked", already_checked),
        ("Error", error),
    ]
    # Ticket lists preview a ticket by its first line, so the title goes first, on a line of its own
    parts = [" ".join(title.split())]
    for label, body in sections:
        body = "\n".join(line for line in (body or "").splitlines() if not HORIZONTAL_RULE_LINE.fullmatch(line)).strip()
        if not body:
            continue
        if label == "Error":
            body = _code_block(body)
        # Markdown joins two lines of prose into one paragraph, so Request needs a blank line to render its
        # label on its own line. The other sections open with a list, which starts a new block anyway.
        separator = "\n\n" if label == "Request" else "\n"
        parts.append(f"{label}:{separator}{body}")
    return SECTION_SEPARATOR.join(parts)


def _code_block(text: str) -> str:
    """Shows error text exactly as given. As Markdown, a line that starts with `#` or `*` would become a
    heading or a list item, and the indentation of stack frames would be lost."""
    if text.startswith("```") and text.endswith("```"):
        return text
    # The fence must be longer than any run of backticks in the text, or that run would close it early.
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}text\n{text}\n{fence}"


class SupportDraftStore:
    """Short-lived drafts that wait for the person to approve them in chat. A draft belongs to one person
    and one project, so a ticket always names the project it was drafted for."""

    def __init__(self, user_id: int, team_id: int) -> None:
        self._user_id = user_id
        self._owner = f"{user_id}:{team_id}"
        self._cache = caches["posthog_support_drafts"]

    def create(
        self,
        *,
        message: str,
        topic: TicketTopic,
        filing_reason: FilingReason,
        drafted_via: DraftedVia = DraftedVia.API,
        mcp_session_id: str | None = None,
        mcp_conversation_id: str | None = None,
    ) -> SupportTicketDraft:
        draft = SupportTicketDraft(
            id=str(uuid.uuid4()),
            message=message,
            topic=topic,
            filing_reason=filing_reason,
            expires_at=int(time.time()) + DRAFT_TTL_SECONDS,
            drafted_via=drafted_via,
            mcp_session_id=mcp_session_id,
            mcp_conversation_id=mcp_conversation_id,
        )
        stored = {
            **asdict(draft),
            "topic": topic.value,
            "filing_reason": filing_reason.value,
            "drafted_via": drafted_via.value,
        }
        self._cache.set(self._key(draft.id), stored, DRAFT_TTL_SECONDS)
        return draft

    def get(self, draft_id: str) -> SupportTicketDraft | None:
        stored = self._cache.get(self._key(draft_id))
        if stored is None:
            return None
        # Stored as a plain dict, so a draft written before a deploy still loads after it.
        return SupportTicketDraft(
            id=stored["id"],
            message=stored["message"],
            topic=TicketTopic(stored["topic"]),
            filing_reason=FilingReason(stored["filing_reason"]),
            expires_at=stored["expires_at"],
            drafted_via=DraftedVia(stored["drafted_via"]),
            mcp_session_id=stored.get("mcp_session_id"),
            mcp_conversation_id=stored.get("mcp_conversation_id"),
        )

    def count_send_attempt(self, draft_id: str) -> int:
        self._cache.add(self._attempts_key(draft_id), 0, DRAFT_TTL_SECONDS)
        return self._cache.incr(self._attempts_key(draft_id))

    def send_started(self, draft_id: str) -> bool:
        return self._cache.get(self._sending_key(draft_id)) is not None

    def start_send(self, draft_id: str) -> bool:
        """Mark a server-side send as running. Only one send can run. A send with an unknown result
        keeps the mark until the draft expires, because a retry could create a second ticket."""
        return bool(self._cache.add(self._sending_key(draft_id), 1, DRAFT_TTL_SECONDS))

    def cancel_send(self, draft_id: str) -> None:
        self._cache.delete(self._sending_key(draft_id))

    def record_sent(self, draft_id: str, topic: TicketTopic, ticket: SentSupportTicket) -> None:
        self._cache.set(self._sent_key(draft_id), asdict(ticket), DRAFT_TTL_SECONDS)
        sent_at = [*self._recent_sends(topic), int(time.time())]
        self._cache.set(self._topic_key(topic), sent_at, TOPIC_WINDOW_SECONDS)

    def record_ticket_number(self, draft_id: str, ticket: SentSupportTicket) -> None:
        self._cache.set(self._sent_key(draft_id), asdict(ticket), DRAFT_TTL_SECONDS)

    def topic_limit_reached(self, topic: TicketTopic) -> bool:
        return len(self._recent_sends(topic)) >= MAX_TICKETS_PER_TOPIC

    def _recent_sends(self, topic: TicketTopic) -> list[int]:
        oldest = time.time() - TOPIC_WINDOW_SECONDS
        return [sent_at for sent_at in self._cache.get(self._topic_key(topic)) or [] if sent_at > oldest]

    def sent_ticket(self, draft_id: str) -> SentSupportTicket | None:
        stored = self._cache.get(self._sent_key(draft_id))
        if stored is None:
            return None
        return SentSupportTicket(ticket_id=stored["ticket_id"], ticket_number=stored.get("ticket_number"))

    def _topic_key(self, topic: TicketTopic) -> str:
        # Not per project, so switching projects does not reset the limit
        return f"posthog_support_topic_sends:{self._user_id}:{topic.value}"

    def _attempts_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_attempts:{self._owner}:{draft_id}"

    def _sending_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_sending:{self._owner}:{draft_id}"

    def _sent_key(self, draft_id: str) -> str:
        return f"posthog_support_draft_sent:{self._owner}:{draft_id}"

    def _key(self, draft_id: str) -> str:
        return f"posthog_support_draft:{self._owner}:{draft_id}"


@frozen
class DraftOutcome:
    permission: TicketPermission
    membership_level: OrganizationMembership.Level | None
    draft: SupportTicketDraft | None = None
    refusal: DraftRefusal | None = None


@frozen
class SendOutcome:
    draft: SupportTicketDraft | None = None
    ticket: SentSupportTicket | None = None
    failure: SendFailure | None = None
    replayed: bool = False


def _membership_level(team: Team, user: User) -> OrganizationMembership.Level | None:
    membership = OrganizationMembership.objects.filter(organization_id=team.organization_id, user=user).first()
    return membership.effective_level if membership else None


def create_draft(
    user: User,
    team: Team,
    *,
    message: str,
    topic: TicketTopic,
    filing_reason: FilingReason,
    drafted_via: DraftedVia,
    mcp_session_id: str | None,
    mcp_conversation_id: str | None,
) -> DraftOutcome:
    store = SupportDraftStore(user.pk, team.pk)
    membership_level = _membership_level(team, user)
    permission = check_ticket_permission(team.organization, user, topic, membership_level)
    if permission in (
        TicketPermission.TOPIC_EXCLUDED,
        TicketPermission.PLAN_EXCLUDES_SUPPORT,
        TicketPermission.NEEDS_ORG_ADMIN,
    ):
        return DraftOutcome(
            permission=permission, membership_level=membership_level, refusal=DraftRefusal(permission.value)
        )
    if store.topic_limit_reached(topic):
        return DraftOutcome(permission=permission, membership_level=membership_level, refusal=DraftRefusal.TOPIC_LIMIT)
    draft = store.create(
        message=message,
        topic=topic,
        filing_reason=filing_reason,
        drafted_via=drafted_via,
        mcp_session_id=mcp_session_id,
        mcp_conversation_id=mcp_conversation_id,
    )
    return DraftOutcome(permission=permission, membership_level=membership_level, draft=draft)


def send_draft(user: User, team: Team, draft_id: str) -> SendOutcome:
    store = SupportDraftStore(user.pk, team.pk)
    if (sent := store.sent_ticket(draft_id)) is not None:
        return SendOutcome(ticket=sent, replayed=True)
    draft = store.get(draft_id)
    if draft is None:
        return SendOutcome(failure=SendFailure.NOT_FOUND)

    def failed(failure: SendFailure) -> SendOutcome:
        return SendOutcome(draft=draft, failure=failure)

    if store.send_started(draft_id):
        return failed(SendFailure.ALREADY_SENDING)
    if store.count_send_attempt(draft_id) > MAX_SEND_ATTEMPTS:
        return failed(SendFailure.TOO_MANY_ATTEMPTS)
    if store.topic_limit_reached(draft.topic):
        return failed(SendFailure.TOPIC_LIMIT)
    membership_level = _membership_level(team, user)
    permission = check_ticket_permission(team.organization, user, draft.topic, membership_level)
    if permission != TicketPermission.ALLOWED:
        return failed(SendFailure(permission.value))

    if not store.start_send(draft_id):
        return failed(SendFailure.ALREADY_SENDING)
    try:
        client = PostHogSupportWidgetClient(resolve_support_widget_target())
        ticket = client.send_ticket(
            user, draft.outgoing_message(team, membership_level), via_mcp=draft.drafted_via == DraftedVia.MCP
        )
    except SupportTicketNotSent:
        store.cancel_send(draft_id)
        return failed(SendFailure.NOT_SENT)
    except SupportTicketOutcomeUnknown:
        return failed(SendFailure.OUTCOME_UNKNOWN)

    # Recorded before the number lookup, so a request that dies during the lookup still leaves the ticket on record.
    try:
        store.record_sent(draft_id, draft.topic, ticket)
    except (ConnectionInterrupted, RedisError) as e:
        # The ticket exists and the send mark stays, so a retry cannot send it twice.
        capture_exception(e)
    ticket_number = client.ticket_number(ticket.ticket_id)
    if ticket_number is not None:
        ticket = SentSupportTicket(ticket_id=ticket.ticket_id, ticket_number=ticket_number)
        try:
            store.record_ticket_number(draft_id, ticket)
        except (ConnectionInterrupted, RedisError) as e:
            # The ticket exists and is on record, so a replay only loses the number.
            capture_exception(e)
    return SendOutcome(draft=draft, ticket=ticket)
