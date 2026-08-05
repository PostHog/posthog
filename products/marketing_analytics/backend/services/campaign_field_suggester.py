"""Suggest `campaign_field_preferences` — should an integration match campaigns by
name or by id?

Ad platforms differ in what they put in `utm_campaign`: some auto-tag the campaign
name, some the numeric id, and Google's auto-tagging depends on the template the
account configured. Get it wrong and `match_key` never joins, so spend lands on one
row and conversions on another and every ROAS on the dashboard is wrong — see the
join in `marketing_analytics_table_query_runner`.

The decision is pure arithmetic over data the audit already fetched: count how much
*spend* would match under each field and pick the winner. No LLM: an LLM would be
strictly worse at this and non-reproducible.

Pure function, no queries. Feed it `get_campaigns_with_spend` and
`get_utm_campaign_catalogue` output.
"""

from dataclasses import asdict, dataclass, field
from typing import Any

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
    resolve_source,
)

logger = structlog.get_logger(__name__)

# Below this, one campaign flips the rate and the "winner" is noise.
MIN_CAMPAIGNS = 5

# Several adapters emit an empty `campaign_id`. Recommending id-matching when the
# ids aren't even populated is a guaranteed regression, so require most rows to
# actually carry one.
MIN_ID_COVERAGE = 0.8

# The suggested field must beat the current one by this much, and clear this floor
# on its own. Both are needed: +20pp is meaningless if it's 5% -> 25%.
MIN_SPEND_RATE_DELTA = 0.15
MIN_SUGGESTED_SPEND_RATE = 0.50

# "Apply all safe" thresholds — deliberately far above the suggest thresholds.
BATCH_MIN_DELTA = 0.30
BATCH_MIN_SUGGESTED_RATE = 0.70
BATCH_MIN_ID_COVERAGE = 0.95

# Confidence floor/ceiling. Never 1.0: this is a spend-weighted sample of the top
# 500 campaigns, not a proof.
MIN_CONFIDENCE = 0.55
MAX_CONFIDENCE = 0.95

# A name collision can't be resolved by arithmetic — two platforms genuinely share
# a campaign name, so name-matching is ambiguous however good its hit rate looks.
# Surfaced at low confidence so a human decides.
COLLISION_CONFIDENCE = 0.4

# Cap the examples embedded in a suggestion so the payload stays readable.
MAX_EXAMPLE_CAMPAIGNS = 5


@dataclass
class MatchRates:
    """How well one candidate field matches the UTM catalogue, by spend and by count.

    Spend is the metric that decides — a hundred matched $0 campaigns don't make up
    for one unmatched $40k campaign — but the count is reported alongside it because
    a big disagreement between the two is worth a human's attention.
    """

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
    # Spend on campaigns that don't match under the *current* field. What switching
    # is worth, and what `setup_plan` ranks on.
    spend_at_risk: float
    confidence: float
    safe_to_batch: bool
    reason: str
    # True when this came from a cross-platform name collision rather than from the
    # spend delta — the fix is the same, but the evidence and confidence differ.
    triggered_by_collision: bool = False
    colliding_integrations: list[str] = field(default_factory=list)
    # Campaigns still unmatched even after switching. These need their ad URLs
    # fixed; no mapping or preference change reaches them.
    still_unmatched_examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def suggest_campaign_field_preferences(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
    audit_results: list[CampaignAuditResult] | None = None,
) -> list[FieldPreferenceSuggestion]:
    """Per integration, compare name-matching vs id-matching and suggest the winner.

    `audit_results` is optional; without it the cross-platform name-collision
    override is skipped (the audit is what detects collisions).

    Manual `campaign_name_mappings` are deliberately excluded from both rates: they
    rewrite whichever field is preferred, so counting them would credit one side for
    something both sides get, and inflate the current field's apparent hit rate.

    Rates are scoped per integration by resolved `utm_source`, because the table groups
    cost and conversions on a `(campaign, source)` row key — a rate pooled across every
    platform would not describe what the dashboard actually attributes.
    """
    values_by_source = _utm_values_by_source(utm_events, mappings)
    collisions_by_source = _collisions_by_source(audit_results or [])

    suggestions: list[FieldPreferenceSuggestion] = []
    for source_name, group in _group_by_source(campaigns).items():
        suggestion = _suggest_for_integration(
            source_name=source_name,
            group=group,
            utm_campaign_values=values_by_source.get(source_name, set()),
            mappings=mappings,
            colliding_integrations=collisions_by_source.get(source_name, set()),
        )
        if suggestion is not None:
            suggestions.append(suggestion)

    # Highest-value switch first; `id` breaks ties so the output is stable.
    suggestions.sort(key=lambda s: (-s.spend_at_risk, s.integration))
    return suggestions


