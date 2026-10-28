import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Literal

import tldextract

from posthog.schema import MarketingAnalyticsRecommendation, MarketingAnalyticsRecommendationRule

from posthog.dataclasses import frozen

PER_RULE_LIMIT = 10
# Share of impressions that become clicks once a page reaches the top 3 organic results. A rough industry figure.
TOP3_CTR = 0.15
# Below this, someone else's ad often takes the first spot on your own brand searches.
BRAND_DEFENSE_ABSOLUTE_TOP = 0.9
INACTIVE_STATUSES = frozenset({"PAUSED", "ENDED", "REMOVED"})
POLICY_REASONS = frozenset(
    {
        "HAS_ADS_LIMITED_BY_POLICY",
        "HAS_ADS_DISAPPROVED",
        # Performance Max reports policy limits on its asset groups instead of its ads.
        "HAS_ASSET_GROUPS_LIMITED_BY_POLICY",
        "HAS_ASSET_GROUPS_DISAPPROVED",
    }
)
# Modifiers that match almost any search, so they say nothing about whether a query fits the account.
GENERIC_WORDS = frozenset(
    {
        "app",
        "apps",
        "best",
        "free",
        "online",
        "open",
        "platform",
        "site",
        "software",
        "source",
        "tool",
        "tools",
        "top",
        "web",
        "website",
    }
)
# Share of the searches mentioning a name that must be comparisons for it to count as a competitor.
COMPETITOR_COMPARISON_SHARE = 0.07
COMPARISON = re.compile(r"(alternatives?|competitors?|(^| )vs\.?( |$))")
COMPETITOR_PATTERNS = (
    re.compile(r"^([a-z0-9.-]+) (?:alternatives?|competitors?|vs\.?)( |$)"),
    re.compile(r"(?:alternatives? to|vs\.?) ([a-z0-9.-]+)"),
)
DOMAIN_SUFFIX = re.compile(r"\.(com|io|co|ai|app|net|org)$")
SITE_HOST = re.compile(r"^(?:sc-domain:|https?://)([a-z0-9.-]+)")
MIN_BRAND_LENGTH = 3
# The bundled public suffix snapshot, so parsing a site never fetches the list over the network.
DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)

Direction = Literal["save", "gain", "invest", "keep"]
# Google Ads KeywordMatchType values, for tables that stored the enum number.
MATCH_TYPES = {"2": "EXACT", "3": "PHRASE", "4": "BROAD"}


@frozen
class CampaignStats:
    id: str
    name: str
    channel_type: str | None
    primary_status: str | None
    status_reasons: tuple[str, ...]
    daily_budget: float | None
    recommended_daily_budget: float | None
    cost: float
    conversions: float
    impression_share: float | None
    lost_to_budget: float | None
    lost_to_rank: float | None
    budget_id: str | None = None


@frozen
class SearchTermStats:
    term: str
    campaign_id: str
    clicks: float
    impressions: float
    cost: float
    conversions: float
    status: str
    absolute_top_percentage: float | None = None


@frozen
class OrganicQueryStats:
    query: str
    clicks: float
    impressions: float
    position: float


@frozen
class TermKeywordStats:
    term: str
    keyword: str
    match_type: str
    cost: float


@frozen
class RecommendationInputs:
    campaigns: tuple[CampaignStats, ...]
    search_terms: tuple[SearchTermStats, ...]
    organic_queries: tuple[OrganicQueryStats, ...]
    site_urls: tuple[str, ...]
    currency: str | None
    days: int
    term_keywords: tuple[TermKeywordStats, ...] = ()


@frozen
class _Term:
    term: str
    clicks: float
    cost: float
    conversions: float
    status: str
    top_campaign_id: str
    organic: OrganicQueryStats | None
    absolute_top: float | None


@frozen
class _Spend:
    cost: float
    conversions: float


@frozen
class _BrandSpend:
    cost: float
    conversions: float
    top_term: str


def _site_brand(site_url: str) -> str | None:
    match = SITE_HOST.match(site_url.lower())
    if not match:
        return None
    # A URL-prefix property can be app.example.com or blog.example.com, so the brand is the registrable label.
    brand = DOMAIN_PARTS(match.group(1).strip(".")).domain
    return brand if len(brand) >= MIN_BRAND_LENGTH else None


