"""Propose `campaign_name_mappings` for typo'd `utm_campaign` values.

`sprng_sale_2024` against a platform campaign named `spring_sale_2024` shows up in the
audit as "not linked" with no explanation. This proposes the mapping that reconnects it.

BEFORE LOOSENING ANYTHING HERE: the errors are not symmetric. A miss costs one unlinked
campaign; a false positive misattributes spend and surfaces months later as "our ROAS is
wrong". The thresholds, the near-tie refusals and the period guard all pay for that.

Pure function. Feed it `get_campaigns_with_spend` and `get_utm_campaign_catalogue` output.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

import structlog

from posthog.schema import NativeMarketingSource

from posthog.helpers.fuzzy_search import fuzzy_rank

from products.marketing_analytics.backend.services.native_integrations import (
    NATIVE_TO_KEY,
    display_name_for_key,
    native_for_primary_source,
)
from products.marketing_analytics.backend.services.types import Campaign, TeamMappings
from products.marketing_analytics.backend.services.utm_matching import (
    build_campaign_lookup,
    get_match_value_raw,
    group_campaigns_by_source,
    normalize_source_name,
    resolve_source,
)

logger = structlog.get_logger(__name__)

MIN_EVENT_COUNT = 25
MAX_UNMATCHED_VALUES = 100

# Longer than any real campaign name — Google Ads caps them at 128 characters and the rest are in
# that range — so anything past this is junk that can't be a typo of a real name. It is also the
# only bound on the fuzzy pass's cost: `utm_campaign` arrives from an event property with no length
# limit, and 100 orphans against 500 candidates takes 60ms at realistic lengths and 5 minutes when
# both sides are 20k characters.
MAX_VALUE_LENGTH = 200

# 88, not the helper's default 70: that one is tuned for a search box with a human reading it.
SCORE_CUTOFF = 88.0
MIN_MARGIN = 6.0
UNSCOPED_SCORE_CUTOFF = 93.0
BATCH_SCORE = 95.0
BATCH_MARGIN = 15.0

# Floor for measuring the margin, not for accepting a match: a runner-up below this can't change
# a verdict, one above it must stay visible.
MARGIN_FLOOR = SCORE_CUTOFF - BATCH_MARGIN

TOP_N_CANDIDATES = 3
# Slack so a quarterly family, alike across every sibling, can't fill every slot pre-filter.
CANDIDATE_HEADROOM = 4

_TOKEN_SPLIT = re.compile(r"[-_./\s+|:]+")
_MONTHS = frozenset(
    "jan feb mar apr may jun jul aug sep oct nov dec january february march april june "
    "july august september october november december".split()
)
_PERIOD_TOKEN = re.compile(r"^(?:q[1-4]|h[12]|fy\d{2,4}|wk?\d{1,2}|\d{4}q[1-4])$")

SuggestionMethod = Literal["fuzzy_exact_scope", "fuzzy_unscoped"]


@dataclass
class CampaignMappingProposal:
    # PascalCase `NativeMarketingSource` value, i.e. the key team config uses.
    integration: str
    integration_display_name: str
    # Must equal `match_key`, so it follows `campaign_field_preferences` — a name proposed to an
    # id-matching integration writes a mapping that never joins.
    clean_name: str
    raw_utm_campaign: str
    event_count: int
    campaign_spend: float
    score: float
    confidence: float
    safe_to_batch: bool
    method: SuggestionMethod
    reason: str
    observed_utm_source: str
    expected_utm_campaign: str
    expected_utm_source: str


@dataclass
class AmbiguousCampaign:
    raw_utm_campaign: str
    event_count: int
    observed_utm_source: str
    candidates: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""


@dataclass
class CampaignMappingSuggestions:
    proposals: list[CampaignMappingProposal] = field(default_factory=list)
    ambiguous: list[AmbiguousCampaign] = field(default_factory=list)
    unresolved: list[AmbiguousCampaign] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def suggest_campaign_name_mappings(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
    *,
    min_event_count: int = MIN_EVENT_COUNT,
    max_unmatched_values: int = MAX_UNMATCHED_VALUES,
) -> CampaignMappingSuggestions:
    already_matched = set(build_campaign_lookup(campaigns, mappings))
    already_mapped = {raw for aliases in mappings.campaign_aliases.values() for raw in aliases}
    campaigns_by_source = group_campaigns_by_source(campaigns)

    # Per platform, not global: name reuse is the norm, and a global set let Meta's `brand`
    # traffic disqualify Google's own `brand` campaign.
    seen_by_source: dict[str, set[str]] = {}
    for utm_campaign, utm_source in utm_events:
        if not utm_campaign:
            continue
        seen_by_source.setdefault(resolve_source(normalize_source_name(utm_source), mappings), set()).add(
            utm_campaign.lower()
        )

    orphans = _orphans(utm_events, already_matched | already_mapped)
    considered = [o for o in orphans if o.event_count >= min_event_count][:max_unmatched_values]

    notes: list[str] = []
    if len(orphans) > len(considered):
        notes.append(
            f"{len(orphans) - len(considered)} orphaned utm_campaign value(s) were skipped: below "
            f"{min_event_count} events or beyond the top {max_unmatched_values} by volume."
        )

    result = CampaignMappingSuggestions(notes=notes)
    # clean_name -> the utm_source already proposed for it, so two platforms' orphans can't merge.
    claimed_clean_names: dict[str, str] = {}

    for orphan in considered:
        verdict = _classify(
            orphan=orphan,
            campaigns_by_source=campaigns_by_source,
            mappings=mappings,
            seen_by_source=seen_by_source,
            claimed_clean_names=claimed_clean_names,
        )
        match verdict:
            case CampaignMappingProposal():
                claimed_clean_names[verdict.clean_name] = verdict.observed_utm_source
                result.proposals.append(verdict)
            case _Ambiguous(entry):
                result.ambiguous.append(entry)
            case _Unresolved(entry):
                result.unresolved.append(entry)

    result.proposals.sort(key=lambda p: (-p.campaign_spend, -p.event_count, p.raw_utm_campaign))
    result.ambiguous.sort(key=lambda a: -a.event_count)
    result.unresolved.sort(key=lambda a: -a.event_count)
    return result


@dataclass
class _Orphan:
    raw_utm_campaign: str
    event_count: int
    dominant_utm_source: str


def _orphans(utm_events: dict[tuple[str, str], int], excluded: set[str]) -> list[_Orphan]:
    """Unmatched values with the utm_source they mostly arrive on. "Unmatched" is
    `build_campaign_lookup`'s definition, so this can't disagree with the audit."""
    totals: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    for (utm_campaign, utm_source), count in utm_events.items():
        if not utm_campaign or len(utm_campaign) > MAX_VALUE_LENGTH or utm_campaign in excluded:
            continue
        totals[utm_campaign] += count
        by_source[utm_campaign][utm_source] += count

    orphans = []
    for raw, count in totals.most_common():
        sources = by_source[raw]
        dominant = min(sources.most_common(), key=lambda item: (-item[1], item[0]))[0] if sources else ""
        orphans.append(_Orphan(raw_utm_campaign=raw, event_count=count, dominant_utm_source=dominant))
    return orphans


def _tokens(value: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(value.lower()) if token]


def _is_period_token(token: str) -> bool:
    return token.isdigit() or bool(_PERIOD_TOKEN.match(token)) or token in _MONTHS


def differs_only_by_period(a: str, b: str) -> bool:
    """True when the two names differ *only* in period/instance tokens.

    `brand_us_q1` vs `brand_us_q2` is a sibling, not a typo. An identical multiset is a separator
    or ordering difference, i.e. a real match, so it returns False. Accepted false negative: a
    truncation like `spring_sale_202` is indistinguishable from a sibling, so both are refused.
    """
    diff = (Counter(_tokens(a)) - Counter(_tokens(b))) + (Counter(_tokens(b)) - Counter(_tokens(a)))
    return bool(diff) and all(_is_period_token(token) for token in diff.elements())


class _Target(NamedTuple):
    campaign: Campaign
    native: NativeMarketingSource


class _Ambiguous(NamedTuple):
    """Several plausible targets. Distinct from `_Unresolved` only in which list it lands in."""

    entry: AmbiguousCampaign


class _Unresolved(NamedTuple):
    entry: AmbiguousCampaign


_Verdict = CampaignMappingProposal | _Ambiguous | _Unresolved | None


def _refuse(orphan: _Orphan, reason: str, candidates: list[tuple[str, float]] | None = None) -> AmbiguousCampaign:
    return AmbiguousCampaign(
        raw_utm_campaign=orphan.raw_utm_campaign,
        event_count=orphan.event_count,
        observed_utm_source=orphan.dominant_utm_source,
        candidates=candidates or [],
        reason=reason,
    )


def _classify(
    *,
    orphan: _Orphan,
    campaigns_by_source: dict[str, list[Campaign]],
    mappings: TeamMappings,
    seen_by_source: dict[str, set[str]],
    claimed_clean_names: Mapping[str, str],
) -> _Verdict:
    """Decide one orphan's fate. Returns the verdict rather than filing it, so the caller owns
    both accumulators — `claimed_clean_names` is read here and written only there."""
    scoped_source = resolve_source(orphan.dominant_utm_source, mappings)
    scoped_group = campaigns_by_source.get(scoped_source)

    if scoped_group:
        candidates, method, cutoff = scoped_group, "fuzzy_exact_scope", SCORE_CUTOFF
    else:
        candidates = [c for group in campaigns_by_source.values() for c in group]
        method, cutoff = "fuzzy_unscoped", UNSCOPED_SCORE_CUTOFF

    if not candidates:
        return None

    seen = (
        seen_by_source.get(scoped_source, set())
        if scoped_group
        else {value for values in seen_by_source.values() for value in values}
    )

    by_value: dict[str, _Target] = {}
    # Which platforms carry each value; only ever >1 unscoped. See the guard on `top_value`.
    natives_by_value: dict[str, set[str]] = {}
    for campaign in candidates:
        value = get_match_value_raw(campaign, mappings)
        if not value or len(value) > MAX_VALUE_LENGTH or value.lower() in seen:
            continue
        native = native_for_primary_source(campaign.source_name)
        if native is None:
            continue
        natives_by_value.setdefault(value, set()).add(native.value)
        if value not in by_value or campaign.spend > by_value[value].campaign.spend:
            by_value[value] = _Target(campaign, native)

    # MARGIN_FLOOR, not `cutoff`: a sub-cutoff runner-up still proves ambiguity, and filtering it
    # out here made a 90.9-vs-85.5 pair read as a lone match at margin 100.
    ranked = fuzzy_rank(
        orphan.raw_utm_campaign,
        list(by_value),
        score_cutoff=MARGIN_FLOOR,
        limit=TOP_N_CANDIDATES * CANDIDATE_HEADROOM,
    )
    # Split before the margin, or `brand_q2` beside `brand_q1` reads as ambiguous instead of no
    # match. The siblings are kept to explain the refusal, not to rank.
    kept: list[tuple[str, float]] = []
    siblings: list[str] = []
    for value, score in ranked:
        if differs_only_by_period(orphan.raw_utm_campaign, value):
            siblings.append(value)
        else:
            kept.append((value, score))
    ranked = kept[:TOP_N_CANDIDATES]

    if ranked and ranked[0][1] < cutoff:
        ranked = []

    if not ranked:
        # Naming the sibling matters: without it the reason claims nothing was close, while the
        # campaign the user is looking at sits well above the cutoff and was refused on purpose.
        if siblings:
            reason = (
                f"'{orphan.raw_utm_campaign}' closely matches {siblings[0]}, but the two differ only "
                "in the period they name, so they are different runs of one campaign. Mapping them "
                "together would merge their spend."
            )
        else:
            reason = (
                f"No platform campaign is within {cutoff:.0f}% similarity of "
                f"'{orphan.raw_utm_campaign}'. Either the campaign was renamed beyond what edit "
                "distance can match, or this traffic isn't from a connected ad platform."
            )
        return _Unresolved(_refuse(orphan, reason))

    top_value, top_score = ranked[0]
    margin = top_score - ranked[1][1] if len(ranked) > 1 else 100.0

    if margin < MIN_MARGIN:
        return _Ambiguous(
            _refuse(
                orphan,
                f"'{orphan.raw_utm_campaign}' is a near-equal match for "
                f"{' and '.join(value for value, _ in ranked[:2])} "
                f"({ranked[0][1]:.0f}% vs {ranked[1][1]:.0f}%). Picking one could attribute this "
                "campaign's traffic to the wrong ad spend, so it needs a human.",
                ranked,
            )
        )

    # A name two platforms both run ties *at* the top, so the margin reads 100 and the spend
    # tiebreak would silently pick the platform. Unreachable when scoped.
    contenders = natives_by_value.get(top_value, set())
    if len(contenders) > 1:
        return _Ambiguous(
            _refuse(
                orphan,
                f"'{top_value}' is a campaign on {' and '.join(sorted(contenders))}, and "
                f"utm_source='{orphan.dominant_utm_source}' doesn't say which one this traffic "
                "belongs to. Mapping it to the wrong platform would move real spend, so it "
                "needs a human.",
                ranked,
            )
        )

    campaign, native = by_value[top_value]

    claimed_by = claimed_clean_names.get(top_value)
    if claimed_by is not None and claimed_by != orphan.dominant_utm_source:
        logger.debug(
            "campaign_mapping_suggester.clean_name_already_claimed",
            clean_name=top_value,
            claimed_by=claimed_by,
            skipped=orphan.raw_utm_campaign,
        )
        return None

    expected_utm_source = normalize_source_name(campaign.source_name)
    display_name = display_name_for_key(NATIVE_TO_KEY[native])
    return CampaignMappingProposal(
        integration=native.value,
        integration_display_name=display_name,
        clean_name=top_value,
        raw_utm_campaign=orphan.raw_utm_campaign,
        event_count=orphan.event_count,
        campaign_spend=campaign.spend,
        score=round(top_score, 1),
        confidence=_confidence(top_score),
        safe_to_batch=(method == "fuzzy_exact_scope" and top_score >= BATCH_SCORE and margin >= BATCH_MARGIN),
        method=method,  # type: ignore[arg-type]
        reason=(
            f"'{orphan.raw_utm_campaign}' — {orphan.event_count:,} events, {top_score:.0f}% similar to "
            f"{display_name} campaign '{top_value}', which has {campaign.spend:,.0f} spend and no "
            "matched events."
        ),
        observed_utm_source=orphan.dominant_utm_source,
        expected_utm_campaign=top_value,
        expected_utm_source=expected_utm_source,
    )


def _confidence(score: float) -> float:
    """Score band above the cutoff mapped onto 0.5-0.9. The ceiling keeps these rows out of any
    UI that auto-applies on confidence."""
    span = max(100.0 - SCORE_CUTOFF, 1e-9)
    return round(min(0.5 + ((score - SCORE_CUTOFF) / span) * 0.4, 0.9), 2)
