"""Should an integration match campaigns by name or by id?

Platforms differ in what they auto-tag into `utm_campaign`. Get it wrong and `match_key`
never joins, so spend lands on one row and conversions on another. Decided on
spend-weighted match rates. Pure function over `get_campaigns_with_spend` and
`get_utm_campaign_catalogue` output.
"""

from dataclasses import dataclass, field

import structlog

from products.marketing_analytics.backend.services.native_integrations import (
    NATIVE_TO_KEY,
    display_name_for_key,
    native_for_primary_source,
)
from products.marketing_analytics.backend.services.types import (
    Campaign,
    CampaignAuditResult,
    TeamMappings,
    UtmIssueKind,
)
from products.marketing_analytics.backend.services.utm_matching import (
    DEFAULT_MATCH_FIELD,
    get_match_field,
    group_campaigns_by_source,
    normalize_campaign_name,
    normalize_source_name,
    resolve_source,
)

logger = structlog.get_logger(__name__)

MIN_CAMPAIGNS = 5

# Several adapters emit an empty `campaign_id`; suggesting id-matching there is a regression.
MIN_ID_COVERAGE = 0.8

# Both are needed: +20pp is meaningless if it's 5% -> 25%.
MIN_SPEND_RATE_DELTA = 0.15
MIN_SUGGESTED_SPEND_RATE = 0.50

BATCH_MIN_DELTA = 0.30
BATCH_MIN_SUGGESTED_RATE = 0.70
BATCH_MIN_ID_COVERAGE = 0.95

# Never 1.0: this is a spend-weighted sample of the top 500 campaigns, not a proof.
MIN_CONFIDENCE = 0.55
MAX_CONFIDENCE = 0.95

# Arithmetic can't settle a collision: two platforms really do share the name.
COLLISION_CONFIDENCE = 0.4

MAX_EXAMPLE_CAMPAIGNS = 5


@dataclass
class MatchRates:
    """How well one candidate field matches the catalogue. Spend decides; count is reported
    because a big disagreement between the two is worth a human's attention."""

    match_field: str
    spend_rate: float
    count_rate: float
    matched_spend: float
    matched_campaigns: int


@dataclass
class FieldPreferenceSuggestion:
    # PascalCase `NativeMarketingSource` value, i.e. the key team config uses.
    integration: str
    integration_display_name: str
    current_match_field: str
    suggested_match_field: str
    current: MatchRates
    suggested: MatchRates
    campaigns_considered: int
    total_spend: float
    spend_at_risk: float
    # The ranking key, so a switch that barely helps a big integration can't outrank one that
    # nearly repairs a small one. Can be <= 0 on the collision path.
    spend_recovered: float
    confidence: float
    safe_to_batch: bool
    reason: str
    triggered_by_collision: bool = False
    colliding_integrations: list[str] = field(default_factory=list)
    still_unmatched_examples: list[str] = field(default_factory=list)


def suggest_campaign_field_preferences(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
    audit_results: list[CampaignAuditResult] | None = None,
) -> list[FieldPreferenceSuggestion]:
    """Per integration, compare name-matching vs id-matching and suggest the winner.

    Manual `campaign_name_mappings` are excluded from both rates: they rewrite whichever field is
    preferred, so counting them credits one side for a hit both get. Rates are scoped per
    integration because the table groups on a `(campaign, source)` row key.
    """
    values_by_source = _utm_values_by_source(utm_events, mappings)
    collisions_by_source = _collisions_by_source(audit_results or [])

    suggestions: list[FieldPreferenceSuggestion] = []
    for source_name, group in group_campaigns_by_source(campaigns).items():
        suggestion = _suggest_for_integration(
            source_name=source_name,
            group=group,
            utm_campaign_values=values_by_source.get(source_name, set()),
            mappings=mappings,
            colliding_integrations=collisions_by_source.get(source_name, set()),
        )
        if suggestion is not None:
            suggestions.append(suggestion)

    # By recovery, not by the current gap. `integration` breaks ties so output is stable.
    suggestions.sort(key=lambda s: (-s.spend_recovered, s.integration))
    return suggestions


