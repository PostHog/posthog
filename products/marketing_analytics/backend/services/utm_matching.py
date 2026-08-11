"""How a raw UTM value resolves to an ad-platform campaign or source.

Extracted from `utm_audit` so the audit and the setup suggesters share one
definition of "matched". Everything here is a pure function over a `TeamMappings`
snapshot plus the campaign rows an adapter emitted — no queries, no Django ORM
beyond the single config read in `load_team_mappings`.

Two vocabularies meet in this module and are easy to confuse:

- `source_name` / *primary source* — what an adapter emits on its rows ('google',
  'meta'). Lowercase, matched against `utm_source`.
- `NativeMarketingSource` — the PascalCase enum value team config is keyed by
  ('GoogleAds'). Use `native_integrations.native_for_primary_source` to cross over.
"""

from functools import cache
from typing import Literal, NamedTuple

import structlog

from posthog.schema import NativeMarketingSource

from posthog.models.team.team import Team

from products.marketing_analytics.backend.hogql_queries.constants import INTEGRATION_DEFAULT_SOURCES
from products.marketing_analytics.backend.services.native_integrations import (
    KEY_TO_NATIVE,
    canonical_source_aliases,
    iter_custom_source_mappings,
    normalize,
    primary_source_for,
)
from products.marketing_analytics.backend.services.types import Campaign, MatchType, TeamMappings

logger = structlog.get_logger(__name__)

MatchFieldName = Literal["campaign_name", "campaign_id"]

DEFAULT_MATCH_FIELD: MatchFieldName = "campaign_name"


class CampaignMatch(NamedTuple):
    """Why a `utm_campaign` value resolved to a platform campaign.

    `match_type` is AUTO when the raw value equals the campaign's configured match
    field, MAPPED when it only matched through `campaign_name_mappings`.
    """

    campaign_name: str
    match_type: str


def load_team_mappings(team: Team) -> TeamMappings:
    """Load custom source mappings and campaign name mappings from team config."""
    config = team.marketing_analytics_config
    if config is None:
        return TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})

    # Build source mapping: custom utm_source values -> the integration's primary source.
    # e.g. custom_source_mappings = {"GoogleAds": ["partner_blog", "affiliate"]} →
    # {"partner_blog": "google", "affiliate": "google"} because the GoogleAds adapter
    # uses "google" as `source_name`. The (target_key, raw_value) pairs come from
    # `iter_custom_source_mappings` so the enum-resolution rules stay shared with
    # `native_integrations.build_combined_alias_map`.
    source_to_integration: dict[str, str] = {}
    for target_key, raw_value in iter_custom_source_mappings(config.custom_source_mappings):
        native = KEY_TO_NATIVE[target_key]
        primary = primary_source_for(native)
        if not primary:
            # Integration without a registered primary source (e.g. shipped before
            # INTEGRATION_PRIMARY_SOURCE was updated). Drop it, but log the gap.
            logger.warning(
                "utm_audit_dropping_custom_mapping_no_primary_source",
                team_id=team.id,
                integration=native.value,
                raw_value=raw_value,
            )
            continue
        source_to_integration[normalize_source_name(raw_value)] = primary

    # Build campaign aliases: clean_campaign_name -> set of raw utm values
    # e.g. campaign_name_mappings = {"GoogleAds": {"brand_campaign": ["partner_q1", "brand_q1"]}}
    campaign_aliases: dict[str, set[str]] = {}
    campaign_name_mappings = config.campaign_name_mappings or {}
    for _integration_type, campaign_map in campaign_name_mappings.items():
        for clean_name, raw_values in campaign_map.items():
            clean_lower = normalize_campaign_name(clean_name)
            if clean_lower not in campaign_aliases:
                campaign_aliases[clean_lower] = set()
            for raw_value in raw_values:
                campaign_aliases[clean_lower].add(normalize_campaign_name(raw_value))

    # Build field preferences, keyed by primary source so campaign rows can be looked
    # up directly by their `source_name`.
    field_preferences: dict[str, str] = {}
    campaign_field_prefs = config.campaign_field_preferences or {}
    for integration_type, prefs in campaign_field_prefs.items():
        match_field = prefs.get("match_field", DEFAULT_MATCH_FIELD)
        try:
            native_source = NativeMarketingSource(integration_type)
        except ValueError:
            continue
        primary = primary_source_for(native_source)
        if primary:
            field_preferences[primary] = match_field

    return TeamMappings(
        source_to_integration=source_to_integration,
        campaign_aliases=campaign_aliases,
        field_preferences=field_preferences,
    )


def build_known_sources(mappings: TeamMappings) -> set[str]:
    """Build the set of utm_source values claimed by any integration (default or custom).

    Used to decide whether an unmatched utm_source is safe to suggest as a mapping —
    if it's already claimed by another integration, mapping it would break that one.
    """
    known: set[str] = set()
    for sources in INTEGRATION_DEFAULT_SOURCES.values():
        for source in sources:
            known.add(normalize_source_name(source))
    # Custom mappings already flattened to source -> primary_source
    known.update(mappings.source_to_integration.keys())
    return known


