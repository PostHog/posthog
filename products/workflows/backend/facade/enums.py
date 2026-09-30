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


class HogFlowBatchJobState(LabeledStrEnum):
    WAITING = "waiting"
    QUEUED = "queued"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


# The same pairs as HogFlow.State, so the API schema reuses HogFlowStateEnum for it. A labeled enum
# would share HogFlow.State's choices, and then neither class would name the schema enum.
WORKFLOW_STATUS_CHOICES = [(status.value, status.name.title()) for status in WorkflowStatus]


class WorkflowCodeErrorStatus(LabeledStrEnum):
    INVALID_YAML = "invalid_yaml"
    YAML_FEATURE_NOT_ALLOWED = "yaml_feature_not_allowed"
    DUPLICATE_KEY = "duplicate_key"
    CONTENT_TOO_LARGE = "content_too_large"
    UNSUPPORTED_VERSION = "unsupported_version"
    MISSING_FIELD = "missing_field"
    UNKNOWN_FIELD = "unknown_field"
    INVALID_VALUE = "invalid_value"
    UNKNOWN_TYPE = "unknown_type"
    DUPLICATE_STEP_ID = "duplicate_step_id"
    SECRET_INPUT = "secret_input"
    UNKNOWN_TEMPLATE = "unknown_template"
    INVALID_WORKFLOW = "invalid_workflow"
    STATUS_CHANGE_NOT_ALLOWED = "status_change_not_allowed"
    CONFLICT = "conflict"
    TOO_MANY_ERRORS = "too_many_errors"


class WorkflowCodePlanResult(LabeledStrEnum):
    CREATE = "create"
    UPDATE = "update"
    STAGE = "stage"
    UNCHANGED = "unchanged"


class WorkflowCodeApplyResult(LabeledStrEnum):
    CREATED = "created"
    UPDATED = "updated"
    STAGED = "staged"
    UNCHANGED = "unchanged"
