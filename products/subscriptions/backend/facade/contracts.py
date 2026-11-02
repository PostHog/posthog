"""
Contract types for subscriptions.

Frozen dataclasses and errors that cross the subscriptions boundary.
No Django imports. Used by the facade as inputs and outputs.
"""

import uuid
import typing
import dataclasses
from collections.abc import Mapping
from datetime import datetime


class SubscriptionTriggerType:
    """How a subscription delivery was triggered.

    Plain string constants (not enum.Enum) because Temporal's
    DefaultPayloadConverter mis-deserializes str enums as character lists.
    """

    SCHEDULED = "scheduled"  # Regular cron-based delivery
    SUBSCRIPTION_CHANGE = "target_change"  # An API create or edit triggered an immediate delivery.
    MANUAL = "manual"  # User clicked "Test delivery"


@dataclasses.dataclass(frozen=True)
class ProcessSubscriptionWorkflowInputs:
    subscription_id: int
    team_id: int = 0
    distinct_id: str = ""
    previous_target_value: typing.Optional[str] = None
    # TODO(2026-07-30): Remove in a follow-up after this PR is fully deployed and pre-deployment workflow payloads expire.
    previous_value: typing.Optional[str] = None
    invite_message: typing.Optional[str] = None
    trigger_type: str = SubscriptionTriggerType.SUBSCRIPTION_CHANGE
    scheduled_at: typing.Optional[str] = None
    # Lets HandleSubscriptionValueChangeWorkflow route AI-prompt subs to
    # ProcessAISubscriptionWorkflow. Passed by the API from the loaded instance.
    resource_type: str = ""


class PromptRejectedError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class SharedInsightImage:
    """The first insight of a shared resource, rendered as an image for a link preview."""

    title: str | None
    image_url: str
    alt_text: str | None


@dataclasses.dataclass(frozen=True)
class FailedDeliveryCount:
    """How often one subscription failed to deliver in a period."""

    subscription_id: int
    title: str | None
    prompt: str | None
    failed_deliveries: int
    last_failed_at: datetime


# The API reads and writes below. A view parses the request into these contracts, calls the facade,
# and serializes what comes back.

# A JSON column read back as stored: an object, a list, a scalar or null.
type JsonValue = object


class Unset:
    """Marks a field the request did not mention, because None is a valid value."""


UNSET = Unset()


class SubscriptionNotFoundError(LookupError):
    """No subscription or delivery of the team matches. The API answers 404."""


class MalformedIdError(SubscriptionNotFoundError):
    """The requested id cannot name any row, such as a delivery id that is not a UUID."""


class SubscriptionRequestInvalidError(ValueError):
    """The request breaks a subscription rule. The API answers 400 with `detail`.

    `detail` has the shape a serializer validation error carries: a message, a list of messages, or
    a mapping from field name to messages.
    """

    def __init__(self, detail: str | list[str] | Mapping[str, list[str]]) -> None:
        super().__init__(detail)
        self.detail = detail


class SubscriptionPermissionDeniedError(PermissionError):
    """The requester may not do this. The API answers 403 with the message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SubscriptionQuotaExceededError(Exception):
    """A plan or credit limit refuses the write. The API answers 402 with the message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionCreator:
    """The user fields a subscription response shows for its creator."""

    id: int
    uuid: uuid.UUID
    distinct_id: str | None
    first_name: str
    last_name: str
    email: str
    is_email_verified: bool | None
    hedgehog_config: dict[str, JsonValue] | None
    role_at_organization: str | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionDashboardContext:
    """A dashboard that grounds an AI report."""

    dashboard_id: int
    dashboard_name: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionInsightContext:
    """An insight that grounds an AI report."""

    insight_id: int
    insight_short_id: str
    insight_name: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionRecord:
    """One subscription, with every value its API responses show."""

    id: int
    team_id: int
    resource_type: str
    dashboard_id: int | None
    insight_id: int | None
    insight_short_id: str | None
    resource_name: str | None
    dashboard_export_insight_ids: tuple[int, ...]
    prompt: str | None
    ai_prompt_config: JsonValue
    # Live targets only, and always empty unless resource_type is "ai_prompt".
    contexts: tuple[SubscriptionDashboardContext | SubscriptionInsightContext, ...]
    ai_query_plan_status: str | None
    target_type: str
    # The stored value. A Microsoft Teams webhook URL authorizes a post on its own, so responses show
    # recipient_label for a Teams subscription instead.
    target_value: str
    recipient_label: str
    frequency: str
    interval: int
    byweekday: tuple[str, ...] | None
    bysetpos: int | None
    count: int | None
    start_date: datetime
    until_date: datetime | None
    created_at: datetime
    created_by_id: int | None
    created_by: SubscriptionCreator | None
    deleted: bool
    enabled: bool
    title: str | None
    summary: str
    next_delivery_date: datetime | None
    integration_id: int | None
    summary_enabled: bool
    summary_prompt_guide: str
    delivery_config: JsonValue


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionRef:
    """The stored columns of one subscription that access checks and request routing read."""

    id: int
    team_id: int
    created_by_id: int | None
    deleted: bool
    enabled: bool
    target_type: str
    insight_id: int | None
    dashboard_id: int | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionPage:
    """One page of subscriptions, and how many match in total."""

    count: int
    results: tuple[SubscriptionRecord, ...]


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionFilters:
    """Narrows the subscriptions a read can see. A None filter does not filter.

    The API applies these to every subscription route, so a filter that excludes a subscription
    also makes it unreachable for a retrieve, an update or a test delivery.
    """

    insight_ids: tuple[int, ...] | None = None
    # A second insight filter, combined with insight_ids by AND, as the `insights` parameter is.
    any_of_insight_ids: tuple[int, ...] | None = None
    tile_insight_ids: tuple[int, ...] | None = None
    dashboard_id: int | None = None
    deleted: bool | None = None
    # Each term must match one of title, insight name, dashboard name or prompt, ignoring case.
    search_terms: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionListQuery:
    """What a subscription list asks for, beyond the filters every route applies."""

    filters: SubscriptionFilters
    created_by_uuid: str | None = None
    resource_type: str | None = None
    target_type: str | None = None
    ordering: tuple[str, ...] = ()
    # The object-level access filter that lists apply to their rows. Service credentials skip it.
    filter_by_object_access: bool = True
    include_all_if_admin: bool = False


