"""The ICP fit score — encodes the Aug 2026 "who we build for" definition.

Definitional score, not an MRR predictor: default components are Traction (35), Capital (30),
AIPilled (15), HeadcountGrowth (10), SoftwareRelevance (10), summing to 100. AIPilled
awards its 15 points on a Harmonic AI signal, a detected wizard AI SDK stamp, or a
positive AI label. Spec:
https://posthog.com/handbook/growth/revops/icp-scoring. Weights and rules are owned by
RevOps and validated against a 382-company exemplar/customer set plus a 9.7k-signup
cohort. The scoring policy, curated tags, and investors live in versioned DB rows (see icp_lists.py).
Policy changes stamp a new `lists_version`; changes to the scoring engine bump SCORE_VERSION.

Written to its own `icp_fit_*` key family, deliberately NOT the legacy `icp_score` keys:
the live consumers of `icp_score` are threshold-tuned to the clay formula's -5..21 scale,
and the clay scorer (score.py) keeps writing them until each consumer migrates. The pair
of scores is by design — this one answers "does this company match who we build for?",
the planned expected-revenue score answers "what is this signup likely to be worth?".

Deterministic and I/O-free: consumes a Harmonic company payload in the provider's REST
shape (snake_case, precomputed horizon blocks). Archived GraphQL payloads are normalized
into that shape by harmonic_adapter.py. One deliberate divergence from the offline
reference implementation, ruled by the score owner (Mine, 2026-08-19): the
insufficient-data gate counts `investors` as a funding signal — matching the handbook
spec and the coverage counter — so an EXISTS_BUT_UNDISCLOSED raise with a named quality
investor scores capital 18 instead of falling out as insufficient_data.
"""

import re
import dataclasses
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.growth.backend.enrichment.icp_lists import CuratedLists, norm
from products.growth.backend.enrichment.scoring_rules import points_for

SCORE_VERSION = "v0.7"

STATUS_SCORED = "scored"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_NOT_FOUND = "not_found"
STATUS_DISQUALIFIED = "disqualified"

# Description regexes are formula, not curation: they change with SCORE_VERSION, so they
# live here rather than in the DB-backed lists.
SW_DESC = re.compile(
    r"\b(software|platform|api|saas|application|developer|sdk|automat\w+|dashboard|analytics|infrastructure|integrat\w+)\b",
    re.I,
)
AI_DESC = re.compile(
    r"\b(ai|artificial intelligence|machine learning|ml|llms?|genai|generative|copilot|neural network)\b", re.I
)

# Metadata flags only — deliberately not score inputs: consulting/agencies qualify on their
# merits (team + traffic), and .org non-profits include paying customers. Downstream teams
# route on the flags instead.
AGENCY_TAGS = frozenset({"consulting", "technology & digital consulting", "management & strategy consulting"})
NONPROFIT_TAGS = frozenset({"non-profit & community organizations"})

# Names at least this long may substring-match an observed investor name ("Sequoia Capital
# India" contains "sequoia capital"); shorter names/acronyms (GV, NEA, CRV) never
# substring-match, to avoid false hits inside unrelated words.
QUALITY_INVESTOR_SUBSTRING_MIN_CHARS = 8


@frozen
class AiPilledLabel:
    result_id: str
    fetch_id: str
    prompt_version: str
    prompt_hash: str


@dataclasses.dataclass(frozen=True)
class IcpFitResult:
    """One org's fit evaluation. score is None unless status is scored/disqualified."""

    status: str
    score: Optional[int] = None
    dq_reason: Optional[str] = None
    components: Optional[dict[str, int]] = None
    quality_investor: Optional[bool] = None
    data_coverage: Optional[int] = None
    low_confidence: Optional[bool] = None
    agency_flag: Optional[bool] = None
    nonprofit_flag: Optional[bool] = None
    wizard_ai_sdk: Optional[bool] = None
    ai_pilled_source: Optional[str] = None
    ai_pilled_label: AiPilledLabel | None = None
    ai_pilled_label_result_id: str | None = None
    version: str = SCORE_VERSION
    lists_version: Optional[str] = None


