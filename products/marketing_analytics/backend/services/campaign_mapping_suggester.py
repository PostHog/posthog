"""Suggest `campaign_name_mappings` entries for typo'd or lightly-mangled
`utm_campaign` values.

A campaign whose UTM tag is `sprng_sale_2024` while the platform calls it
`spring_sale_2024` shows up in the audit as "not linked" with no explanation. This
proposes the mapping that reconnects it.

READ THIS BEFORE TOUCHING THE THRESHOLDS. A false positive here silently
misattributes spend and nobody notices for months — it surfaces later as "our ROAS
numbers are wrong", by which time the mapping is ancient config nobody remembers
adding. That asymmetry (a miss costs one unlinked campaign, a false positive
corrupts a number people make decisions on) is why:

- the score cutoff is 88, not the helper's default 70;
- a near-tie between the top two candidates produces advice, not a guess;
- pairs that differ only by a period token are rejected outright, however high they
  score — `brand_us_q1` vs `brand_us_q2` scores ~96 on WRatio and is a *different
  campaign*. Without that guard this whole module is net-negative;
- a mapping is only ever offered alongside "fix the ad URL", which is the actual
  cure. The mapping is a band-aid over a tagging bug in the ad platform.

Pure function, no queries. Feed it `get_campaigns_with_spend` and
`get_utm_campaign_catalogue` output.
"""

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import structlog

from posthog.helpers.fuzzy_search import fuzzy_rank

from products.marketing_analytics.backend.services.native_integrations import (
    NATIVE_TO_KEY,
    display_name_for_key,
    native_for_primary_source,
)
from products.marketing_analytics.backend.services.types import Campaign, TeamMappings
from products.marketing_analytics.backend.services.utm_matching import (
    build_campaign_lookup,
    get_match_value,
    get_match_value_raw,
    group_campaigns_by_source,
    normalize_source_name,
    resolve_source,
)

logger = structlog.get_logger(__name__)

# Below this many events a config change isn't worth the risk of getting it wrong.
MIN_EVENT_COUNT = 25

# Only consider the top-N orphans by volume. Caps prompt/compute cost and keeps the
# long tail of one-off test tags out of the suggestions.
MAX_UNMATCHED_VALUES = 100

# Far above `fuzzy_search.DEFAULT_SCORE_CUTOFF` (70), which is tuned for
# human-in-the-loop search boxes rather than for writing config unattended.
SCORE_CUTOFF = 88.0

# When the runner-up is within this many points, the match is ambiguous — emit
# advice instead of picking.
MIN_MARGIN = 6.0

# Without a resolvable utm_source we have to search every integration's campaigns,
# so the bar goes up and batching is off.
UNSCOPED_SCORE_CUTOFF = 93.0

# "Apply all safe" needs near-certainty and a clear runner-up gap.
BATCH_SCORE = 95.0
BATCH_MARGIN = 15.0

# Ranking floor used while *measuring* the margin, distinct from the acceptance cutoffs above.
# A runner-up only makes the top candidate ambiguous if it is within MIN_MARGIN (or BATCH_MARGIN)
# of it, so anything further below the lowest cutoff than the widest margin can never change a
# verdict — but everything above that has to stay visible, or the near-tie it proves gets discarded
# before it can be counted.
MARGIN_FLOOR = SCORE_CUTOFF - BATCH_MARGIN

# How many candidates to keep per orphan. 3 is enough to measure the margin.
TOP_N_CANDIDATES = 3

# Extra candidates to rank before the period filter runs, so a quarterly family can't fill
# every slot and hide a real match underneath it. A campaign named per quarter yields at most
# four siblings, so four times the window clears the worst realistic case.
CANDIDATE_HEADROOM = 4

# Tokens that mean "same campaign family, different period/instance". A pair whose
# only differences are these is a sibling, not a typo.
_TOKEN_SPLIT = re.compile(r"[-_./\s+|:]+")
_MONTHS = frozenset(
    "jan feb mar apr may jun jul aug sep oct nov dec january february march april june "
    "july august september october november december".split()
)
_PERIOD_TOKEN = re.compile(r"^(?:q[1-4]|h[12]|fy\d{2,4}|wk?\d{1,2}|\d{4}q[1-4])$")

