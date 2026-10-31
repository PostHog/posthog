"""Exported enums for today. Every enum used in a contract dataclass field lives here."""

from posthog.enums import LabeledStrEnum


class KeyClauseRole(LabeledStrEnum):
    PROBLEM = "problem", "Problem"
    CAUSE = "cause", "Cause"
    FIX = "fix", "Fix"


class CitedSource(LabeledStrEnum):
    CODE = "code", "Code"
    SLACK = "slack", "Slack"


class FigureText(LabeledStrEnum):
    LEAD = "lead", "Lead"
    IMPACT = "impact", "Impact"


class ImpactNumberKey(LabeledStrEnum):
    TICKETS = "tickets", "Support tickets"
    QUERY_HOURS = "query-hours", "Database hours"


class FigureSourceKind(LabeledStrEnum):
    SIGNAL = "signal", "Signal"
    RESEARCH = "research", "Agent's research"


class HighlightLabel(LabeledStrEnum):
    RISK = "risk", "Risk"
    OPPORTUNITY = "opportunity", "Opportunity"


class HighlightsStatus(LabeledStrEnum):
    COMPUTING = "computing", "Computing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class HighlightPriority(LabeledStrEnum):
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"
    P4 = "P4", "P4"


class HighlightUnit(LabeledStrEnum):
    EVENTS = "events", "Events"
    PEOPLE = "people", "People"
    NUMBER = "number", "Number"


class HighlightMetricReason(LabeledStrEnum):
    ROUTINE = "routine", "You open this often"
    DASHBOARD = "dashboard", "On a dashboard you open often"
    KEY_METRIC = "key_metric", "Project key metric"
    POPULAR = "popular", "Opened often in this project"


class HighlightPinStatus(LabeledStrEnum):
    READY = "ready", "Ready"
    UNAVAILABLE = "unavailable", "Unavailable"


class HighlightInterval(LabeledStrEnum):
    DAY = "day", "Day"
    WEEK = "week", "Week"
    MONTH = "month", "Month"
