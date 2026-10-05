from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, NotRequired, Protocol, TypedDict
from uuid import UUID

from posthog.dataclasses import frozen

from products.workflows.backend.facade.enums import (
    HogFlowBatchJobState,
    HogFlowTemplateExitCondition,
    HogFlowTemplateScope,
)

if TYPE_CHECKING:
    from posthog.models.team.team import Team
    from posthog.models.user import User


@frozen
class WorkflowSummary:
    id: str
    name: str
    status: str


@frozen
class RecentWorkflow:
    id: str
    name: str
    status: str
    updated_at: datetime | None


@frozen
class WorkflowActivitySummary:
    total_count: int
    active_count: int
    recent: tuple[RecentWorkflow, ...]


@frozen
class WorkflowTaskDailyLimits:
    """A team's daily caps on tasks created by workflows. None means the default cap applies."""

    per_workflow: int | None
    per_team: int | None


@frozen
class WorkflowBatchJob:
    """One batch run of a workflow.

    ``created_by`` carries the core ``User`` row rather than a projection of it, so the
    presentation layer keeps serializing it through core's ``UserBasicSerializer`` and the
    generated ``UserBasic`` component stays as it was.
    """

    id: UUID
    hog_flow_id: UUID
    status: HogFlowBatchJobState
    filters: dict[str, Any]
    variables: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: "User | None"


class WorkflowBatchJobNotFound(Exception):
    pass


@dataclass(frozen=True)
class HogFlowReference:
    id: str
    name: str
    status: str


@frozen
class AccountAudienceCustomPropertyFilter:
    """One custom-property predicate of a batch audience (key = definition id)."""

    definition_id: UUID
    operator: str
    value: Any = None


AccountAssignmentStatus = Literal["all", "assigned", "unassigned"]


@frozen
class AccountAudienceFilters:
    """Account selection for a batch run; empty filters mean every account with an external_id."""

    tag_names: tuple[str, ...] = ()
    assignment_status: AccountAssignmentStatus | None = None
    assigned_to_user_ids: tuple[int, ...] = ()
    all_roles_unassigned: bool = False
    custom_properties: tuple[AccountAudienceCustomPropertyFilter, ...] = ()


class AccountAudienceProvider(Protocol):
    def count_accounts(self, team: "Team", filters: AccountAudienceFilters) -> int: ...

    def list_account_external_ids(
        self, team: "Team", filters: AccountAudienceFilters, *, cursor: str | None, limit: int
    ) -> list[str]: ...

    def get_account_group_type_name(self, team: "Team") -> str | None: ...


@frozen
class AudienceSize:
    """How many recipients a batch audience matches, and the most a batch trigger may send to."""

    affected: int
    total: int
    limit: int
    dedupe_key: str | None


@frozen
class AudiencePage:
    """One cursor-paginated page of a batch audience: person, group or account ids."""

    ids: list[str]
    has_more: bool


@frozen
class EmailSendingTierLimits:
    """What a trust tier allows: two send-rate caps and a maximum batch audience."""

    tier: int
    per_hour: int
    per_day: int
    max_batch_audience: int


@frozen
class TierDecision:
    team_id: int
    previous_tier: int
    new_tier: int
    reason: str

    @property
    def changed(self) -> bool:
        return self.previous_tier != self.new_tier


@frozen
class EmailSendingState:
    """A team's email sending controls. A team with no config row reads as the field defaults."""

    suspended_at: datetime | None
    suspension_reason: str
    tier: int
    tier_pinned: bool
    tier_updated_at: datetime | None


@frozen
class EmailSendingSuspensionChange:
    """The outcome of a suspend or unsuspend request.

    ``changed_at`` is set only when this request flipped the state. ``previously_suspended_at`` is
    set when a suspend request found the team already suspended.
    """

    changed_at: datetime | None
    previously_suspended_at: datetime | None = None


