"""Exported enums for today. Every enum used in a contract dataclass field lives here."""

from enum import StrEnum

from posthog.enums import LabeledStrEnum


class BriefingStatus(StrEnum):
    COLLECTING = "collecting"
    WRITING = "writing"
    READY = "ready"
    FAILED = "failed"


class BriefingTrigger(StrEnum):
    SCHEDULED = "scheduled"
    FIRST_OPEN = "first_open"
    REFRESH = "refresh"


class BriefingWriter(StrEnum):
    AGENT = "agent"


class ItemGroup(StrEnum):
    REPORT = "report"
    DASHBOARD = "dashboard"
    OTHER = "other"


class ItemSource(StrEnum):
    SELF_DRIVING = "self_driving"
    PRODUCT_ANALYTICS = "product_analytics"
    ALERTS = "alerts"
    SUPPORT = "support"
    ERROR_TRACKING = "error_tracking"
    GITHUB = "github"


class ItemReason(StrEnum):
    CLAIMED_BY_YOU = "claimed_by_you"
    WAITING_FOR_YOU = "waiting_for_you"
    SUGGESTED_REVIEWER = "suggested_reviewer"
    URGENT_FOR_PROJECT = "urgent_for_project"
    DASHBOARD_YOU_VIEWED = "dashboard_you_viewed"
    DASHBOARD_YOU_STARRED = "dashboard_you_starred"
    INSIGHT_YOU_VIEWED = "insight_you_viewed"
    INSIGHT_YOU_STARRED = "insight_you_starred"
    ALERT_FIRING = "alert_firing"
    ASSIGNED_TICKET = "assigned_ticket"
    ASSIGNED_ERROR_ISSUE = "assigned_error_issue"
    REVIEW_REQUESTED = "review_requested"
    YOUR_PULL_REQUEST = "your_pull_request"


class ItemState(StrEnum):
    OPEN = "open"
    # Resolved, fixed or merged since the briefing was written.
    DONE = "done"
    # Dismissed or deleted since the briefing was written.
    DISMISSED = "dismissed"


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
