"""Vocabulary for the marketing analytics setup plan.

`setup_plan`, `setup_ai_enrichment` and `apply_setup_ops` share these types, the last validating
incoming ops against the same union it emits — which is why ops are Pydantic models rather than
dataclasses like the sibling services use. One definition for both emit and validate is what keeps
a hallucinated op out of the config.

`APPLICABLE_OPS` mutate config server-side; `NAVIGATE_OPS` need a browser or are advice only.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SuggestionKind(StrEnum):
    CONNECT_SOURCE = "connect_source"
    RECONNECT_OAUTH = "reconnect_oauth"
    FIX_SYNC = "fix_sync"
    MAP_SCHEMA_COLUMNS = "map_schema_columns"
    ADD_SOURCE_MAPPING = "add_source_mapping"
    SWITCH_CAMPAIGN_MATCH_FIELD = "switch_campaign_match_field"
    ADD_CAMPAIGN_NAME_MAPPING = "add_campaign_name_mapping"
    FIX_PLATFORM_URLS = "fix_platform_urls"
    CREATE_CONVERSION_GOAL = "create_conversion_goal"
    FIX_CONVERSION_GOAL = "fix_conversion_goal"
    MARK_GOAL_AS_REVENUE = "mark_goal_as_revenue"
    MARK_GOAL_AS_CUSTOMER = "mark_goal_as_customer"


class Capability(StrEnum):
    """What a working setup buys you. Every suggestion says which of these it
    unlocks, so the UI can answer "why should I care?" without extra copy."""

    COST = "cost"
    ATTRIBUTION = "attribution"
    ROAS = "roas"
    CAC = "cac"


class ReadinessStatus(StrEnum):
    UNLOCKED = "unlocked"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


# A mapping is a band-aid over a tagging bug, so each must carry `fix_platform_urls` — the cure.
# Enforced by the validator below, not at each builder, so a new mapping kind can't skip it.
MAPPING_KINDS = frozenset({SuggestionKind.ADD_SOURCE_MAPPING, SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING})


class SuggestionSource(StrEnum):
    DETERMINISTIC = "deterministic"
    AI = "ai"


# Which kinds, once fixed, make other kinds worth doing. Drives ranking.
UNBLOCKS: dict[SuggestionKind, frozenset[SuggestionKind]] = {
    SuggestionKind.CONNECT_SOURCE: frozenset(
        {
            SuggestionKind.SWITCH_CAMPAIGN_MATCH_FIELD,
            SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING,
            SuggestionKind.ADD_SOURCE_MAPPING,
            SuggestionKind.MARK_GOAL_AS_REVENUE,
            SuggestionKind.MARK_GOAL_AS_CUSTOMER,
        }
    ),
    SuggestionKind.RECONNECT_OAUTH: frozenset(
        {
            SuggestionKind.SWITCH_CAMPAIGN_MATCH_FIELD,
            SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING,
        }
    ),
    SuggestionKind.FIX_SYNC: frozenset(
        {
            SuggestionKind.SWITCH_CAMPAIGN_MATCH_FIELD,
            SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING,
        }
    ),
    SuggestionKind.MAP_SCHEMA_COLUMNS: frozenset(
        {
            SuggestionKind.SWITCH_CAMPAIGN_MATCH_FIELD,
            SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING,
        }
    ),
    SuggestionKind.CREATE_CONVERSION_GOAL: frozenset(
        {
            SuggestionKind.MARK_GOAL_AS_REVENUE,
            SuggestionKind.MARK_GOAL_AS_CUSTOMER,
        }
    ),
}

_SEVERITY_RANK = {Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}


class _Op(BaseModel):
    # Reject unknown keys so a hallucinated op fails at the boundary, not silently on defaults.
    model_config = ConfigDict(extra="forbid")


# --- Applicable: the server mutates config ---------------------------------


class AddCustomSourceMapping(_Op):
    op: Literal["add_custom_source_mapping"] = "add_custom_source_mapping"
    integration: str
    raw_utm_source: str


class RemoveCustomSourceMapping(_Op):
    """Inverse of `add_custom_source_mapping`. Exists so the apply endpoint can return a
    real undo op rather than asking the client to reconstruct prior state."""

    op: Literal["remove_custom_source_mapping"] = "remove_custom_source_mapping"
    integration: str
    raw_utm_source: str


class SetCampaignFieldPreference(_Op):
    op: Literal["set_campaign_field_preference"] = "set_campaign_field_preference"
    integration: str
    match_field: Literal["campaign_name", "campaign_id"]


class AddCampaignNameMapping(_Op):
    op: Literal["add_campaign_name_mapping"] = "add_campaign_name_mapping"
    integration: str
    clean_name: str
    raw_values: list[str] = Field(min_length=1)


class RemoveCampaignNameMapping(_Op):
    """Inverse of `add_campaign_name_mapping`."""

    op: Literal["remove_campaign_name_mapping"] = "remove_campaign_name_mapping"
    integration: str
    clean_name: str
    raw_values: list[str] = Field(min_length=1)


class CreateConversionGoal(_Op):
    op: Literal["create_conversion_goal"] = "create_conversion_goal"
    # Validated against `ConversionGoalFilter` by the apply endpoint, which owns that adapter.
    goal: dict[str, Any]
    # Set only on an undo op, to put back the goal a delete removed under its original
    # id. A fresh create always gets a server-assigned id; honouring a client-supplied
    # one would let callers pick ids and collide.
    restore: bool = False


class UpdateConversionGoal(_Op):
    op: Literal["update_conversion_goal"] = "update_conversion_goal"
    conversion_goal_id: str
    patch: dict[str, Any]


class DeleteConversionGoal(_Op):
    op: Literal["delete_conversion_goal"] = "delete_conversion_goal"
    conversion_goal_id: str


class SetSourceColumnMapping(_Op):
    op: Literal["set_source_column_mapping"] = "set_source_column_mapping"
    table_id: str
    field_mappings: dict[str, str]


class SetCustomerAnalyticsEvent(_Op):
    op: Literal["set_customer_analytics_event"] = "set_customer_analytics_event"
    field: Literal[
        "activity_event",
        "signup_pageview_event",
        "signup_event",
        "subscription_event",
        "payment_event",
    ]
    event_node: dict[str, Any]


# --- Navigate-only: the browser does it, or it's advice --------------------


class OpenOauth(_Op):
    op: Literal["open_oauth"] = "open_oauth"
    # Integration `kind` as `api/integrations/authorize` expects it, e.g. "google-ads".
    kind: str


class OpenSourceWizard(_Op):
    op: Literal["open_source_wizard"] = "open_source_wizard"
    # `ExternalDataSource.source_type` — what `urls.dataWarehouseSourceNew` matches on.
    kind: str


class OpenSettings(_Op):
    op: Literal["open_settings"] = "open_settings"
    anchor: str


class FixPlatformUrls(_Op):
    """Advice, never an action. Attached to every mapping suggestion because the
    mapping is a band-aid and correcting the ad platform's tracking template is the
    actual cure."""

    op: Literal["fix_platform_urls"] = "fix_platform_urls"
    integration: str
    campaign_name: str
    expected_utm_campaign: str
    expected_utm_source: str


ApplyOp = Annotated[
    AddCustomSourceMapping
    | RemoveCustomSourceMapping
    | SetCampaignFieldPreference
    | AddCampaignNameMapping
    | RemoveCampaignNameMapping
    | CreateConversionGoal
    | UpdateConversionGoal
    | DeleteConversionGoal
    | SetSourceColumnMapping
    | SetCustomerAnalyticsEvent
    | OpenOauth
    | OpenSourceWizard
    | OpenSettings
    | FixPlatformUrls,
    Field(discriminator="op"),
]

APPLICABLE_OPS: frozenset[str] = frozenset(
    {
        "add_custom_source_mapping",
        "remove_custom_source_mapping",
        "set_campaign_field_preference",
        "add_campaign_name_mapping",
        "remove_campaign_name_mapping",
        "create_conversion_goal",
        "update_conversion_goal",
        "delete_conversion_goal",
        "set_source_column_mapping",
        "set_customer_analytics_event",
    }
)

NAVIGATE_OPS: frozenset[str] = frozenset(
    {
        "open_oauth",
        "open_source_wizard",
        "open_settings",
        "fix_platform_urls",
    }
)


class Suggestion(BaseModel):
    """One row in the setup plan."""

    # Stable across scans: the frontend remembers dismissals by this.
    id: str
    kind: SuggestionKind
    source: SuggestionSource = SuggestionSource.DETERMINISTIC
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    evidence: str
    unlocks: list[Capability] = Field(default_factory=list)
    apply: ApplyOp | None = None
    also_recommended: list[ApplyOp] = Field(default_factory=list)
    safe_to_batch: bool = False
    rank_score: float = 0.0
    integration: str | None = None
    deep_link: str | None = None
    spend_at_risk: float = 0.0
    event_volume: int = 0

    @model_validator(mode="after")
    def _mapping_suggestions_carry_the_url_fix(self) -> "Suggestion":
        if self.kind in MAPPING_KINDS and not any(op.op == "fix_platform_urls" for op in self.also_recommended):
            raise ValueError(
                f"{self.kind.value} suggestions must carry a fix_platform_urls op in also_recommended: "
                "the mapping is a workaround, and offering it without the cure teaches the wrong fix."
            )
        return self


class CapabilityReadiness(BaseModel):
    capability: Capability
    status: ReadinessStatus
    explanation: str
    # `Suggestion.id`s — the link from "ROAS is blocked" to the rows that unblock it.
    blocked_by: list[str] = Field(default_factory=list)


class SetupPlan(BaseModel):
    suggestions: list[Suggestion] = Field(default_factory=list)
    readiness: list[CapabilityReadiness] = Field(default_factory=list)
    degraded: list[str] = Field(default_factory=list)
    # Rates are over the queries' top-N rows, so a percentage is a subtotal.
    truncated: bool = False
    summary: str = ""


def rank_score(suggestion: Suggestion, present_kinds: set[SuggestionKind], max_impact: float) -> float:
    """Unblocking-first, then severity, then impact.

    An action that unblocks others outranks one that doesn't, however big the latter's number.
    `max_impact` normalises so impact can't outweigh the two structural terms.
    """
    unblocked = len(UNBLOCKS.get(suggestion.kind, frozenset()) & present_kinds)
    impact = suggestion.spend_at_risk or float(suggestion.event_volume)
    normalised_impact = (impact / max_impact) if max_impact > 0 else 0.0
    return (100 * unblocked) + (10 * _SEVERITY_RANK[suggestion.severity]) + normalised_impact


def sort_suggestions(suggestions: list[Suggestion]) -> list[Suggestion]:
    """Score and sort, returning a new list. Ties break on `id` so output is byte-identical run
    to run — snapshot tests depend on it, and so does a UI that shouldn't reshuffle."""
    present_kinds = {s.kind for s in suggestions}
    max_impact = max((s.spend_at_risk or float(s.event_volume) for s in suggestions), default=0.0)
    for suggestion in suggestions:
        suggestion.rank_score = rank_score(suggestion, present_kinds, max_impact)
    return sorted(suggestions, key=lambda s: (-s.rank_score, s.id))
