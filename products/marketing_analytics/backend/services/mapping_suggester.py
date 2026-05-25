"""Suggest `custom_source_mappings` and `campaign_name_mappings` entries for a
team based on recent unmatched UTM-tagged events.

Deterministic v1: alias lookups (from `native_integrations`) plus fuzzy match
via `difflib.SequenceMatcher`. An LLM-assisted path for ambiguous cases is
planned for a later PR but is not part of this service today.

The suggestion math reuses `attribution_health` directly so we don't double-
count or diverge on what counts as "unmatched".
"""

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any, Literal

import structlog

from posthog.schema import NativeMarketingSource

from posthog.models.team.team import Team
from posthog.sync import database_sync_to_async

from products.marketing_analytics.backend.services.attribution_health import UnmatchedUtmSample, get_attribution_health
from products.marketing_analytics.backend.services.native_integrations import (
    NATIVE_TO_KEY,
    NativeIntegration,
    aliases_for,
    canonical_source_aliases,
    display_name_for_key,
    normalize,
)

logger = structlog.get_logger(__name__)

MappingMethod = Literal["fuzzy_match", "exact_alias", "llm"]

# Default minimum confidence for a fuzzy match suggestion to surface. The same
# threshold is reused by `attribution_health` for "likely yours" attribution,
# so consumers see consistent decisions across both surfaces.
DEFAULT_CONFIDENCE_THRESHOLD = 0.72

# Minimum 30d event count for a raw value to be worth suggesting. Tiny tails
# don't justify configuration changes.
DEFAULT_MIN_EVENT_COUNT = 10

# Cap suggestions per integration to keep the output digestible by LLMs and UIs.
MAX_SUGGESTIONS_PER_INTEGRATION = 10


@dataclass
class SourceMappingSuggestion:
    raw_utm_source: str
    suggested_target: NativeIntegration
    suggested_target_display_name: str
    confidence: float
    method: MappingMethod
    reason: str
    event_count_30d: int


@dataclass
class CampaignMappingSuggestion:
    integration: NativeIntegration
    integration_display_name: str
    suggested_clean_name: str
    raw_campaign_values: list[str]
    confidence: float
    method: MappingMethod
    reason: str
    event_count_30d: int


@dataclass
class RawUnmatchedSample:
    """A raw utm_source value that doesn't match any integration. Distinct from
    `SourceMappingSuggestion`: this is informational (here is what the team
    has), without committing to a mapping recommendation."""

    raw_utm_source: str
    event_count: int
    fuzzy_best_target: NativeIntegration | None
    fuzzy_best_ratio: float


@dataclass
class CurrentMapping:
    raw_utm_source: str
    target: NativeIntegration
    target_display_name: str
    source: Literal["canonical", "team_custom"]


@dataclass
class CatalogueEntry:
    """Every utm_source value seen in the window. Includes matched ones too so
    the LLM can give a complete picture (instead of recurring to ad-hoc SQL)."""

    raw_utm_source: str
    event_count: int
    matched_integration: NativeIntegration | None
    matched_integration_display_name: str | None
    fuzzy_best_target: NativeIntegration | None
    fuzzy_best_ratio: float


