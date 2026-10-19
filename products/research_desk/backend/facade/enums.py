"""Exported enums for research_desk."""

from posthog.enums import LabeledStrEnum


class SourceKind(LabeledStrEnum):
    WORKFLOW = "workflow", "Workflow"
    SURVEY = "survey", "Survey"
    COHORT = "cohort", "Cohort"
    EVENT = "event", "Event"


class SourceOrigin(LabeledStrEnum):
    MANUAL = "manual", "Manual"
    SCOUT = "scout", "Scout"


class SessionStatus(LabeledStrEnum):
    SCHEDULED = "scheduled", "Scheduled"
    HELD = "held", "Held"
    CANCELLED = "cancelled", "Cancelled"


class SessionOrigin(LabeledStrEnum):
    CALENDAR = "calendar", "Calendar"
    MANUAL = "manual", "Manual"


class TouchChannel(LabeledStrEnum):
    EMAIL = "email", "Email"
    SURVEY = "survey", "Survey"
    EVENT = "event", "Event"
    COHORT = "cohort", "Cohort"
    SESSION = "session", "Session"
