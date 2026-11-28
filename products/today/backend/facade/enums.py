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
    EXPERIMENT = "experiment", "An experiment you run"
    AGENT = "agent", "Your agents query this"
    EVALUATION = "evaluation", "An evaluation you created"


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


class SeasonalActionKind(LabeledStrEnum):
    ASK_AI = "ask_ai", "Do it with PostHog AI"


class SeasonalItemIcon(LabeledStrEnum):
    BELL = "bell", "Bell"
    BUG = "bug", "Bug"
    CHECK = "check", "Check"
    FLAG = "flag", "Flag"
    GRAPH = "graph", "Graph"
    LAPTOP = "laptop", "Laptop"
    MESSAGE = "message", "Message"
    NOTIFICATION = "notification", "Notification"
    PLUG = "plug", "Plug"
    PULSE = "pulse", "Pulse"
    ROCKET = "rocket", "Rocket"
    SERVER = "server", "Server"
    SPARKLES = "sparkles", "Sparkles"
    TOGGLE = "toggle", "Toggle"
    WARNING = "warning", "Warning"


class HogAccessory(LabeledStrEnum):
    BERET = "beret", "Beret"
    CAP = "cap", "Cap"
    CHEF = "chef", "Chef hat"
    COWBOY = "cowboy", "Cowboy hat"
    EYEPATCH = "eyepatch", "Eyepatch"
    FLAG = "flag", "Flag"
    GLASSES = "glasses", "Glasses"
    GRADUATION = "graduation", "Graduation cap"
    PARROT = "parrot", "Parrot"
    PARTY = "party", "Party hat"
    PINEAPPLE = "pineapple", "Pineapple"
    SUNGLASSES = "sunglasses", "Sunglasses"
    TOPHAT = "tophat", "Top hat"
    XMAS_ANTLERS = "xmas-antlers", "Christmas antlers"
    XMAS_HAT = "xmas-hat", "Christmas hat"
    XMAS_SCARF = "xmas-scarf", "Christmas scarf"
