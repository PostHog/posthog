from enum import StrEnum

from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum

MAX_SEND_ATTEMPTS = 4
MAX_TICKETS_PER_TOPIC = 3
WIDGET_MESSAGE_MAX_LENGTH = 10_000
TICKET_NOTE_MAX_LENGTH = 1_000
# Redirects to the person's own region
SUPPORT_PANEL_URL = "https://app.posthog.com/home#panel=support"


class FilingReason(LabeledStrEnum):
    # Each reason starts from what the person wants or what only PostHog can see, never from the
    # agent's own diagnosis, so an agent cannot file just because it decided the bug is ours.
    USER_ASKED_FOR_SUPPORT = "user_asked_for_support", "The person asked to contact PostHog support"
    NEEDS_POSTHOG_STAFF = "needs_posthog_staff", "Only PostHog staff can do or see what the person needs"
    UNEXPLAINED_ERROR = "unexplained_error", "A reproducible error the agent confirmed but cannot explain"
    USER_DISAGREES_WITH_AGENT = "user_disagrees_with_agent", "The person disagrees with the agent's answer"


# The person already got an answer, so support needs to see that answer to settle the disagreement.
ANSWERED_FILING_REASONS = frozenset({FilingReason.USER_ASKED_FOR_SUPPORT, FilingReason.USER_DISAGREES_WITH_AGENT})


class TicketTopic(LabeledStrEnum):
    PRIVACY = "privacy", "Privacy"
    SECURITY = "security", "Security"
    COMPLIANCE = "compliance", "Compliance"
    RETENTION = "retention", "Data retention"
    DPA = "dpa", "Data processing agreement (DPA)"
    BAA = "baa", "Business associate agreement (BAA)"
    PRIVACY_OR_SECURITY_DELETION = (
        "privacy_or_security_deletion",
        "Deleting data for a privacy or security reason",
    )
    OTHER_DELETION = "other_deletion", "Deleting data for another reason"
    BILLING = "billing", "Billing or usage"
    OTHER = "other", "Anything else"


class DraftedVia(LabeledStrEnum):
    MCP = "mcp", "Drafted by an AI agent through the PostHog MCP"
    API = "api", "Drafted through the PostHog API"


class TicketPermission(StrEnum):
    ALLOWED = "allowed"
    PLAN_EXCLUDES_SUPPORT = "plan_excludes_support"
    PLAN_UNKNOWN = "plan_unknown"
    TOPIC_EXCLUDED = "topic_excluded"


class DraftRefusal(StrEnum):
    TOPIC_EXCLUDED = "topic_excluded"
    PLAN_EXCLUDES_SUPPORT = "plan_excludes_support"
    TOPIC_LIMIT = "topic_limit"


class SendFailure(StrEnum):
    NOT_FOUND = "not_found"
    ALREADY_SENDING = "already_sending"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    TOPIC_LIMIT = "topic_limit"
    TOPIC_EXCLUDED = "topic_excluded"
    PLAN_EXCLUDES_SUPPORT = "plan_excludes_support"
    PLAN_UNKNOWN = "plan_unknown"
    NOT_SENT = "not_sent"
    OUTCOME_UNKNOWN = "outcome_unknown"


@frozen
class SupportDraft:
    id: str
    message: str
    ticket_context: str
    expires_at: int
    topic: TicketTopic
    filing_reason: FilingReason
    permission: TicketPermission


@frozen
class SentSupportTicketResult:
    ticket_id: str
    ticket_number: int | None
    newly_sent: bool
    topic: TicketTopic | None = None
    filing_reason: FilingReason | None = None