def _utm_values_by_source(
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
) -> dict[str, set[str]]:
    """Primary source -> the `utm_campaign` values that arrived tagged as that integration.

    Resolution goes through `resolve_source`, the same path the audit and the real query use,
    so a team custom mapping and a canonical default alias ('fb' -> meta) both count. A source
    that resolves to nothing is credited to nobody: in the table its traffic lands on its own
    row rather than the platform's, so counting it here would claim spend is attributed when
    it isn't. Such a platform reports a 0 rate, which is the truth — the fix it needs is a
    source mapping, which the plan suggests separately.
    """
    values: dict[str, set[str]] = {}
    for (utm_campaign, utm_source), _ in utm_events.items():
        if not utm_campaign:
            continue
        primary = resolve_source(utm_source.lower().strip(), mappings)
        values.setdefault(primary, set()).add(utm_campaign)
    return values


def _group_by_source(campaigns: list[Campaign]) -> dict[str, list[Campaign]]:
    grouped: dict[str, list[Campaign]] = {}
    for campaign in campaigns:
        source_name = campaign.source_name.lower().strip()
        if not source_name:
            continue
        grouped.setdefault(source_name, []).append(campaign)
    return grouped


def _collisions_by_source(audit_results: list[CampaignAuditResult]) -> dict[str, set[str]]:
    """source_name -> the other platforms it collides with on a campaign name."""
    collisions: dict[str, set[str]] = {}
    for result in audit_results:
        source_name = result.source_name.lower().strip()
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
        # A group only reaches here with spend > 0 (the query filters on it), but
        # guard anyway so a future caller can't divide by zero.
        spend_rate=(matched_spend / total_spend) if total_spend > 0 else 0.0,
        count_rate=(len(matched) / len(group)) if group else 0.0,
        matched_spend=matched_spend,
        matched_campaigns=len(matched),
    )


def _candidate_value(campaign: Campaign, match_field: str) -> str:
    raw = campaign.campaign_id if match_field == "campaign_id" else campaign.campaign_name
    # Empty never matches: `utm_campaign_values` excludes the empty string, but being
    # explicit keeps an empty id from silently counting as a hit if that changes.
    return raw.lower().strip()


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
        # Not a native integration we can write `campaign_field_preferences` for.
        logger.debug("campaign_field_suggester.unknown_source", source_name=source_name)
        return None

    if len(group) < MIN_CAMPAIGNS:
        return None

    current_field = get_match_field(source_name, mappings)

    # Matching on campaign_id is the cure for a name collision, so once a team is already on it
    # a collision is not evidence of anything to change. Without this the target field — derived
    # as "whatever isn't current" — came out as campaign_name, and the override below would
    # cheerfully suggest reintroducing the ambiguity it fired about.
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
        # Collision-only: the arithmetic doesn't favour switching, but name matching
        # is structurally ambiguous here. Never batched — a human should look.
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
    # Flag a big spend/count disagreement: it usually means one very expensive
    # campaign is carrying the verdict, which a reviewer should know.
    if abs(suggested.spend_rate - suggested.count_rate) >= 0.25:
        reason += (
            f" By campaign count the gap is smaller ({_pct(suggested.count_rate)} vs "
            f"{_pct(current.count_rate)}) — spend is concentrated in a few campaigns."
        )
    return reason


def _collision_reason(
    display_name: str,
    colliding: list[str],
    group: list[Campaign],
    utm_campaign_values: set[str],
) -> str:
    # Campaigns whose name IS in the catalogue — those are the ones a shared name can misattribute.
    # This read `not in` before, which counted the campaigns receiving no traffic at all and so
    # reported "0 campaign(s) worth $0.00" in precisely the collision case it exists to describe.
    affected = [c for c in group if _candidate_value(c, DEFAULT_MATCH_FIELD) in utm_campaign_values]
    others = ", ".join(colliding) or "another integration"
    return (
        f"{display_name} shares campaign names with {others}, so name matching can't tell them "
        f"apart — {len(affected)} campaign(s) worth {_money(sum(c.spend for c in affected))} are "
        "affected. Matching on campaign_id disambiguates, but only if the ad URLs put the id in "
        "utm_campaign."
    )