@dataclass
class UtmMappingSuggestionsResponse:
    source_suggestions: list[SourceMappingSuggestion] = field(default_factory=list)
    campaign_suggestions: list[CampaignMappingSuggestion] = field(default_factory=list)
    raw_unmatched_samples: list[RawUnmatchedSample] = field(default_factory=list)
    full_utm_source_catalogue: list[CatalogueEntry] = field(default_factory=list)
    current_mappings: list[CurrentMapping] = field(default_factory=list)
    total_unmatched_events_in_window: int = 0
    total_events_with_utm_in_window: int = 0
    lookback_days_used: int = 0
    confidence_threshold_used: float = DEFAULT_CONFIDENCE_THRESHOLD
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def suggest_utm_mappings(
    team: Team,
    *,
    min_event_count: int = DEFAULT_MIN_EVENT_COUNT,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    max_per_integration: int = MAX_SUGGESTIONS_PER_INTEGRATION,
    lookback_days: int = 90,
) -> UtmMappingSuggestionsResponse:
    """Detect unmatched utm_source values and propose target integrations.

    `lookback_days` defaults to 90 days because 7 (the attribution_health default)
    is too narrow to catch typo'd or one-off utm_source values that the user
    might want to map. Callers can widen further (e.g. 365) for catalog-style
    audits.
    """
    attribution = await get_attribution_health(team, lookback_days=lookback_days)
    current_mappings = await _read_current_mappings(team)
    notes: list[str] = []

    # 1. High-confidence suggestions: raw values where fuzzy match crosses the
    # threshold. These are safe to apply directly. Aggregate across integrations
    # so each raw value appears once with its best-confidence target.
    # Source candidates from the global unmatched list (capped at
    # MAX_GLOBAL_UNMATCHED), not each integration's per-entry samples — those
    # are capped at the much smaller MAX_SAMPLE_UNMATCHED, which would make
    # `max_per_integration` unreachable.
    by_raw: dict[str, SourceMappingSuggestion] = {}
    for sample in attribution.sample_globally_unmatched:
        if sample.event_count < min_event_count:
            continue
        if sample.suggested_integration is None or sample.fuzzy_ratio < confidence_threshold:
            continue
        current = by_raw.get(sample.raw_value)
        if current is None or sample.fuzzy_ratio > current.confidence:
            by_raw[sample.raw_value] = _to_source_suggestion(sample, sample.suggested_integration)

    # Cap per integration to keep output digestible.
    grouped: dict[NativeIntegration, list[SourceMappingSuggestion]] = defaultdict(list)
    for suggestion in by_raw.values():
        grouped[suggestion.suggested_target].append(suggestion)
    source_suggestions: list[SourceMappingSuggestion] = []
    for key, items in grouped.items():
        items.sort(key=lambda s: s.event_count_30d, reverse=True)
        if len(items) > max_per_integration:
            notes.append(
                f"{display_name_for_key(key)}: showing top {max_per_integration} of {len(items)} candidate values."
            )
        source_suggestions.extend(items[:max_per_integration])
    source_suggestions.sort(key=lambda s: s.event_count_30d, reverse=True)

    # 2. ALL raw unmatched samples, regardless of fuzzy confidence. The LLM
    # needs to see the actual catalogue (not just high-confidence guesses) to
    # produce useful explanations like "you have 152 conversions tagged
    # utm_source=organic — these are not from any ad platform".
    raw_unmatched: list[RawUnmatchedSample] = []
    for s in attribution.sample_globally_unmatched:
        if s.event_count < min_event_count:
            continue
        raw_unmatched.append(
            RawUnmatchedSample(
                raw_utm_source=s.raw_value,
                event_count=s.event_count,
                fuzzy_best_target=s.suggested_integration,
                fuzzy_best_ratio=s.fuzzy_ratio,
            )
        )

    if attribution.total_events_unmatched > 0 and not source_suggestions:
        notes.append(
            f"{attribution.total_events_unmatched} events with unmatched utm_source were seen "
            f"in the last {lookback_days} days but none crossed the confidence threshold "
            f"({confidence_threshold:.2f}). The raw values are listed under `raw_unmatched_samples` "
            "for the LLM/user to review manually — many will be 'organic', 'direct', test campaigns, "
            "or partner traffic that should NOT be mapped to ad platforms."
        )

    if attribution.total_events_with_utm == 0:
        notes.append(
            f"No events with utm_source were seen in the last {lookback_days} days. This does NOT "
            "mean the team has never had UTM data — try widening `lookback_days` (e.g. 365) before "
            "concluding that UTM tagging has never worked. If the longer window also shows 0, then "
            "UTMs really aren't being captured (check ad URL tagging, SDK install on landing pages, "
            "and redirects that may strip query params)."
        )

    final_notes = [
        *notes,
        "Campaign clustering (campaign_name_mappings) is not yet implemented; "
        "this v1 only proposes custom_source_mappings entries.",
    ]
    catalogue: list[CatalogueEntry] = []
    for entry in attribution.all_utm_source_samples:
        catalogue.append(
            CatalogueEntry(
                raw_utm_source=entry.raw_value,
                event_count=entry.event_count,
                matched_integration=entry.matched_integration,
                matched_integration_display_name=(
                    display_name_for_key(entry.matched_integration) if entry.matched_integration else None
                ),
                fuzzy_best_target=entry.fuzzy_best_target,
                fuzzy_best_ratio=entry.fuzzy_best_ratio,
            )
        )

    return UtmMappingSuggestionsResponse(
        source_suggestions=source_suggestions,
        campaign_suggestions=[],  # campaign clustering disabled in v1
        raw_unmatched_samples=raw_unmatched,
        full_utm_source_catalogue=catalogue,
        current_mappings=current_mappings,
        total_unmatched_events_in_window=attribution.total_events_unmatched,
        total_events_with_utm_in_window=attribution.total_events_with_utm,
        lookback_days_used=lookback_days,
        confidence_threshold_used=confidence_threshold,
        notes=final_notes,
    )