def brands_from_site_urls(site_urls: Iterable[str]) -> frozenset[str]:
    return frozenset(brand for url in site_urls if (brand := _site_brand(url)))


def _merge_organic(queries: Iterable[OrganicQueryStats]) -> dict[str, OrganicQueryStats]:
    merged: dict[str, OrganicQueryStats] = {}
    for query in queries:
        current = merged.get(query.query)
        if current is None:
            merged[query.query] = query
            continue
        impressions = current.impressions + query.impressions
        merged[query.query] = OrganicQueryStats(
            query=query.query,
            clicks=current.clicks + query.clicks,
            impressions=impressions,
            position=(current.position * current.impressions + query.position * query.impressions) / impressions
            if impressions
            else current.position,
        )
    return merged


def recommend(inputs: RecommendationInputs) -> list[MarketingAnalyticsRecommendation]:
    return _Recommender(inputs).run()


class _Recommender:
    def __init__(self, inputs: RecommendationInputs) -> None:
        self.inputs = inputs
        self.per_month = 30 / max(inputs.days, 1)
        self.brands = brands_from_site_urls(inputs.site_urls)
        self.campaigns = {campaign.id: campaign for campaign in inputs.campaigns}
        self.organic = _merge_organic(inputs.organic_queries)
        self.term_cost_by_campaign: dict[str, float] = defaultdict(float)
        for row in inputs.search_terms:
            self.term_cost_by_campaign[row.campaign_id] += row.cost
        self.terms = self._aggregate_terms()
        self.brand_terms = {term.term for term in self.terms.values() if self._is_brand(term)}
        self.top_keyword: dict[str, TermKeywordStats] = {}
        for keyword_row in inputs.term_keywords:
            current = self.top_keyword.get(keyword_row.term)
            if current is None or keyword_row.cost > current.cost:
                self.top_keyword[keyword_row.term] = keyword_row

    def run(self) -> list[MarketingAnalyticsRecommendation]:
        campaign_rules = sorted(self._campaign_rules(), key=lambda rec: -(rec.impact or 0))
        return campaign_rules + self._search_term_rules()

    # Campaign rules

    def _campaign_rules(self) -> list[MarketingAnalyticsRecommendation]:
        recommendations: list[MarketingAnalyticsRecommendation] = []
        brand_spend = self._brand_spend_by_campaign()
        nonbrand = {
            campaign.id: self._nonbrand_totals(campaign, brand_spend.get(campaign.id))
            for campaign in self.campaigns.values()
        }
        search_campaigns = [
            campaign
            for campaign in self.campaigns.values()
            if campaign.channel_type == "SEARCH" and not self._is_brand_campaign(campaign, brand_spend)
        ]
        nonbrand_cost = sum(nonbrand[campaign.id].cost for campaign in search_campaigns)
        nonbrand_conversions = sum(nonbrand[campaign.id].conversions for campaign in search_campaigns)
        nonbrand_cpa = nonbrand_cost / nonbrand_conversions if nonbrand_conversions else None
        search_cost = sum(campaign.cost for campaign in self.campaigns.values() if campaign.channel_type == "SEARCH")

        constrained_budgets: set[str] = set()
        for campaign in self.campaigns.values():
            if campaign.primary_status in INACTIVE_STATUSES:
                continue
            budget = self._budget_constrained(campaign)
            # Campaigns that share a budget each report it as constrained, so one row covers the shared budget.
            if budget and not (campaign.budget_id and campaign.budget_id in constrained_budgets):
                recommendations.append(budget)
                if campaign.budget_id:
                    constrained_budgets.add(campaign.budget_id)
            if POLICY_REASONS.intersection(campaign.status_reasons):
                recommendations.append(
                    self._recommendation(
                        MarketingAnalyticsRecommendationRule.POLICY_LIMITED,
                        "campaign",
                        campaign.name,
                        "Check the affected ads in Policy manager",
                        "Some ads or asset groups are limited or disapproved by Google policy, which cuts the campaign's reach.",
                        None,
                        "gain",
                        "measured",
                    )
                )

        has_brand_campaign = any(self._is_brand_campaign(c, brand_spend) for c in self.campaigns.values())
        for campaign in self.campaigns.values():
            if campaign.channel_type != "PERFORMANCE_MAX" or campaign.primary_status in INACTIVE_STATUSES:
                continue
            leak = brand_spend.get(campaign.id)
            if leak and leak.cost >= 0.05 * max(self._term_cost(campaign.id), 1):
                recommendations.append(self._brand_leak(campaign, leak, has_brand_campaign))
            if campaign.conversions > 0 and (campaign.lost_to_rank or 0) >= 0.4:
                recommendations.append(self._performance_max_rank(campaign))

        for campaign in search_campaigns:
            if campaign.primary_status in INACTIVE_STATUSES:
                continue
            leak = brand_spend.get(campaign.id)
            if leak and leak.cost >= 0.05 * max(self._term_cost(campaign.id), 1):
                recommendations.append(self._brand_leak(campaign, leak, has_brand_campaign))
            totals = nonbrand[campaign.id]
            cost, conversions = totals.cost, totals.conversions
            cpa = cost / conversions if conversions else None
            lost = (campaign.lost_to_budget or 0) + (campaign.lost_to_rank or 0)
            if nonbrand_cpa and cpa and conversions >= 5 and cpa <= nonbrand_cpa and lost >= 0.4:
                recommendations.append(self._scale(campaign, cpa, nonbrand_cpa, lost))
            elif (
                nonbrand_cpa
                and search_cost
                and campaign.cost >= 0.05 * search_cost
                and (cpa is None or cpa >= 3 * nonbrand_cpa)
            ):
                recommendations.append(self._review(campaign, cpa, nonbrand_cpa))
        return recommendations

    def _budget_constrained(self, campaign: CampaignStats) -> MarketingAnalyticsRecommendation | None:
        budget, recommended = campaign.daily_budget, campaign.recommended_daily_budget
        if (
            "BUDGET_CONSTRAINED" not in campaign.status_reasons
            or not budget
            or not recommended
            or recommended <= budget
        ):
            return None
        lost = (
            f"{campaign.lost_to_budget:.0%} of eligible impressions are lost because the budget runs out. "
            if campaign.lost_to_budget
            else ""
        )
        return self._recommendation(
            MarketingAnalyticsRecommendationRule.BUDGET_CONSTRAINED,
            "campaign",
            campaign.name,
            f"Raise the daily budget from {self._money(budget)} to {self._money(recommended)}",
            f"Limited by budget. {lost}{self._money(recommended)} a day is Google's recommended budget.",
            (recommended - budget) * 30,
            "invest",
            "estimated",
        )

    def _brand_leak(
        self, campaign: CampaignStats, leak: _BrandSpend, has_brand_campaign: bool
    ) -> MarketingAnalyticsRecommendation:
        cost, conversions, top_term = leak.cost, leak.conversions, leak.top_term
        share = cost / max(self._term_cost(campaign.id), 1)
        brand = next((brand for brand in self.brands if brand in top_term.replace(" ", "")), top_term)
        # Performance Max takes no negative keywords; brand exclusions are its equivalent.
        action = (
            f'Add a brand exclusion for "{brand}"'
            if campaign.channel_type == "PERFORMANCE_MAX"
            else f'Add "{brand}" as a negative keyword'
        )
        follow_up = (
            "Your brand campaign can serve them at a lower cost."
            if has_brand_campaign
            else "People who search your brand often find you without an ad."
        )
        return self._recommendation(
            MarketingAnalyticsRecommendationRule.BRAND_LEAK,
            "campaign",
            campaign.name,
            action,
            f'{share:.0%} of its search term spend goes to brand searches such as "{top_term}", '
            f"with {conversions:.0f} conversions. {follow_up}",
            cost * self.per_month,
            "save",
            "measured",
        )

    def _scale(
        self, campaign: CampaignStats, cpa: float, nonbrand_cpa: float, lost: float
    ) -> MarketingAnalyticsRecommendation:
        budget_bound = (campaign.lost_to_budget or 0) >= (campaign.lost_to_rank or 0)
        extra = campaign.cost * min(lost / max(campaign.impression_share or 0.1, 0.1), 1)
        return self._recommendation(
            MarketingAnalyticsRecommendationRule.SCALE_CAMPAIGN,
            "campaign",
            campaign.name,
            "Raise the budget" if budget_bound else "Raise bids or improve ad quality",
            f"Non-brand CPA of {self._money(cpa)}, against {self._money(nonbrand_cpa)} across non-brand campaigns. "
            f"It loses {campaign.lost_to_budget or 0:.0%} of impressions to budget "
            f"and {campaign.lost_to_rank or 0:.0%} to ad rank.",
            extra * self.per_month,
            "invest",
            "estimated",
        )

    def _performance_max_rank(self, campaign: CampaignStats) -> MarketingAnalyticsRecommendation:
        lost = (campaign.lost_to_budget or 0) + (campaign.lost_to_rank or 0)
        extra = campaign.cost * min(lost / max(campaign.impression_share or 0.1, 0.1), 1)
        return self._recommendation(
            MarketingAnalyticsRecommendationRule.SCALE_CAMPAIGN,
            "campaign",
            campaign.name,
            "Raise the target CPA or improve its asset groups",
            f"Converts at a CPA of {self._money(campaign.cost / campaign.conversions)}. "
            f"It loses {campaign.lost_to_rank or 0:.0%} of eligible search impressions to ad rank "
            f"and {campaign.lost_to_budget or 0:.0%} to budget, so most missed searches go to better-ranked ads.",
            extra * self.per_month,
            "invest",
            "estimated",
        )

    def _review(
        self, campaign: CampaignStats, cpa: float | None, nonbrand_cpa: float
    ) -> MarketingAnalyticsRecommendation:
        reason = (
            f"Spent {self._money(campaign.cost)} with no non-brand conversions."
            if cpa is None
            else f"Non-brand CPA of {self._money(cpa)}, {cpa / nonbrand_cpa:.1f}x the non-brand average "
            f"of {self._money(nonbrand_cpa)}."
        )
        return self._recommendation(
            MarketingAnalyticsRecommendationRule.REVIEW_CAMPAIGN,
            "campaign",
            campaign.name,
            "Review bids, ads and landing page, or pause",
            reason,
            campaign.cost * self.per_month,
            "save",
            "measured",
        )

    # Search term rules

    def _search_term_rules(self) -> list[MarketingAnalyticsRecommendation]:
        if not self.terms:
            return []
        terms = list(self.terms.values())
        paid_cost = sum(term.cost for term in terms)
        paid_conversions = sum(term.conversions for term in terms)
        cpa = paid_cost / paid_conversions if paid_conversions else None
        unranked = [term for term in terms if not term.organic or term.organic.position > 3]
        unranked_clicks = sum(term.clicks for term in unranked)
        average_cpc = sum(term.cost for term in unranked) / unranked_clicks if unranked_clicks else None
        vocabulary = self._vocabulary(terms, cpa)
        competitors = self._competitor_names()

        rules: dict[MarketingAnalyticsRecommendationRule, list[MarketingAnalyticsRecommendation]] = defaultdict(list)
        if cpa:
            rules[MarketingAnalyticsRecommendationRule.BRAND_OVERLAP] = self._brand_overlap(terms, cpa)
            rules[MarketingAnalyticsRecommendationRule.CONTENT_GAP] = [
                self._term_recommendation(
                    MarketingAnalyticsRecommendationRule.CONTENT_GAP,
                    term,
                    "Create or improve a page for this search",
                    f"Converts in Ads at a CPA of {self._money(term.cost / term.conversions)} "
                    f"(account {self._money(cpa)}), but "
                    + (
                        f"ranks #{term.organic.position:.1f} organically"
                        if term.organic
                        else "does not rank organically"
                    ),
                    term.conversions * cpa,
                    "gain",
                    "measured",
                )
                for term in terms
                if term.term not in self.brand_terms
                and term.conversions >= 2
                and term.cost / term.conversions <= cpa
                and (not term.organic or term.organic.position > 10)
            ]
            rules[MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS] = [
                self._term_recommendation(
                    MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS,
                    term,
                    self._no_conversion_action(term, competitors),
                    f"Spent {self._money(term.cost)} ({term.cost / cpa:.1f}x the account CPA) "
                    f"on {term.clicks:.0f} clicks with no conversions",
                    term.cost,
                    "save",
                    "measured",
                )
                for term in terms
                if term.term not in self.brand_terms
                and term.conversions == 0
                and term.cost >= 2 * cpa
                and term.status in ("NONE", "")
                and self._serving(term)
            ]
        if self.organic:
            if average_cpc:
                rules[MarketingAnalyticsRecommendationRule.KEYWORD_GAP] = self._keyword_gap(
                    average_cpc, vocabulary, competitors
                )
            rules[MarketingAnalyticsRecommendationRule.STRIKING_DISTANCE] = [
                self._term_recommendation(
                    MarketingAnalyticsRecommendationRule.STRIKING_DISTANCE,
                    term,
                    "Improve the ranking page to reach the top 3",
                    f"Position {term.organic.position:.1f} with {term.organic.impressions:.0f} impressions "
                    f"and {term.organic.clicks:.0f} clicks. Paid CPC {self._money(term.cost / term.clicks)}",
                    max(term.organic.impressions * TOP3_CTR - term.organic.clicks, 0) * term.cost / term.clicks,
                    "gain",
                    "estimated",
                )
                for term in terms
                if term.organic
                and term.term not in self.brand_terms
                and 5 <= term.organic.position <= 20
                and term.clicks >= 5
                and term.term not in competitors
            ]

        ordered: list[MarketingAnalyticsRecommendation] = []
        for rule in (
            MarketingAnalyticsRecommendationRule.BRAND_OVERLAP,
            MarketingAnalyticsRecommendationRule.CONTENT_GAP,
            MarketingAnalyticsRecommendationRule.KEYWORD_GAP,
            MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS,
            MarketingAnalyticsRecommendationRule.STRIKING_DISTANCE,
        ):
            ordered.extend(sorted(rules.get(rule, []), key=lambda rec: -(rec.impact or 0))[:PER_RULE_LIMIT])
        return ordered

    def _no_conversion_action(self, term: _Term, competitors: set[str]) -> str:
        keyword = self.top_keyword.get(term.term)
        match_type = MATCH_TYPES.get(keyword.match_type, keyword.match_type).lower() if keyword else ""
        if self._mentions(term.term, competitors):
            matched_by = f' It matched the keyword "{keyword.keyword}" ({match_type} match).' if keyword else ""
            return f"Competitor term: decide whether conquesting is worth it.{matched_by}"
        if not keyword:
            return "Review the bid and landing page, or add it as a negative"
        if match_type in ("broad", "phrase") and keyword.keyword.lower() != term.term:
            return f'Add it as a negative, or change the keyword "{keyword.keyword}" from {match_type} to exact match'
        return f'Review the keyword "{keyword.keyword}" ({match_type} match) and its landing page, or pause it'

    def _brand_overlap(self, terms: list[_Term], cpa: float) -> list[MarketingAnalyticsRecommendation]:
        recommendations = []
        for term in terms:
            organic = term.organic
            if (
                term.term not in self.brand_terms
                or not organic
                or organic.position > 3
                or term.cost < cpa
                or not self._serving(term)
            ):
                continue
            reason = (
                f"Ranks #{organic.position:.1f} organically with {organic.clicks:.0f} clicks. "
                f"Ads cost {self._money(term.cost)} for {term.clicks:.0f} clicks."
            )
            # Another ad above yours on your own brand search means someone bids on it, so pausing hands them the top spot.
            if term.absolute_top is not None and term.absolute_top < BRAND_DEFENSE_ABSOLUTE_TOP:
                recommendations.append(
                    self._term_recommendation(
                        MarketingAnalyticsRecommendationRule.BRAND_OVERLAP,
                        term,
                        "Keep the ad: another ad often shows above yours",
                        f"{reason} When your ad shows, another ad is above it {1 - term.absolute_top:.0%} of the time.",
                        term.cost,
                        "keep",
                        "measured",
                    )
                )
            elif term.absolute_top is None:
                # Without the top position, a competitor bidding on the brand is invisible, so pausing is not safe to suggest.
                recommendations.append(
                    self._term_recommendation(
                        MarketingAnalyticsRecommendationRule.BRAND_OVERLAP,
                        term,
                        "Check whether other ads show above yours before you test pausing",
                        f"{reason} Top position data for this term is not synced yet.",
                        term.cost,
                        "save",
                        "estimated",
                    )
                )
            else:
                recommendations.append(
                    self._term_recommendation(
                        MarketingAnalyticsRecommendationRule.BRAND_OVERLAP,
                        term,
                        "Test pausing the ad in alternating weeks and compare total clicks",
                        f"{reason} Your ad is at the very top {term.absolute_top:.0%} of the time it shows.",
                        term.cost,
                        "save",
                        "measured",
                    )
                )
        return recommendations

    def _keyword_gap(
        self, average_cpc: float, vocabulary: set[str], competitors: set[str]
    ) -> list[MarketingAnalyticsRecommendation]:
        has_search = any(
            campaign.channel_type == "SEARCH" and campaign.primary_status not in INACTIVE_STATUSES
            for campaign in self.campaigns.values()
        )
        impressions = sorted(query.impressions for query in self.organic.values())
        threshold = impressions[int(len(impressions) * 0.95)] if impressions else 0
        recommendations = []
        for query in self.organic.values():
            if query.query in self.terms or query.position <= 10 or query.impressions < threshold:
                continue
            if self._is_brand_query(query.query, query, 0) or self._mentions(query.query, competitors):
                continue
            words = [word for word in query.query.split() if len(word) >= 3 and word not in GENERIC_WORDS]
            matched = [word for word in words if word in vocabulary]
            if not words or len(matched) < len(words):
                continue
            recommendations.append(
                self._recommendation(
                    MarketingAnalyticsRecommendationRule.KEYWORD_GAP,
                    "search_term",
                    query.query,
                    "Add as a keyword in Google Ads" if has_search else "Add as a search theme in Performance Max",
                    f"{query.impressions:.0f} organic impressions at position {query.position:.1f}, not bought. "
                    "Its words all appear in paid searches that convert at or below the account CPA",
                    query.impressions * TOP3_CTR * average_cpc * self.per_month,
                    "invest",
                    "estimated",
                )
            )
        return recommendations

    # Helpers

    def _aggregate_terms(self) -> dict[str, _Term]:
        totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        statuses: dict[str, str] = {}
        cost_by_campaign: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        top_impressions: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for row in self.inputs.search_terms:
            total = totals[row.term]
            total[0] += row.clicks
            total[1] += row.cost
            total[2] += row.conversions
            statuses.setdefault(row.term, row.status)
            cost_by_campaign[row.term][row.campaign_id] += row.cost
            if row.absolute_top_percentage is not None and row.impressions:
                top_impressions[row.term][0] += row.absolute_top_percentage * row.impressions
                top_impressions[row.term][1] += row.impressions
        return {
            term: _Term(
                term=term,
                clicks=clicks,
                cost=cost,
                conversions=conversions,
                status=statuses[term],
                top_campaign_id=max(cost_by_campaign[term], key=lambda campaign: cost_by_campaign[term][campaign]),
                organic=self.organic.get(term),
                absolute_top=top[0] / top[1] if (top := top_impressions.get(term)) and top[1] else None,
            )
            for term, (clicks, cost, conversions) in totals.items()
        }

    def _names_brand(self, query: str) -> bool:
        compact = query.replace(" ", "")
        return any(brand in compact for brand in self.brands)

    def _is_brand(self, term: _Term) -> bool:
        return self._is_brand_query(term.term, term.organic, term.clicks)

    def _is_brand_query(self, query: str, organic: OrganicQueryStats | None, paid_clicks: float) -> bool:
        if self._names_brand(query):
            return True
        # Navigational behavior also catches misspellings of the brand. Paid clicks count too, since
        # bidding on the brand pulls clicks away from the organic result.
        return bool(
            organic
            and organic.position < 2.5
            and organic.impressions >= 50
            and (organic.clicks + paid_clicks) / organic.impressions > 0.3
        )

    def _brand_spend_by_campaign(self) -> dict[str, _BrandSpend]:
        spend: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        top: dict[str, tuple[float, str]] = {}
        for row in self.inputs.search_terms:
            if row.term not in self.brand_terms:
                continue
            spend[row.campaign_id][0] += row.cost
            spend[row.campaign_id][1] += row.conversions
            if row.cost > top.get(row.campaign_id, (-1.0, ""))[0]:
                top[row.campaign_id] = (row.cost, row.term)
        return {
            campaign: _BrandSpend(cost=cost, conversions=conversions, top_term=top[campaign][1])
            for campaign, (cost, conversions) in spend.items()
        }

    def _is_brand_campaign(self, campaign: CampaignStats, brand_spend: dict[str, _BrandSpend]) -> bool:
        spend = brand_spend.get(campaign.id)
        return spend is not None and spend.cost >= 0.5 * max(self._term_cost(campaign.id), 1)

    def _term_cost(self, campaign_id: str) -> float:
        return self.term_cost_by_campaign.get(campaign_id, 0.0)

    def _nonbrand_totals(self, campaign: CampaignStats, leak: _BrandSpend | None) -> _Spend:
        if not leak:
            return _Spend(cost=campaign.cost, conversions=campaign.conversions)
        return _Spend(
            cost=max(campaign.cost - leak.cost, 0), conversions=max(campaign.conversions - leak.conversions, 0)
        )

    def _vocabulary(self, terms: list[_Term], cpa: float | None) -> set[str]:
        # Words from non-brand terms that convert at or below the account CPA: the account's own
        # definition of a relevant search. Terms that convert only at a high cost do not count.
        return {
            word
            for term in terms
            if term.conversions > 0
            and term.term not in self.brand_terms
            and (cpa is None or term.cost / term.conversions <= cpa)
            for word in term.term.split()
            if len(word) >= 3 and word not in GENERIC_WORDS
        }

    def _competitor_names(self) -> set[str]:
        queries = set(self.organic) | set(self.terms)
        comparisons: dict[str, int] = defaultdict(int)
        appearances: dict[str, int] = defaultdict(int)
        for query in queries:
            for word in set(query.split()):
                appearances[DOMAIN_SUFFIX.sub("", word)] += 1
            if self._names_brand(query):
                continue
            for pattern in COMPETITOR_PATTERNS:
                match = pattern.search(query)
                if match:
                    comparisons[DOMAIN_SUFFIX.sub("", match.group(1))] += 1
        # A competitor shows up in two comparison searches, is searched on its own, and a fair share of the
        # searches that mention it are comparisons. Category words like "analytics" appear in thousands of
        # searches and almost never as the subject of a comparison.
        return {
            name
            for name, count in comparisons.items()
            if count >= 2
            and len(name) >= 3
            and name in queries
            and name not in self.brands
            and name not in GENERIC_WORDS
            and count / appearances[name] >= COMPETITOR_COMPARISON_SHARE
        }

    @staticmethod
    def _mentions(query: str, competitors: set[str]) -> bool:
        return any(DOMAIN_SUFFIX.sub("", word) in competitors for word in query.split())

    def _serving(self, term: _Term) -> bool:
        # Advice to cut or pause a term is moot when its campaign no longer serves.
        campaign = self.campaigns.get(term.top_campaign_id)
        return campaign is None or campaign.primary_status not in INACTIVE_STATUSES

    def _term_recommendation(
        self,
        rule: MarketingAnalyticsRecommendationRule,
        term: _Term,
        action: str,
        reason: str,
        impact: float,
        direction: Direction,
        impact_type: Literal["measured", "estimated"],
    ) -> MarketingAnalyticsRecommendation:
        campaign = self.campaigns.get(term.top_campaign_id)
        return self._recommendation(
            rule,
            "search_term",
            term.term,
            action,
            reason,
            impact * self.per_month,
            direction,
            impact_type,
            campaign.name if campaign else None,
        )

    def _recommendation(
        self,
        rule: MarketingAnalyticsRecommendationRule,
        level: Literal["campaign", "search_term"],
        subject: str,
        action: str,
        reason: str,
        impact: float | None,
        direction: Direction,
        impact_type: Literal["measured", "estimated"],
        campaign: str | None = None,
    ) -> MarketingAnalyticsRecommendation:
        return MarketingAnalyticsRecommendation(
            rule=rule,
            level=level,
            subject=subject,
            campaign=campaign,
            action=action,
            reason=reason,
            impact=round(impact) if impact is not None else None,
            impactDirection=direction,
            impactType=impact_type,
            currency=self.inputs.currency,
        )

    def _money(self, amount: float) -> str:
        currency = self.inputs.currency or ""
        return f"${amount:,.0f}" if currency in ("USD", "") else f"{amount:,.0f} {currency}"