SuggestionMethod = Literal["fuzzy_exact_scope", "fuzzy_unscoped"]


@dataclass
class CampaignMappingProposal:
    """A concrete `campaign_name_mappings` entry to add."""

    # PascalCase `NativeMarketingSource` value — the key team config uses.
    integration: str
    integration_display_name: str
    # What the platform calls it, in the field this integration matches on. This is
    # the value that has to end up equal to `match_key` for the join to work.
    clean_name: str
    raw_utm_campaign: str
    event_count: int
    # Spend sitting on the platform campaign that currently has no events linked.
    campaign_spend: float
    score: float
    margin: float
    confidence: float
    safe_to_batch: bool
    method: SuggestionMethod
    reason: str
    # The dominant utm_source seen on the orphan, and what the ad URL should say.
    observed_utm_source: str
    expected_utm_campaign: str
    expected_utm_source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AmbiguousCampaign:
    """An orphan with several plausible matches. Deliberately not a proposal — the
    module refuses to guess when the runner-up is close."""

    raw_utm_campaign: str
    event_count: int
    observed_utm_source: str
    candidates: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""


@dataclass
class CampaignMappingSuggestions:
    proposals: list[CampaignMappingProposal] = field(default_factory=list)
    ambiguous: list[AmbiguousCampaign] = field(default_factory=list)
    # Orphans considered but matched nothing above the cutoff. These are the AI
    # layer's input: structurally-renamed campaigns edit distance can't reach.
    unresolved: list[AmbiguousCampaign] = field(default_factory=list)
    total_orphans: int = 0
    orphans_considered: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def suggest_campaign_name_mappings(
    campaigns: list[Campaign],
    utm_events: dict[tuple[str, str], int],
    mappings: TeamMappings,
    *,
    min_event_count: int = MIN_EVENT_COUNT,
    max_unmatched_values: int = MAX_UNMATCHED_VALUES,
) -> CampaignMappingSuggestions:
    """Propose `campaign_name_mappings` for orphaned `utm_campaign` values."""
    already_matched = set(build_campaign_lookup(campaigns, mappings))
    already_mapped = {raw for aliases in mappings.campaign_aliases.values() for raw in aliases}
    campaigns_by_source = group_campaigns_by_source(campaigns)
    # Every integration's match values, so we can tell "typo" from "collision".
    all_match_values = {
        get_match_value(campaign, mappings) for group in campaigns_by_source.values() for campaign in group
    }

    # Campaigns whose match value already shows up in the catalogue are linked and
    # working. Mapping an orphan onto one would pile a second campaign's traffic onto
    # a row that's already attributing correctly, so they're not valid targets.
    #
    # Keyed by resolved source, because "already receiving traffic" is per-platform: candidates are
    # scoped to one integration, so a global set let Meta's `brand` traffic disqualify Google's own
    # `brand` campaign — and cross-platform name reuse (brand / retargeting / prospecting) is the
    # norm for anyone running both. Lowercased because the lookup compares a lowercased candidate.
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

    result = CampaignMappingSuggestions(
        total_orphans=len(orphans),
        orphans_considered=len(considered),
        notes=notes,
    )
    # clean_name -> the utm_source already proposed for it, so two orphans arriving
    # from different platforms can't be merged under one clean name.
    claimed_clean_names: dict[str, str] = {}

    for orphan in considered:
        _classify(
            orphan=orphan,
            campaigns_by_source=campaigns_by_source,
            mappings=mappings,
            all_match_values=all_match_values,
            seen_by_source=seen_by_source,
            claimed_clean_names=claimed_clean_names,
            result=result,
        )

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
    """Unmatched `utm_campaign` values, with the utm_source they mostly arrive on.

    "Unmatched" is `build_campaign_lookup`'s definition, so this can never disagree
    with what the audit reports as linked.
    """
    totals: Counter[str] = Counter()
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    for (utm_campaign, utm_source), count in utm_events.items():
        if not utm_campaign or utm_campaign in excluded:
            continue
        totals[utm_campaign] += count
        by_source[utm_campaign][utm_source] += count

    orphans = []
    for raw, count in totals.most_common():
        sources = by_source[raw]
        # Ties broken by name so the output is deterministic across runs.
        dominant = min(sources.most_common(), key=lambda item: (-item[1], item[0]))[0] if sources else ""
        orphans.append(_Orphan(raw_utm_campaign=raw, event_count=count, dominant_utm_source=dominant))
    return orphans


