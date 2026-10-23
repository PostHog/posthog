from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, NotRequired, Protocol, TypedDict
from uuid import UUID

from posthog.dataclasses import frozen

from products.workflows.backend.facade.enums import (
    EmailDraftFallbackReason,
    EmailDraftOrigin,
    HogFlowBatchJobState,
    HogFlowScheduleStatus,
    HogFlowTemplateExitCondition,
    HogFlowTemplateScope,
    SetupStepKey,
    WorkflowProposalStatus,
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
class CohortDependentWorkflow:
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
class OwnedWorkflowHealth:
    """A live workflow one person created: its runs over the last 7 days and what waits on its owner."""

    workflow_id: UUID
    name: str
    succeeded: int
    failed: int
    email_sending_paused: bool
    pending_suggestions: int


@frozen
class WorkflowTaskDailyLimits:
    """A team's daily caps on tasks created by workflows. None means the default cap applies."""

    per_workflow: int | None
    per_team: int | None


@frozen
class WorkflowVisionScanDailyLimits:
    """A team's daily caps on Replay Vision scans requested by workflows. None means the default cap applies."""

    per_workflow: int | None
    per_team: int | None


@frozen
class RealtimeAudienceCohort:
    """A realtime cohort a batch audience sends to from the realtime pipeline's membership."""

    id: int
    name: str
    ready: bool
    # False when the realtime pipeline doesn't run for the cohort's project, so it never becomes ready.
    can_finish: bool


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


@frozen
class WorkflowSchedule:
    """One recurring schedule of a workflow."""

    id: UUID
    hog_flow_id: UUID
    rrule: str
    starts_at: datetime
    timezone: str
    variables: dict[str, Any]
    status: HogFlowScheduleStatus
    next_run_at: datetime | None
    created_at: datetime
    updated_at: datetime


@frozen
class SendCalendarBatchJob:
    """One batch run, with only the fields the send calendar shows."""

    id: UUID
    status: HogFlowBatchJobState
    created_at: datetime


@frozen
class SendCalendarFlow:
    """An active, scheduled email workflow, with only the fields a send calendar card shows.

    The email fields come from the first email step. ``audience_properties`` and ``audience_type``
    come from a batch trigger's filters, and ``email_to`` only from a schedule trigger, which has no
    audience. ``batch_jobs`` holds only the runs inside the requested range.
    """

    id: UUID
    name: str | None
    origin_product: str | None
    created_by: "User | None"
    user_access_level: str | None
    trigger_type: str
    audience_properties: list[dict[str, Any]]
    audience_type: str | None
    email_to: str | None
    message_category_id: str | None
    schedules: tuple[WorkflowSchedule, ...]
    batch_jobs: tuple[SendCalendarBatchJob, ...]


class WorkflowScheduleNotFound(Exception):
    pass


@frozen
class ProcessedSchedules:
    """The schedule ids one scheduler pass fired, initialized, or failed on."""

    processed: list[str]
    initialized: list[str]
    failed: list[str]


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
class RealtimeCohortStatus:
    """How far a realtime cohort audience is from having its membership calculated."""

    id: int
    name: str
    # A CohortRealtimeState value: "ready", "building", "rebuilding" or "needs_attention".
    state: str
    percent_complete: int | None


@frozen
class AudienceSize:
    """How many recipients a batch audience matches, and the most a batch trigger may send to."""

    affected: int
    total: int
    limit: int
    dedupe_key: str | None
    # Set when the audience is one realtime cohort. A send waits until that cohort is ready.
    realtime_cohort: RealtimeCohortStatus | None = None
    # Set when a realtime cohort shares the audience with other conditions, which a save rejects.
    realtime_cohort_with_other_conditions: RealtimeAudienceCohort | None = None


@frozen
class AudiencePage:
    """One cursor-paginated page of a batch audience: person, group or account ids."""

    ids: list[str]
    has_more: bool


class PeopleImportInvalid(Exception):
    """The upload cannot be used. The message is shown to the person who sent it."""


@frozen
class PeopleImportSummary:
    """What an uploaded people list kept, and how many rows it dropped and why."""

    cohort_id: int
    row_count: int
    new_people: int
    columns: list[str]
    dropped_invalid_email: int
    dropped_duplicate_email: int
    dropped_too_large: int


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


class WorkflowTemplateNotFound(Exception):
    pass


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


@frozen
class TeamUtmDefaults:
    enabled: bool
    params: dict[str, str]


@frozen
class MessageAsset:
    invocation_id: str
    action_id: str
    function_id: str
    parent_run_id: str
    kind: str
    distinct_id: str
    person_id: str
    recipient: str
    subject: str
    status: str
    sent_at: datetime
    # Human-readable workflow name; enriched by the endpoint before serialization.
    # Left blank when the workflow no longer exists so the frontend falls back to function_id.
    function_name: str = ""


@frozen
class WorkflowRevisionSummary:
    """One entry of a workflow's version history, without the content snapshot."""

    version: int
    created_at: datetime
    created_by: "User | None"


@frozen
class WorkflowRevision:
    version: int
    created_at: datetime
    created_by: "User | None"
    content: dict[str, Any]


class WorkflowRevisionNotFound(Exception):
    pass


class WorkflowDraftExists(Exception):
    """A draft is staged and the caller did not ask to overwrite it."""


class WorkflowDraftChanged(Exception):
    """The staged draft changed since the caller confirmed the overwrite."""


class WorkflowStale(Exception):
    """The workflow was written elsewhere after the caller loaded the version it edits."""


class WorkflowHasNoDraft(Exception):
    """Publish found no staged draft."""


@frozen
class Workflow:
    """A workflow as the API reads it.

    Each set secret input in ``actions``, ``trigger`` and ``draft`` is already replaced by the
    ``{"secret": True}`` presence marker, so the contract never carries a secret value.
    ``created_by`` carries the core ``User`` row, so the presentation layer keeps serializing it
    through core's ``UserBasicSerializer``. ``user_access_level`` is the reader's access level, or
    None when the reader is a service credential.

    ``edges`` and ``actions`` hold lists, but a row saved without them keeps the model default
    ``{}``, so both fields can also be a dict.
    """

    id: UUID
    team_id: int
    name: str | None
    description: str
    version: int
    status: str
    origin_product: str | None
    created_at: datetime
    created_by: "User | None"
    updated_at: datetime
    trigger: Any
    trigger_masking: dict[str, Any] | None
    conversion: dict[str, Any] | None
    exit_condition: str
    email_sending_rate_limit: dict[str, Any] | None
    edges: list[dict[str, Any]] | dict[str, Any]
    actions: list[dict[str, Any]] | dict[str, Any]
    abort_action: str | None
    variables: list[dict[str, Any]] | None
    billable_action_types: list[str] | None
    schedules: tuple[WorkflowSchedule, ...]
    draft: dict[str, Any] | None
    draft_updated_at: datetime | None
    action_redirects: dict[str, str] | None
    email_sending_paused_at: datetime | None
    email_sending_paused_reason: str
    email_sending_paused_by: str
    email_sending_resumed_at: datetime | None
    user_access_level: str | None
    # Tag names, sorted.
    tags: tuple[str, ...] = ()
    # Read on the list only. A single-workflow read leaves both None and ``schedules`` filled.
    pending_suggestions: int | None = None
    suggestions_enabled: bool | None = None


@frozen
class SuggestionsSample:
    """Whether the live version has sent enough email for the suggestions scout to judge it."""

    reached: bool
    # Tracked sends (sent minus untracked) from the live version's busiest email step in the window.
    tracked_sends: int
    required_sends: int
    version_live_since: datetime


@frozen
class WorkflowRef:
    """A workflow's identity and dispatch settings, for an action that does not return the workflow.

    It carries no step configuration, so it holds no secret input. ``trigger_type`` and
    ``trigger_filters`` come from the stored trigger.
    """

    id: UUID
    team_id: int
    name: str | None
    status: str
    version: int
    trigger_type: str | None
    trigger_filters: dict[str, Any]
    variables: list[dict[str, Any]] | None
    # Read from the published steps, not the draft.
    has_email_step: bool


@frozen
class TransactionalEmailContent:
    """What a transactional email's workflow sends, taken from the message template it was made from."""

    message_template_id: UUID
    name: str
    subject: str
    preheader: str
    html: str
    text: str
    # None uses the project's default sender on create, and keeps the workflow's sender on update.
    from_integration_id: int | None
    message_category_id: UUID | None
    # Sends keep a placeholder instead of the body, and clicks drop the link's query string.
    sensitive: bool = False
    # Empty values use the sender's own address, name and default reply-to.
    from_email: str = ""
    from_name: str = ""
    reply_to: str = ""


class TransactionalEmailSenderUnavailable(Exception):
    """No verified email sender: neither the requested one nor the project's default."""


class TransactionalEmailContentInvalid(Exception):
    """The content has no subject or no body, so the workflow could not send it."""


class WorkflowNotFound(Exception):
    pass


class WorkflowArchived(Exception):
    """An archived workflow cannot be enabled or disabled."""


@frozen
class WorkflowListQuery:
    """What a workflow list asks for. The view validates each value before it builds one.

    ``field_filters`` holds the raw exact-match and ``optimization_enabled`` query parameters. The
    service validates them and raises WorkflowListFiltersInvalid when one does not parse.
    """

    search: str = ""
    created_by_uuid: UUID | None = None
    types: frozenset[str] = frozenset()
    origin_product: str | None = None
    trigger: Any = None
    broadcast_eligible: bool = False
    broadcast_statuses: frozenset[str] = frozenset()
    suggestions_first: bool = False
    # A workflow matches when it carries at least one of these tags.
    tags: frozenset[str] = frozenset()
    field_filters: Mapping[str, str] = field(default_factory=dict)


@frozen
class WorkflowPage:
    """One limit/offset page of a workflow list, and how many workflows the whole list holds."""

    count: int
    results: list[Workflow]


@frozen
class WorkflowListFilterError:
    message: str
    code: str | None


class WorkflowListFiltersInvalid(Exception):
    """A field filter did not parse. ``errors`` maps each parameter to its errors."""

    def __init__(self, errors: dict[str, list[WorkflowListFilterError]]) -> None:
        super().__init__(errors)
        self.errors = errors


class WorkflowAccessDenied(Exception):
    """The caller's access level for the workflow is below `required_level`."""

    def __init__(self, required_level: str) -> None:
        super().__init__(required_level)
        self.required_level = required_level


@frozen
class WorkflowEditState:
    """A workflow's stored fields, as the serializer validates an edit against them.

    Unlike ``Workflow``, it carries the encrypted secret inputs: validation recovers a secret the
    editor sent back masked from these maps. Both stay out of ``repr``. Presentation reads it only
    to validate an edit and never returns it.
    """

    id: UUID
    team_id: int
    name: str | None
    status: str
    version: int
    origin_product: str | None
    created_by: "User | None"
    updated_at: datetime
    trigger: Any
    trigger_masking: dict[str, Any] | None
    conversion: dict[str, Any] | None
    exit_condition: str
    email_sending_rate_limit: dict[str, Any] | None
    edges: list[dict[str, Any]] | dict[str, Any]
    actions: list[dict[str, Any]] | dict[str, Any]
    abort_action: str | None
    variables: list[dict[str, Any]] | None
    draft: dict[str, Any] | None
    draft_updated_at: datetime | None
    encrypted_inputs: dict[str, Any] | None = field(default=None, repr=False)
    draft_encrypted_inputs: dict[str, Any] | None = field(default=None, repr=False)


@frozen
class WorkflowActor:
    """Who made a workflow change, for its activity log entry. ``team_id`` is the project the request
    came through. ``user`` carries the core ``User`` row, as ``log_activity`` takes it."""

    organization_id: UUID
    team_id: int
    user: "User | None"
    was_impersonated: bool


@frozen
class WorkflowWriteResult:
    previous: Mapping[str, object]
    current: Mapping[str, object]
    routed_to_draft: bool = False
    schedules_paused: int = 0


class WorkflowProposalNotFound(Exception):
    pass


class WorkflowProposalResolved(Exception):
    """The suggestion was approved or rejected already."""


class WorkflowProposalConflicts(Exception):
    """Someone changed the steps or fields the suggestion is about since it was written."""

    def __init__(self, conflicts: list[str]) -> None:
        super().__init__(conflicts)
        self.conflicts = conflicts


@frozen
class ProposalApproval:
    """The approved suggestion, and the workflow's fields from before and after its draft was staged."""

    proposal: "WorkflowProposalRecord"
    previous: Mapping[str, object]
    current: Mapping[str, object]


@frozen
class ProposalChanges:
    """What approving a suggestion would stage. `conflicts` names the steps or fields someone else
    changed since it was written; approval is refused while there are any."""

    changes: dict
    conflicts: list[str]


@frozen
class WorkflowProposalRecord:
    """A change to a workflow that an agent proposed, and how a human resolved it."""

    id: UUID
    title: str
    rationale: str
    content: dict[str, Any]
    evidence: dict[str, Any]
    step_id: str | None
    base_version: int
    status: WorkflowProposalStatus
    source_id: str | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: "User | None"
    applied_version: int | None
    rejection_reason: str


@frozen
class CreatedWorkflowProposal:
    proposal: WorkflowProposalRecord
    # False when a retry with the same source_id returned the proposal it already made.
    created: bool


@frozen
class EditedEmailDesign:
    design: dict[str, Any]
    warnings: tuple[str, ...]


class EmailDesignRenderingNotConfigured(Exception):
    pass


class EmailDesignRenderFailed(Exception):
    pass


# pinned: analytics property values for the `workflows data suggestion*` events - renaming breaks dashboards
LifecycleStage = Literal["signup", "onboarding", "trial", "purchase", "churn_risk", "failure", "support", "other"]
# The step chips a suggestion card shows.
OutlineKind = Literal["email", "sms", "push", "slack", "webhook", "delay", "wait_until", "branch", "split", "action"]
DataSuggestionsStatus = Literal["ready", "generating", "ai_not_approved", "unavailable"]


@frozen
class DataSuggestion:
    id: str
    name: str
    description: str
    reason: str
    trigger_event: str
    weekly_count: int
    stage: LifecycleStage
    step_outline: tuple[OutlineKind, ...]
    # Prepared ahead of time with its workflow already built, so a click creates the draft without a model call.
    premade: bool = False


@frozen
class DataSuggestionsResult:
    status: DataSuggestionsStatus
    suggestions: tuple[DataSuggestion, ...]
    # The project's events that a build can wait on. Kept with the cards, so a build does not count events again.
    events: tuple[str, ...] = ()


DataSuggestionBuildStatus = Literal["ready", "building", "failed"]


@frozen
class MissingInput:
    """A setting the draft leaves blank and the team must fill before enabling, like a webhook URL."""

    step_id: str
    step_name: str
    field: str


@frozen
class BuiltSuggestion:
    status: DataSuggestionBuildStatus
    # Set only when the status is ready.
    workflow: dict[str, Any] | None = None
    uses_saved_template: bool = False
    # Set only when the build saved the draft itself.
    workflow_id: str | None = None
    missing_inputs: tuple[MissingInput, ...] = ()


@frozen
class PreparedIdeas:
    """What `prepare_workflow_ideas` did for one project."""

    status: DataSuggestionsStatus
    stored: tuple[str, ...] = ()
    failed_builds: int = 0


class DataSuggestionNotFound(Exception):
    """The suggestion id is unknown, usually because the cached suggestions expired."""


class WorkflowIdeaAlreadyResolved(Exception):
    """The premade idea was already used."""


class EmailDraftSourceNotFound(Exception):
    """The project has no entity with that ID for the requested source."""


class EmailDraftSourceForbidden(Exception):
    """The user may not view the source entity, so its text must not be drafted from."""


@frozen
class EmailDraft:
    """A first draft of an email about an error, feature, survey, flag or cohort. Nothing is saved."""

    subject: str
    preheader: str
    html: str
    text: str
    generated_by: EmailDraftOrigin
    fallback_reason: EmailDraftFallbackReason | None = None


@frozen
class SetupStep:
    """One messaging setup step and whether the project has done it."""

    key: SetupStepKey
    done: bool
