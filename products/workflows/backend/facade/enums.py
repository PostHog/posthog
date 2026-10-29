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


class WorkflowIdeaStatus(LabeledStrEnum):
    SUGGESTED = "suggested", "Suggested"
    ACCEPTED = "accepted", "Accepted"
    DISMISSED = "dismissed", "Dismissed"


class WorkflowIdeaSource(LabeledStrEnum):
    MANUAL = "manual", "Manual"
    SCOUT = "scout", "Scout"


class WorkflowImportSource(LabeledStrEnum):
    CUSTOMERIO = "customerio", "Customer.io"


class WorkflowImportNoteLevel(LabeledStrEnum):
    # The step behaves differently in PostHog, and the note says how.
    APPROXIMATED = "approximated", "Approximated"
    # The setting has no PostHog equivalent and was left out.
    UNSUPPORTED = "unsupported", "Unsupported"
    # The step is imported but needs a setting only the team can give, like an email sender.
    NEEDS_INPUT = "needs_input", "Needs input"


class WorkflowImportStatus(LabeledStrEnum):
    PREVIEW = "preview", "Preview"
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    SKIPPED = "skipped", "Skipped"
    FAILED = "failed", "Failed"


class HogFlowState(LabeledStrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class HogFlowOriginProduct(LabeledStrEnum):
    """The product surface that owns a workflow. Null for workflows built in the workflows UI or the API."""

    LOOPS = "loops", "Loops"
    BROADCASTS = "broadcasts", "Broadcasts"
    TRANSACTIONAL_EMAILS = "transactional_emails", "Transactional emails"


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


class EmailDraftSource(LabeledStrEnum):
    ERROR_TRACKING = "error_tracking", "Error tracking issue"
    EARLY_ACCESS = "early_access", "Early access feature"
    SURVEY = "survey", "Survey"
    FEATURE_FLAG = "feature_flag", "Feature flag"
    COHORT = "cohort", "Cohort"


class EmailDraftOrigin(LabeledStrEnum):
    AI = "ai", "AI"
    TEMPLATE = "template", "Template"


class EmailDraftFallbackReason(LabeledStrEnum):
    AI_NOT_APPROVED = "ai_not_approved", "The organization has not approved AI data processing"
    GATEWAY_UNCONFIGURED = "gateway_unconfigured", "The AI gateway is not configured"
    RATE_LIMITED = "rate_limited", "The project used its hourly AI drafts"
    TIMEOUT = "timeout", "The model took too long"
    MODEL_ERROR = "model_error", "The model call failed"
    INVALID_OUTPUT = "invalid_output", "The model returned an unusable draft"


# pinned: step keys in the setup status API - renaming breaks agents that read them
class SetupStepKey(LabeledStrEnum):
    CHANNEL = "channel", "Channel"
    DOMAIN = "domain", "Domain"
    OPT_OUTS = "opt-outs", "Opt-outs"
    SENDING_RULES = "sending-rules", "Sending rules"
    EMAIL_TEMPLATE = "email-template", "Email template"
    FIRST_WORKFLOW = "first-workflow", "First workflow"


class RealtimeAudienceCohortState(LabeledStrEnum):
    """How far a realtime cohort audience's membership has come, as the audience size response reports it."""

    READY = "ready", "Ready"
    BUILDING = "building", "Building"
    REBUILDING = "rebuilding", "Rebuilding"
    NEEDS_ATTENTION = "needs_attention", "Needs attention"


class EmailDomainSetupMethod(LabeledStrEnum):
    AUTO = "auto", "Domain Connect"
    MANUAL = "manual", "Manual DNS records"


class EmailDomainSetupStatus(LabeledStrEnum):
    NOT_STARTED = "not_started", "Not started"
    PENDING = "pending", "Waiting for DNS records"
    RECORDS_FOUND = "records_found", "Records found, waiting for verification"
    VERIFIED = "verified", "Verified"
    TEMPORARY_FAILURE = "temporary_failure", "Temporary failure"
    FAILED = "failed", "Failed"


class EmailDomainSetupRecordKind(LabeledStrEnum):
    VERIFICATION = "verification", "Domain ownership"
    DKIM = "dkim", "DKIM signing"
    SPF = "spf", "SPF"
    MAIL_FROM_MX = "mail_from_mx", "MAIL FROM MX"
    MAIL_FROM_SPF = "mail_from_spf", "MAIL FROM SPF"
    DMARC = "dmarc", "DMARC"


class EmailDomainSetupRecordType(LabeledStrEnum):
    TXT = "TXT", "TXT"
    CNAME = "CNAME", "CNAME"
    MX = "MX", "MX"


class EmailDomainSetupRecordStatus(LabeledStrEnum):
    PENDING = "pending", "Not found yet"
    FOUND = "found", "Found in DNS"
    VERIFIED = "verified", "Verified"


class EmailDomainSetupStepKey(LabeledStrEnum):
    DOMAIN_ADDED = "domain_added", "Domain added"
    RECORDS_FOUND = "records_found", "DNS records found"
    VERIFIED = "verified", "Verified"


class EmailDomainSetupStepState(LabeledStrEnum):
    DONE = "done", "Done"
    PENDING = "pending", "Pending"
    FAILED = "failed", "Failed"