def _utm_values_by_source(
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
) -> dict[str, set[str]]:
    """Primary source -> the `utm_campaign` values that arrived tagged as that integration.

    A source resolving to nothing is credited to nobody: its traffic lands on its own table row,
    so counting it here would claim spend is attributed when it isn't. Both halves are folded like
    `_candidate_value` folds the campaign side — folding one made a perfectly tagged MixedCase
    account read as matching 0% of its spend.
    """
    aliased = {raw for raws in mappings.campaign_aliases.values() for raw in raws}

    values: dict[str, set[str]] = {}
    for (utm_campaign, utm_source), _ in utm_events.items():
        value = normalize_campaign_name(utm_campaign)
        # An aliased value resolves under either field, so counting it credits one side unfairly.
        if not value or value in aliased:
            continue
        primary = resolve_source(normalize_source_name(utm_source), mappings)
        values.setdefault(primary, set()).add(value)
    return values


def _collisions_by_source(audit_results: list[CampaignAuditResult]) -> dict[str, set[str]]:
    """source_name -> the other platforms it collides with on a campaign name."""
    collisions: dict[str, set[str]] = {}
    for result in audit_results:
        source_name = normalize_source_name(result.source_name)
        for issue in result.issues:
            if issue.kind == UtmIssueKind.NAME_COLLISION:
                collisions.setdefault(source_name, set()).update(issue.shared_with_integrations)
    return collisions


def _rates_for(group: list[Campaign], utm_campaign_values: set[str], match_field: str) -> MatchRates:
    total_spend = sum(c.spend for c in group)
    matched = [c for c in group if _candidate_value(c, match_field) in utm_campaign_values]
    matched_spend = sum(c.spend for c in matched)
    return MatchRates(
        match_field=match_field,
        spend_rate=(matched_spend / total_spend) if total_spend > 0 else 0.0,
        count_rate=(len(matched) / len(group)) if group else 0.0,
        matched_spend=matched_spend,
        matched_campaigns=len(matched),
    )


def _candidate_value(campaign: Campaign, match_field: str) -> str:
    raw = campaign.campaign_id if match_field == "campaign_id" else campaign.campaign_name
    return normalize_campaign_name(raw)


def _id_coverage(group: list[Campaign]) -> float:
    if not group:
        return 0.0
    return sum(1 for c in group if c.campaign_id.strip()) / len(group)


def _suggest_for_integration(
    *,
    source_name: str,
    group: list[Campaign],
    utm_campaign_values: set[str],
    mappings: TeamMappings,
    colliding_integrations: set[str],
) -> FieldPreferenceSuggestion | None:
    native = native_for_primary_source(source_name)
    if native is None:
        logger.debug("campaign_field_suggester.unknown_source", source_name=source_name)
        return None

    if len(group) < MIN_CAMPAIGNS:
        return None

    current_field = get_match_field(source_name, mappings)

    # id-matching is the cure for a collision, so a team already on it has nothing to change.
    # Otherwise the target field, "whatever isn't current", suggests reintroducing the ambiguity.
    if colliding_integrations and current_field == "campaign_id":
        return None

    target_field = "campaign_id" if current_field != "campaign_id" else DEFAULT_MATCH_FIELD

    if target_field == "campaign_id" and _id_coverage(group) < MIN_ID_COVERAGE:
        return None

    current = _rates_for(group, utm_campaign_values, current_field)
    suggested = _rates_for(group, utm_campaign_values, target_field)

    delta = suggested.spend_rate - current.spend_rate
    beats_current = delta >= MIN_SPEND_RATE_DELTA and suggested.spend_rate >= MIN_SUGGESTED_SPEND_RATE

    if not beats_current and not colliding_integrations:
        return None

    total_spend = sum(c.spend for c in group)
    display_name = display_name_for_key(NATIVE_TO_KEY[native])

    if beats_current:
        confidence = _confidence_for_delta(delta)
        safe_to_batch = (
            delta >= BATCH_MIN_DELTA
            and suggested.spend_rate >= BATCH_MIN_SUGGESTED_RATE
            and (target_field != "campaign_id" or _id_coverage(group) >= BATCH_MIN_ID_COVERAGE)
        )
        reason = _delta_reason(display_name, current, suggested, total_spend)
        triggered_by_collision = False
    else:
        confidence = COLLISION_CONFIDENCE
        safe_to_batch = False
        reason = _collision_reason(display_name, sorted(colliding_integrations), group, utm_campaign_values)
        triggered_by_collision = True

    return FieldPreferenceSuggestion(
        integration=native.value,
        integration_display_name=display_name,
        current_match_field=current_field,
        suggested_match_field=target_field,
        current=current,
        suggested=suggested,
        campaigns_considered=len(group),
        total_spend=total_spend,
        spend_at_risk=total_spend - current.matched_spend,
        spend_recovered=suggested.matched_spend - current.matched_spend,
        confidence=confidence,
        safe_to_batch=safe_to_batch,
        reason=reason,
        triggered_by_collision=triggered_by_collision,
        colliding_integrations=sorted(colliding_integrations),
        still_unmatched_examples=_still_unmatched(group, utm_campaign_values, target_field),
    )