def _tokens(value: str) -> list[str]:
    return [token for token in _TOKEN_SPLIT.split(value.lower()) if token]


def _is_period_token(token: str) -> bool:
    return token.isdigit() or bool(_PERIOD_TOKEN.match(token)) or token in _MONTHS


def differs_only_by_period(a: str, b: str) -> bool:
    """True when the two names differ *only* in period/instance tokens.

    `brand_us_q1` vs `brand_us_q2`, `sale_2024` vs `sale_2025`, `promo` vs
    `promo_march` — same family, different run. Mapping one onto the other merges
    two campaigns' spend, which is worse than leaving one unlinked.

    Identical token multisets return False: that's a separator or ordering
    difference, i.e. a real match.

    Accepted false negative: this also rejects genuine typos whose only difference
    is numeric — `spring_sale_202` vs `spring_sale_2024` (a truncation) is
    structurally identical to `sale_2024` vs `sale_2025` (a sibling), and nothing
    in the strings distinguishes them. Refusing both is the safe direction, and it
    matters most for integrations matching on `campaign_id`, where a "near-miss" id
    is usually just *another campaign's real id*. Those land in `unresolved`, which
    is the AI layer's input — semantics can separate them, edit distance cannot.
    """
    diff = (Counter(_tokens(a)) - Counter(_tokens(b))) + (Counter(_tokens(b)) - Counter(_tokens(a)))
    return bool(diff) and all(_is_period_token(token) for token in diff.elements())


