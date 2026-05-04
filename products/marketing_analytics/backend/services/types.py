from dataclasses import (
    dataclass,
    field as dataclass_field,
)
from enum import StrEnum


class UtmIssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class UtmIssueKind(StrEnum):
    # Campaign name matches zero events. Safest fix: update platform URLs.
    NOT_LINKED = "not_linked"
    # Campaign name matches events on another integration but not this one.
    NAME_COLLISION = "name_collision"
    # Campaign name matches events, but with a utm_source that belongs to another integration.
    # Mapping would break the other integration's attribution.
    NO_TAGGED_EVENTS = "no_tagged_events"
    # Campaign name matches events with a utm_source unknown to every integration.
    # Safe to suggest a custom source mapping as an alternative to fixing the URLs.
    UNKNOWN_SOURCE = "unknown_source"


class SuggestedAction(StrEnum):
    # Update utm_source / utm_campaign tracking URLs in the ad platform account.
    # Always the primary recommendation — fixes the root cause.
    FIX_PLATFORM_URLS = "fix_platform_urls"
    # Add a custom source mapping for an unrecognised utm_source value.
    # Only safe when the alt source is not claimed by any other integration.
    ADD_SOURCE_MAPPING = "add_source_mapping"
    # Switch this integration's match field from campaign_name to campaign_id to avoid
    # cross-platform name collisions. Caveat: requires utm_campaign URLs to use the ID too.
    SWITCH_TO_ID_MATCH = "switch_to_id_match"


class MatchType(StrEnum):
    NONE = "none"
    AUTO = "auto"  # matched directly by name/id
    MAPPED = "mapped"  # matched via manual campaign_name_mappings or custom_source_mappings


@dataclass
class AlternativeSource:
    """A utm_source value found for a campaign name, with its event count."""

    utm_source: str
    event_count: int


@dataclass
class UtmIssue:
    field: str
    severity: UtmIssueSeverity
    kind: UtmIssueKind
    # Optional headline. Frontend composes the full message from `kind` + context fields.
    # Kept for logs / API consumers that don't render their own text.
    message: str = ""
    alternative_sources: list[AlternativeSource] = dataclass_field(default_factory=list)
    shared_with_integrations: list[str] = dataclass_field(default_factory=list)
    # Ordered list of suggested remediations. First entry is the primary recommendation.
    suggested_actions: list[SuggestedAction] = dataclass_field(default_factory=list)


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
    issues: list[UtmIssue] = dataclass_field(default_factory=list)


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