def _confidence_for_delta(delta: float) -> float:
    """Scale linearly from the suggest threshold up to a near-total sweep."""
    scaled = 0.5 + (delta - MIN_SPEND_RATE_DELTA) / 0.70
    return round(min(max(scaled, MIN_CONFIDENCE), MAX_CONFIDENCE), 2)


def _still_unmatched(group: list[Campaign], utm_campaign_values: set[str], match_field: str) -> list[str]:
    unmatched = [c for c in group if _candidate_value(c, match_field) not in utm_campaign_values]
    unmatched.sort(key=lambda c: -c.spend)
    return [c.campaign_name for c in unmatched[:MAX_EXAMPLE_CAMPAIGNS]]


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _money(value: float) -> str:
    return f"{value:,.0f}"


def _delta_reason(display_name: str, current: MatchRates, suggested: MatchRates, total_spend: float) -> str:
    reason = (
        f"{suggested.match_field} matches {_pct(suggested.spend_rate)} of {display_name} spend "
        f"({_money(suggested.matched_spend)} of {_money(total_spend)}) vs "
        f"{_pct(current.spend_rate)} for {current.match_field}."
    )
    # A big spend/count gap usually means one expensive campaign is carrying the verdict.
    if abs(suggested.spend_rate - suggested.count_rate) >= 0.25:
        reason += (
            f" By campaign count the gap is smaller ({_pct(suggested.count_rate)} vs "
            f"{_pct(current.count_rate)}) — spend is concentrated in a few campaigns."
        )
    return reason


def _display_name_for_source(source_name: str) -> str:
    """Primary source key -> the name a human recognises. Collisions arrive as raw keys while the
    subject is already rendered, so without this one sentence mixes both vocabularies."""
    native = native_for_primary_source(source_name)
    return display_name_for_key(NATIVE_TO_KEY[native]) if native is not None else source_name


def _collision_reason(
    display_name: str,
    colliding: list[str],
    group: list[Campaign],
    utm_campaign_values: set[str],
) -> str:
    # `in`, not `not in`: a shared name only misattributes campaigns that receive traffic.
    affected = [c for c in group if _candidate_value(c, DEFAULT_MATCH_FIELD) in utm_campaign_values]
    others = ", ".join(_display_name_for_source(source) for source in colliding) or "another integration"
    return (
        f"{display_name} shares campaign names with {others}, so name matching can't tell them "
        f"apart — {len(affected)} campaign(s) worth {_money(sum(c.spend for c in affected))} are "
        "affected. Matching on campaign_id disambiguates, but only if the ad URLs put the id in "
        "utm_campaign."
    )