def _classify(
    *,
    orphan: _Orphan,
    campaigns_by_source: dict[str, list[Campaign]],
    mappings: TeamMappings,
    all_match_values: set[str],
    seen_by_source: dict[str, set[str]],
    claimed_clean_names: dict[str, str],
    result: CampaignMappingSuggestions,
) -> None:
    # A value that exactly equals some integration's match value isn't a typo, it's a
    # cross-platform collision — campaign_field_suggester's problem, not ours.
    if orphan.raw_utm_campaign in all_match_values:
        return

    scoped_source = resolve_source(orphan.dominant_utm_source, mappings)
    scoped_group = campaigns_by_source.get(scoped_source)

    if scoped_group:
        candidates, method, cutoff = scoped_group, "fuzzy_exact_scope", SCORE_CUTOFF
    else:
        # utm_source doesn't resolve to a platform we have spend for, so we can't
        # narrow the search. Raise the bar and refuse to batch.
        candidates = [c for group in campaigns_by_source.values() for c in group]
        method, cutoff = "fuzzy_unscoped", UNSCOPED_SCORE_CUTOFF

    if not candidates:
        return

    # Unscoped search spans every platform, so no single source's catalogue describes "already
    # attributing" — fall back to the union there rather than picking one arbitrarily.
    seen = (
        seen_by_source.get(scoped_source, set())
        if scoped_group
        else {value for values in seen_by_source.values() for value in values}
    )

    by_value: dict[str, Campaign] = {}
    for campaign in candidates:
        value = get_match_value_raw(campaign, mappings)
        if not value or value.lower() in seen:
            # Empty, or already receiving traffic under its own name — not an orphan.
            continue
        # Keep the highest-spend campaign when several share a match value.
        if value not in by_value or campaign.spend > by_value[value].spend:
            by_value[value] = campaign

    # Ranked WITHOUT the acceptance cutoff, because the cutoff and the margin answer different
    # questions. The cutoff decides whether the top candidate is close enough to propose at all;
    # the margin decides whether a *second* candidate makes that proposal a guess. Filtering by
    # cutoff first discards exactly the runner-ups that prove ambiguity — a 90.9 top next to an
    # 85.5 runner-up looked like a lone match with margin 100 when the real margin is 5.4.
    #
    # Headroom, and truncation only after the period filter: taking the top N first would let a
    # quarterly family — which scores ~96 across every sibling — fill all N slots and bury a
    # genuine typo match below them, reporting the orphan as unresolvable.
    ranked = fuzzy_rank(
        orphan.raw_utm_campaign,
        list(by_value),
        score_cutoff=MARGIN_FLOOR,
        limit=TOP_N_CANDIDATES * CANDIDATE_HEADROOM,
    )
    # Drop period-siblings before measuring the margin: otherwise `brand_q2` sitting
    # at 96 next to `brand_q1` at 96 reads as "ambiguous" when it's simply not a match.
    ranked = [(value, score) for value, score in ranked if not differs_only_by_period(orphan.raw_utm_campaign, value)]
    ranked = ranked[:TOP_N_CANDIDATES]

    # The cutoff is applied here instead: a top candidate below it is no match, whatever trails it.
    if ranked and ranked[0][1] < cutoff:
        ranked = []

    if not ranked:
        result.unresolved.append(
            AmbiguousCampaign(
                raw_utm_campaign=orphan.raw_utm_campaign,
                event_count=orphan.event_count,
                observed_utm_source=orphan.dominant_utm_source,
                reason=(
                    f"No platform campaign is within {cutoff:.0f}% similarity of "
                    f"'{orphan.raw_utm_campaign}'. Either the campaign was renamed beyond what edit "
                    "distance can match, or this traffic isn't from a connected ad platform."
                ),
            )
        )
        return

    top_value, top_score = ranked[0]
    margin = top_score - ranked[1][1] if len(ranked) > 1 else 100.0

    if margin < MIN_MARGIN:
        result.ambiguous.append(
            AmbiguousCampaign(
                raw_utm_campaign=orphan.raw_utm_campaign,
                event_count=orphan.event_count,
                observed_utm_source=orphan.dominant_utm_source,
                candidates=ranked,
                reason=(
                    f"'{orphan.raw_utm_campaign}' is a near-equal match for "
                    f"{' and '.join(value for value, _ in ranked[:2])} "
                    f"({ranked[0][1]:.0f}% vs {ranked[1][1]:.0f}%). Picking one could attribute this "
                    "campaign's traffic to the wrong ad spend, so it needs a human."
                ),
            )
        )
        return

    campaign = by_value[top_value]
    native = native_for_primary_source(campaign.source_name)
    if native is None:
        return

    # Never let two different platforms' orphans collapse into one clean name.
    claimed_by = claimed_clean_names.get(top_value)
    if claimed_by is not None and claimed_by != orphan.dominant_utm_source:
        logger.debug(
            "campaign_mapping_suggester.clean_name_already_claimed",
            clean_name=top_value,
            claimed_by=claimed_by,
            skipped=orphan.raw_utm_campaign,
        )
        return
    claimed_clean_names[top_value] = orphan.dominant_utm_source

    expected_utm_source = normalize_source_name(campaign.source_name)
    display_name = display_name_for_key(NATIVE_TO_KEY[native])
    result.proposals.append(
        CampaignMappingProposal(
            integration=native.value,
            integration_display_name=display_name,
            clean_name=top_value,
            raw_utm_campaign=orphan.raw_utm_campaign,
            event_count=orphan.event_count,
            campaign_spend=campaign.spend,
            score=round(top_score, 1),
            margin=round(margin, 1),
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
    )


def _confidence(score: float) -> float:
    """Map the score band above the cutoff onto 0.5-0.9.

    Never higher: a string-similarity match is evidence, not proof, and the ceiling
    is what keeps these out of any UI that auto-applies high-confidence rows.
    """
    span = max(100.0 - SCORE_CUTOFF, 1e-9)
    return round(min(0.5 + ((score - SCORE_CUTOFF) / span) * 0.4, 0.9), 2)
