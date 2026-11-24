"""
Exported enums for hogs.

No Django imports: use LabeledStrEnum, not models.TextChoices, for an enum
that backs model or serializer choices.
"""

from posthog.enums import LabeledStrEnum


class HogStatus(LabeledStrEnum):
    SETUP = "setup"
    ACTIVE = "active"
    PAUSED = "paused"


class HogMessageAuthor(LabeledStrEnum):
    USER = "user"
    HOG = "hog"
    SYSTEM = "system"


class HogWakeCause(LabeledStrEnum):
    USER = "user"
    SCHEDULE = "schedule"
    NOTE = "note"
    TRIGGER = "trigger"
    REPORT = "report"
    APPROVAL = "approval"


class HogReportPriority(LabeledStrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


class HogReportStatus(LabeledStrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class HogReportFollowUp(LabeledStrEnum):
    IMPLEMENT = "implement"
    INVESTIGATE = "investigate"


class HogEvidenceKind(LabeledStrEnum):
    INSIGHT = "insight"
    EVENT = "event"
    ERROR = "error"
    REPLAY = "replay"
    FLAG = "flag"
    EXPERIMENT = "experiment"
    SURVEY = "survey"
    LOG = "log"
    TICKET = "ticket"
    MESSAGE = "message"
    CODE = "code"
    OTHER = "other"


class HogActionStatus(LabeledStrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    DONE = "done"


class HogActionDecision(LabeledStrEnum):
    APPROVE = "approve"
    DENY = "deny"


class HogRuleEffect(LabeledStrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