@frozen
class EmailSendingAllowance:
    """A project's sending tier, what it allows, and how much of that it has used."""

    tier: int
    max_tier: int
    emails_per_hour: int
    emails_per_day: int
    max_batch_audience: int
    emails_sent_last_hour: int
    emails_sent_last_day: int
    enforced: bool


class StaffPausedError(Exception):
    """A customer tried to resume a pause only staff may clear."""


# The app metric names the deliverability signals are read from. A Complaint (the recipient's
# "report spam" relayed through the provider's feedback loop) is recorded as `email_blocked`, and
# only permanent bounces count as `email_bounced_hard`, matching how AWS counts its bounce rate.
# See the SES webhook handler in nodejs/src/cdp/services/messaging/helpers/ses.ts.
SENT_METRIC: Final[str] = "email_sent"
HARD_BOUNCE_METRIC: Final[str] = "email_bounced_hard"
COMPLAINT_METRIC: Final[str] = "email_blocked"
EMAIL_HEALTH_METRIC_NAMES: Final[list[str]] = [SENT_METRIC, HARD_BOUNCE_METRIC, COMPLAINT_METRIC]


@frozen
class EmailSendingCounts:
    sent: int = 0
    bounced_hard: int = 0
    complained: int = 0

    def plus(self, counts: Mapping[str, int]) -> "EmailSendingCounts":
        return EmailSendingCounts(
            sent=self.sent + counts.get(SENT_METRIC, 0),
            bounced_hard=self.bounced_hard + counts.get(HARD_BOUNCE_METRIC, 0),
            complained=self.complained + counts.get(COMPLAINT_METRIC, 0),
        )


@frozen
class FlowEmailTotals:
    counts_by_flow: dict[str, EmailSendingCounts]
    names_by_flow_id: dict[str, str]


@frozen
class WorkflowTemplate:
    """A workflow template stored in the database, owned by one team.

    ``created_by`` carries the core ``User`` row rather than a projection of it, so the
    presentation layer keeps serializing it through core's ``UserBasicSerializer``.

    ``edges`` and ``actions`` hold lists, but a row saved without them keeps the model default
    ``{}``, so both fields can also be a dict.
    """

    id: UUID
    team_id: int
    name: str
    description: str
    image_url: str | None
    tags: list[str]
    scope: HogFlowTemplateScope
    created_at: datetime
    created_by: "User | None"
    updated_at: datetime
    trigger: dict[str, Any]
    trigger_masking: dict[str, Any] | None
    conversion: dict[str, Any] | None
    exit_condition: HogFlowTemplateExitCondition
    edges: list[dict[str, Any]] | dict[str, Any]
    actions: list[dict[str, Any]] | dict[str, Any]
    abort_action: str | None
    variables: list[dict[str, Any]] | None


@frozen
class FunctionTemplateSchema:
    """The parts of a cdp function template that a workflow step validates its inputs against."""

    type: str
    inputs_schema: list[dict[str, Any]] | None


# The provider payloads below are TypedDicts, not frozen dataclasses: the email-verify endpoint
# returns them as JSON without a serializer, so the keys are the API response keys.

EmailDomainVerificationStatus = Literal["success", "failed", "pending"]


class EmailDomainDnsRecord(TypedDict):
    """One DNS record the customer adds before the domain can send email."""

    type: Literal["verification", "dkim", "mail_from", "dmarc"]
    recordType: Literal["TXT", "CNAME", "MX"]
    recordHostname: str
    recordValue: str
    status: Literal["success", "pending"]
    priority: NotRequired[int]


class EmailDomainVerification(TypedDict):
    status: EmailDomainVerificationStatus
    dnsRecords: list[EmailDomainDnsRecord]


class TwilioPhoneNumber(TypedDict):
    """The fields callers read. The Twilio payload has more keys."""

    sid: str
    phone_number: str
    friendly_name: str


class TwilioAccount(TypedDict, total=False):
    """Empty when the Twilio request fails."""

    sid: str
