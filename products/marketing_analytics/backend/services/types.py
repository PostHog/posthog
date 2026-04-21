from dataclasses import dataclass, field
from enum import StrEnum


class UtmIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class MatchType(StrEnum):
    NONE = "none"
    AUTO = "auto"  # matched directly by name/id
    MAPPED = "mapped"  # matched via manual campaign_name_mappings or custom_source_mappings


@dataclass
class UtmIssue:
    field: str
    severity: UtmIssueSeverity
    message: str


@dataclass
class Campaign:
    campaign_name: str
    campaign_id: str
    source_name: str
    spend: float
    clicks: int
    impressions: int


@dataclass
class CampaignAuditResult:
    campaign_name: str
    campaign_id: str
    source_name: str
    spend: float
    clicks: int
    impressions: int
    has_utm_events: bool
    event_count: int
    issues: list[UtmIssue] = field(default_factory=list)


@dataclass
class UtmEvent:
    utm_campaign: str
    utm_source: str
    event_count: int
    campaign_match: str  # MatchType value
    source_match: str  # MatchType value
    matched_campaign: str | None


@dataclass
class UtmAuditResponse:
    total_campaigns: int
    campaigns_with_issues: int
    campaigns_without_issues: int
    total_spend_at_risk: float
    results: list[CampaignAuditResult]
    all_utm_events: list[UtmEvent]


@dataclass
class TeamMappings:
    """Resolved mappings from the team's marketing analytics config."""

    # utm_source -> integration source name (e.g. "partner_blog" -> "google")
    source_to_integration: dict[str, str]
    # clean_campaign -> set of raw utm values (e.g. "brand_campaign" -> {"partner_q1", "brand_q1"})
    campaign_aliases: dict[str, set[str]]
    # lowercase source_name -> "campaign_name" | "campaign_id"
    field_preferences: dict[str, str]
