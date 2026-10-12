from enum import StrEnum

from posthog.enums import LabeledStrEnum


class EmailTrackingConsentMode(StrEnum):
    # No consent enforcement: tracking follows the email step's own setting only.
    OFF = "off"
    # Track by default; suppress tracking for recipients who have opted out.
    OPT_OUT = "opt_out"
    # Do not track unless the recipient has explicitly opted in.
    OPT_IN = "opt_in"


# The labels Django's TextChoices derived from the member names, so the model field and the API
# schema keep the same choices.
EMAIL_TRACKING_CONSENT_MODE_CHOICES = [
    (mode.value, mode.name.replace("_", " ").title()) for mode in EmailTrackingConsentMode
]


class HogFlowTemplateScope(LabeledStrEnum):
    """Visibility of the workflow template"""

    ONLY_TEAM = "team", "Only team"
    ORGANIZATION = "organization", "Organization"
    GLOBAL = "global", "Global"


class HogFlowTemplateExitCondition(LabeledStrEnum):
    CONVERSION = "exit_on_conversion"
    TRIGGER_NOT_MATCHED = "exit_on_trigger_not_matched"
    TRIGGER_NOT_MATCHED_OR_CONVERSION = "exit_on_trigger_not_matched_or_conversion"
    ONLY_AT_END = "exit_only_at_end"


class HogFlowBatchJobState(LabeledStrEnum):
    WAITING = "waiting"
    QUEUED = "queued"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class HogFlowScheduleStatus(LabeledStrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"  # RRULE exhausted (COUNT/UNTIL reached)


class WorkflowProposalStatus(LabeledStrEnum):
    SUGGESTED = "suggested", "Suggested"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    APPLIED = "applied", "Applied"


class HogFlowState(LabeledStrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class HogFlowOriginProduct(LabeledStrEnum):
    """The product surface that owns a workflow. Null for workflows built in the workflows UI or the API."""

    LOOPS = "loops", "Loops"
    BROADCASTS = "broadcasts", "Broadcasts"


class HogFlowEmailSendingPausedBy(LabeledStrEnum):
    AUTO = "auto", "auto"
    STAFF = "staff", "staff"


class HogFlowExitCondition(LabeledStrEnum):
    # The same choices as HogFlowTemplateExitCondition, kept as a separate class so each owner keeps its
    # own enum and the shared OpenAPI component name does not change.
    CONVERSION = "exit_on_conversion"
    TRIGGER_NOT_MATCHED = "exit_on_trigger_not_matched"
    TRIGGER_NOT_MATCHED_OR_CONVERSION = "exit_on_trigger_not_matched_or_conversion"
    ONLY_AT_END = "exit_only_at_end"
