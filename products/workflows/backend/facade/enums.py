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