def is_quality_investor(
    observed_name: str, quality_names: frozenset[str], substring_min_chars: int = QUALITY_INVESTOR_SUBSTRING_MIN_CHARS
) -> bool:
    observed = norm(observed_name)
    if observed in quality_names:
        return True
    return any(name in observed for name in quality_names if len(name) >= substring_min_chars)


def _metric(payload: dict[str, Any], name: str, horizon: Optional[str] = None, field: str = "percent_change") -> Any:
    metric = (payload.get("traction_metrics") or {}).get(name)
    if not isinstance(metric, dict):
        return None
    if horizon is None:
        return metric.get("latest_metric_value")
    block = metric.get(horizon)
    return block.get(field) if isinstance(block, dict) else None


def score_company(
    payload: Optional[dict[str, Any]],
    *,
    lists: CuratedLists,
    role: Optional[str] = None,
    domain: Optional[str] = None,
    wizard_ai_sdk: bool = False,
    ai_pilled_label: AiPilledLabel | None = None,
) -> IcpFitResult:
    """Score one company payload (REST shape — see module docstring) against the fit rules.

    `role` is the signup's own role_at_organization answer (production-side, not in
    Harmonic) and `domain` is the signup email domain (for the .ai TLD signal) — never the
    payload's own website domain, which can be a different registrant.

    Statuses: a student signup is disqualified before the payload is even consulted (we
    know the answer regardless of enrichment); a missing/unmatched payload is not_found; a
    matched but empty-shell profile is insufficient_data (no numeric score — "no data yet"
    must never read as "evaluated and low"); everything else is scored 0–100.

    """
    if (role or "").strip().lower() == "student":
        return IcpFitResult(status=STATUS_DISQUALIFIED, score=0, dq_reason="role=student", lists_version=lists.version)

    if not payload or not isinstance(payload, dict):
        return IcpFitResult(status=STATUS_NOT_FOUND, lists_version=lists.version)

    tags = {norm(tag.get("display_value")) for tag in (payload.get("tags_v2") or []) if isinstance(tag, dict)}
    tag_types = {tag.get("type") for tag in (payload.get("tags_v2") or []) if isinstance(tag, dict)}

    # Hard DQ on company_type, not market tags: tags describe who a company SELLS TO
    # (education-market startups carry "Schools" tags), while company_type=SCHOOL marks
    # actual institutions.
    if payload.get("company_type") == "SCHOOL":
        return IcpFitResult(
            status=STATUS_DISQUALIFIED, score=0, dq_reason="company_type=SCHOOL", lists_version=lists.version
        )

    funding = payload.get("funding") or {}
    web_traffic = _metric(payload, "web_traffic", None)
    headcount = payload.get("headcount") or _metric(payload, "headcount", None)
    # Investors count as a funding signal here (matching the handbook and the coverage
    # counter below): a raise Harmonic knows only through its investor list is still a
    # profile worth scoring, not an empty shell.
    if not any(
        [headcount, funding.get("funding_total"), funding.get("investors"), payload.get("tags_v2"), web_traffic]
    ):
        return IcpFitResult(status=STATUS_INSUFFICIENT_DATA, lists_version=lists.version)

    rules = lists.rules
    traffic_change = _metric(payload, "web_traffic", rules.traction.growth_horizon)
    headcount_change = _metric(payload, "headcount", rules.headcount_growth.horizon)
    headcount_adds = _metric(payload, "headcount", rules.headcount_growth.horizon, "change")
    engineering_headcount = _metric(payload, "headcount_engineering", None)
    investors = [
        investor.get("name") or "" for investor in (funding.get("investors") or []) if isinstance(investor, dict)
    ]
    funding_total = funding.get("funding_total") or 0

    traffic_level = points_for(web_traffic or 0, rules.traction.traffic_levels)
    traffic_growth = 0
    if (web_traffic or 0) >= rules.traction.minimum_traffic_for_growth:
        traffic_growth = points_for(
            traffic_change or 0,
            rules.traction.growth_levels,
            rules.traction.positive_growth_points
            if (traffic_change or 0) > rules.traction.positive_growth_minimum
            else 0,
        )
    traction = traffic_level + traffic_growth

    quality = (
        "YC_BATCH" in tag_types  # matched on tag type so future batches qualify without a list update
        or bool(tags & lists.capital_quality)
        or any(
            is_quality_investor(investor, lists.quality_investors, rules.capital.investor_substring_min_chars)
            for investor in investors
        )
    )
    # EXISTS_BUT_UNDISCLOSED implies some funding exists -> base capital tier.
    undisclosed = payload.get("funding_attribute_null_status") == "EXISTS_BUT_UNDISCLOSED"
    capital = points_for(
        funding_total,
        rules.capital.funding_levels,
        rules.capital.funded_points if (funding_total > rules.capital.funded_minimum or undisclosed) else 0,
    )
    capital = min(rules.capital.cap, capital + (rules.capital.quality_bonus if quality else 0))

    description = payload.get("description") or payload.get("short_description") or ""
    has_ai_tag = bool(tags & lists.ai_positive)
    has_ai_description = bool(description and AI_DESC.search(description))
    has_ai_domain = (domain or "").endswith(".ai")
    harmonic_ai = has_ai_tag or has_ai_description or has_ai_domain
    ai_sources = [
        source
        for source, present in (
            ("harmonic", harmonic_ai),
            ("wizard", wizard_ai_sdk),
            ("llm", ai_pilled_label is not None),
        )
        if present and source in rules.ai_sources
    ]
    ai_pilled = rules.ai_points if ai_sources else 0
    ai_pilled_source = "both" if ai_sources == ["harmonic", "wizard"] else "+".join(ai_sources) or None

    headcount_growth = max(
        points_for(
            headcount_change or 0,
            rules.headcount_growth.levels,
            rules.headcount_growth.positive_growth_points
            if (headcount_change or 0) > rules.headcount_growth.positive_growth_minimum
            else 0,
        ),
        rules.headcount_growth.hires_points if (headcount_adds or 0) >= rules.headcount_growth.minimum_hires else 0,
    )

    software_relevance = (
        rules.software_relevance.engineering_points
        if (engineering_headcount or 0) > rules.software_relevance.engineering_minimum
        else rules.software_relevance.other_points
        if (tags & lists.software_positive or SW_DESC.search(description))
        else 0
    )

    coverage = sum(
        [
            bool(headcount and headcount >= rules.coverage.headcount_minimum),
            bool((web_traffic or 0) >= rules.coverage.traffic_minimum),
            bool(funding_total > rules.coverage.funding_minimum or investors),
            bool(payload.get("tags_v2")),
        ]
    )

    return IcpFitResult(
        status=STATUS_SCORED,
        score=traction + capital + ai_pilled + headcount_growth + software_relevance,
        components={
            "traction": traction,
            "capital": capital,
            "ai_pilled": ai_pilled,
            "headcount_growth": headcount_growth,
            "software_relevance": software_relevance,
        },
        quality_investor=quality,
        data_coverage=coverage,
        low_confidence=coverage <= rules.coverage.low_confidence_maximum,
        agency_flag=bool(tags & AGENCY_TAGS),
        nonprofit_flag=bool(tags & NONPROFIT_TAGS),
        wizard_ai_sdk=wizard_ai_sdk,
        ai_pilled_source=ai_pilled_source,
        ai_pilled_label=ai_pilled_label if "llm" in ai_sources else None,
        lists_version=lists.version,
    )