@cache
def default_alias_to_primary() -> dict[str, str]:
    """Normalized default utm_source aliases ('facebook', 'adwords') -> the
    integration's primary source name ('meta', 'google')."""
    out: dict[str, str] = {}
    for alias, target_key in canonical_source_aliases().items():
        primary = primary_source_for(KEY_TO_NATIVE[target_key])
        if primary:
            out[alias] = primary
    return out


def resolve_source(utm_source: str, mappings: TeamMappings) -> str:
    """Resolve a utm_source to its integration's primary source: team custom
    mappings first (they win, matching `build_combined_alias_map`), then the
    platform default aliases so e.g. 'facebook' resolves to 'meta'.

    Returns the input unchanged when nothing claims it — callers check against
    `build_known_sources` to tell "resolved" from "passed through".
    """
    custom = mappings.source_to_integration.get(utm_source)
    if custom is not None:
        return custom
    return default_alias_to_primary().get(normalize(utm_source), utm_source)


def normalize_source_name(source_name: str) -> str:
    """Canonical form of a `source_name`, for keying anything per integration."""
    return source_name.lower().strip()


def normalize_campaign_name(campaign_name: str) -> str:
    """Canonical form of a campaign name or `utm_campaign` value, for comparing the two.

    A function rather than two method calls at each site: matching hinges on both sides folding
    the same way, and halves that stop agreeing match nothing, silently.
    """
    return campaign_name.lower().strip()


def get_match_field(source_name: str, mappings: TeamMappings) -> str:
    """The field this integration matches campaigns on, per `campaign_field_preferences`."""
    return mappings.field_preferences.get(normalize_source_name(source_name), DEFAULT_MATCH_FIELD)


def get_match_value_raw(campaign: Campaign, mappings: TeamMappings) -> str:
    """The platform-side value a mapping has to produce, in its original casing.

    The field choice lives here, not at each call site: proposing a name to an integration that
    matches on id writes a mapping that never joins.
    """
    if get_match_field(campaign.source_name, mappings) == "campaign_id":
        return campaign.campaign_id.strip()
    return campaign.campaign_name.strip()


def get_match_value(campaign: Campaign, mappings: TeamMappings) -> str:
    """`get_match_value_raw`, lowercased for comparison against utm_campaign values."""
    return normalize_campaign_name(get_match_value_raw(campaign, mappings))


def group_campaigns_by_source(campaigns: list[Campaign]) -> dict[str, list[Campaign]]:
    """Campaigns keyed by normalized `source_name`, skipping any that don't name one.

    Skipping matters: a blank source would otherwise collect its own `""` group.
    """
    grouped: dict[str, list[Campaign]] = {}
    for campaign in campaigns:
        source_name = normalize_source_name(campaign.source_name)
        if not source_name:
            continue
        grouped.setdefault(source_name, []).append(campaign)
    return grouped


def build_campaign_lookup(
    campaigns: list[Campaign],
    mappings: TeamMappings,
) -> dict[str, CampaignMatch]:
    """`utm_campaign` value -> the platform campaign it resolves to.

    The single definition of "this UTM campaign is already matched": a value absent
    from this dict is an orphan, whether the audit is reporting it or a suggester is
    trying to map it. First campaign wins on collision, so callers that care about
    cross-platform collisions must detect those separately (see `_cross_reference`).
    """
    lookup: dict[str, CampaignMatch] = {}
    for campaign in campaigns:
        match_value = get_match_value(campaign, mappings)
        campaign_name_lower = normalize_campaign_name(campaign.campaign_name)
        if match_value not in lookup:
            lookup[match_value] = CampaignMatch(campaign.campaign_name, MatchType.AUTO)
        for alias in mappings.campaign_aliases.get(campaign_name_lower, set()):
            if alias not in lookup:
                lookup[alias] = CampaignMatch(campaign.campaign_name, MatchType.MAPPED)
    return lookup


def build_source_lookup(campaigns: list[Campaign], mappings: TeamMappings) -> dict[str, str]:
    """`utm_source` value -> how it matched a connected integration.

    Only covers sources that a connected integration actually spends on: AUTO for a
    primary source emitted by an adapter, MAPPED for a team custom mapping pointing
    at one of those. A custom mapping to an integration with no campaign rows is
    deliberately absent — there's nothing to attribute to.
    """
    lookup: dict[str, str] = {}
    for campaign in campaigns:
        source_name_lower = normalize_source_name(campaign.source_name)
        if source_name_lower not in lookup:
            lookup[source_name_lower] = MatchType.AUTO
    for custom_source, primary_source in mappings.source_to_integration.items():
        if primary_source in lookup and custom_source not in lookup:
            lookup[custom_source] = MatchType.MAPPED
    return lookup