@database_sync_to_async
def _read_team_custom_mappings(team: Team) -> dict:
    config = getattr(team, "marketing_analytics_config", None)
    return config.custom_source_mappings if config is not None else {}


async def _read_current_mappings(team: Team) -> list[CurrentMapping]:
    """Return the full list of utm_source → integration mappings already in
    effect for this team: hardcoded canonical aliases plus the team's
    `custom_source_mappings`. Allows the LLM to say 'fb is already covered
    canonically' instead of suggesting it again."""
    custom = await _read_team_custom_mappings(team)
    out: list[CurrentMapping] = []

    for alias, target in sorted(canonical_source_aliases().items()):
        out.append(
            CurrentMapping(
                raw_utm_source=alias,
                target=target,
                target_display_name=display_name_for_key(target),
                source="canonical",
            )
        )
    if custom:
        for integration_type, raw_values in custom.items():
            try:
                native = NativeMarketingSource(integration_type)
            except ValueError:
                continue
            custom_target = NATIVE_TO_KEY.get(native)
            if custom_target is None:
                continue
            for raw in raw_values or []:
                out.append(
                    CurrentMapping(
                        raw_utm_source=str(raw),
                        target=custom_target,
                        target_display_name=display_name_for_key(custom_target),
                        source="team_custom",
                    )
                )
    return out


def _to_source_suggestion(sample: UnmatchedUtmSample, target: NativeIntegration) -> SourceMappingSuggestion:
    return SourceMappingSuggestion(
        raw_utm_source=sample.raw_value,
        suggested_target=target,
        suggested_target_display_name=display_name_for_key(target),
        confidence=sample.fuzzy_ratio,
        method="fuzzy_match",
        reason=_build_reason(sample.raw_value, target, sample.fuzzy_ratio),
        event_count_30d=sample.event_count,
    )


def _build_reason(raw: str, target: NativeIntegration, ratio: float) -> str:
    closest_alias = _closest_alias(raw, target)
    return (
        f"Fuzzy match '{raw}' ↔ '{closest_alias}' (ratio={ratio:.2f}); "
        f"'{closest_alias}' is a known alias of {display_name_for_key(target)}."
    )


def _closest_alias(raw: str, target: NativeIntegration) -> str:
    norm_raw = normalize(raw)
    best_alias = ""
    best_ratio = 0.0
    for alias in aliases_for(target):
        ratio = SequenceMatcher(None, norm_raw, alias).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_alias = alias
    return best_alias
