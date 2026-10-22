"""
Contract types for subscriptions.

Frozen dataclasses and errors that cross the subscriptions boundary.
No Django imports. Used by the facade as inputs and outputs.
"""

import typing
import dataclasses
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
