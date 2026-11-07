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
    WATCHED = "watched", "You get updates on this"
    BUILT = "built", "You created or edited this"


class HighlightPinStatus(LabeledStrEnum):
    READY = "ready", "Ready"
    UNAVAILABLE = "unavailable", "Unavailable"


class PulseSlotStatus(LabeledStrEnum):
    PENDING = "pending", "Loading"
    READY = "ready", "Ready"
    EMPTY = "empty", "No data"
    ERROR = "error", "Could not load"


class HighlightInterval(LabeledStrEnum):
    DAY = "day", "Day"
    WEEK = "week", "Week"
    MONTH = "month", "Month"


class SidebarPage(LabeledStrEnum):
    ANALYTICS_ALL = "analytics_all", "View all"
    ANALYTICS_MINE = "analytics_mine", "My work"
    COLLECTIONS = "collections", "Collections"
    ALERTS = "alerts", "Alerts"
    SUBSCRIPTIONS = "subscriptions", "Subscriptions"
    PRODUCT_ANALYTICS = "product_analytics", "Product analytics"
    WEB_ANALYTICS = "web_analytics", "Web analytics"
    SQL_EDITOR = "sql_editor", "SQL editor"
    NEW_INSIGHT = "new_insight", "New insight"


class SidebarIcon(LabeledStrEnum):
    LIST = "list", "List"
    PERSON = "person", "Person"
    PEOPLE = "people", "People"
    BOX = "box", "Box"
    BELL = "bell", "Bell"
    NOTIFICATION = "notification", "Notification"
    POSTHOG = "posthog", "PostHog logo"
    CHART = "chart", "Chart"
    DASHBOARD = "dashboard", "Dashboard"
    NOTEBOOK = "notebook", "Notebook"
    SQL = "sql", "SQL"
    STAR = "star", "Star"
    ROCKET = "rocket", "Rocket"
    TARGET = "target", "Target"
    TRENDING = "trending", "Trending"
    GLOBE = "globe", "Globe"
    SPARKLE = "sparkle", "Sparkle"
    BOLT = "bolt", "Bolt"
    FLAG = "flag", "Flag"
    WARNING = "warning", "Warning"


class SidebarListSource(LabeledStrEnum):
    PINNED = "pinned", "Items the person pinned"
    RECENTS = "recents", "Items the person opened recently"
    BY_POSTHOG = "by_posthog", "Ready-made analytics by PostHog"


class SidebarButtonVariant(LabeledStrEnum):
    DEFAULT = "default", "Default"
    PRIMARY = "primary", "Primary"
    OUTLINE = "outline", "Outline"