@dataclasses.dataclass(frozen=True, kw_only=True)
class CreatedAtCursorWindow:
    """One window of a list ordered by creation time, as cursor pagination asks for it.

    `created_before` and `created_after` are the cursor position as the cursor carries it, a
    timestamp string. `limit` rows are returned from `offset` on.
    """

    newest_first: bool
    created_before: str | None = None
    created_after: str | None = None
    offset: int
    limit: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionDeliveryRecord:
    """One delivery run of a subscription, as stored."""

    id: uuid.UUID
    subscription_id: int
    temporal_workflow_id: str
    idempotency_key: str
    trigger_type: str
    scheduled_at: datetime | None
    target_type: str
    target_value: str
    exported_asset_ids: tuple[int, ...]
    content_snapshot: JsonValue
    recipient_results: JsonValue
    status: str
    error: JsonValue
    created_at: datetime
    last_updated_at: datetime
    finished_at: datetime | None
    change_summary: str | None


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionSummaryRecord:
    """An AI summary that a completed delivery carried."""

    id: uuid.UUID
    subscription_id: int
    subscription_title: str | None
    target_type: str
    change_summary: str | None
    # The previous completed delivery of the same subscription, or None for the first one.
    period_start: datetime | None
    created_at: datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class SummaryQuota:
    """How many AI summaries an organization has turned on, against its plan's cap."""

    active_count: int
    limit: int | None
    at_limit: bool


class ManualDeliveryOutcome:
    """What happened when someone asked for a test delivery."""

    STARTED = "started"
    ALREADY_RUNNING = "already_running"
    FAILED = "failed"


@dataclasses.dataclass(frozen=True, kw_only=True)
class ManualDeliveryResult:
    outcome: str
    workflow_id: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionContextTarget:
    """A dashboard or an insight that a write asks to ground an AI report in."""

    kind: typing.Literal["dashboard", "insight"]
    id: int


@dataclasses.dataclass(frozen=True, kw_only=True)
class SubscriptionWrite:
    """The fields a create or an update sets. UNSET leaves a field out of the write.

    Values have passed the request's field checks. The rules that span fields, the team and the
    plan run in the facade.
    """

    dashboard_id: int | None | Unset = UNSET
    insight_id: int | None | Unset = UNSET
    dashboard_export_insight_ids: list[int] | Unset = UNSET
    prompt: str | None | Unset = UNSET
    ai_prompt_config: dict[str, JsonValue] | Unset = UNSET
    contexts: tuple[SubscriptionContextTarget, ...] | Unset = UNSET
    target_type: str | Unset = UNSET
    target_value: str | Unset = UNSET
    frequency: str | Unset = UNSET
    interval: int | Unset = UNSET
    byweekday: list[str] | None | Unset = UNSET
    bysetpos: int | None | Unset = UNSET
    count: int | None | Unset = UNSET
    start_date: datetime | Unset = UNSET
    until_date: datetime | None | Unset = UNSET
    deleted: bool | Unset = UNSET
    enabled: bool | Unset = UNSET
    title: str | None | Unset = UNSET
    integration_id: int | None | Unset = UNSET
    invite_message: str | None | Unset = UNSET
    send_test_now: bool | Unset = UNSET
    summary_enabled: bool | Unset = UNSET
    summary_prompt_guide: str | Unset = UNSET
    delivery_config: dict[str, JsonValue] | Unset = UNSET
