from enum import StrEnum

from posthog.enums import LabeledStrEnum


# nosemgrep: tuple-return-prefer-dataclass -- Django and DRF take choices as (value, label) pairs.
def _choices(members: type[StrEnum]) -> list[tuple[str, str]]:
    # The labels Django's TextChoices derives from the member names, so a model field and the API schema
    # keep the choices a TextChoices class would give them.
    return [(member.value, member.name.replace("_", " ").title()) for member in members]


class EmailTrackingConsentMode(StrEnum):
    # No consent enforcement: tracking follows the email step's own setting only.
    OFF = "off"
    # Track by default; suppress tracking for recipients who have opted out.
    OPT_OUT = "opt_out"
    # Do not track unless the recipient has explicitly opted in.
    OPT_IN = "opt_in"


EMAIL_TRACKING_CONSENT_MODE_CHOICES = _choices(EmailTrackingConsentMode)


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


class WorkflowCodeErrorStatus(StrEnum):
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


class WorkflowCodePlanResult(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    STAGE = "stage"
    UNCHANGED = "unchanged"


class WorkflowCodeApplyResult(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    STAGED = "staged"
    UNCHANGED = "unchanged"


# The same pairs as HogFlow.State, so the API schema reuses HogFlowStateEnum for it.
WORKFLOW_STATUS_CHOICES = _choices(WorkflowStatus)
WORKFLOW_CODE_ERROR_STATUS_CHOICES = _choices(WorkflowCodeErrorStatus)
WORKFLOW_CODE_PLAN_RESULT_CHOICES = _choices(WorkflowCodePlanResult)
WORKFLOW_CODE_APPLY_RESULT_CHOICES = _choices(WorkflowCodeApplyResult)
