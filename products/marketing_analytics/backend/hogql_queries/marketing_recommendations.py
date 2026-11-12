import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from itertools import groupby
from typing import Literal
from urllib.parse import quote

import tldextract

from posthog.schema import (
    MarketingAnalyticsRecommendation,
    MarketingAnalyticsRecommendationCpa,
    MarketingAnalyticsRecommendationCpaBenchmarkSource as BenchmarkSource,
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationResolution,
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationStep as Step,
)

from posthog.dataclasses import frozen

from products.marketing_analytics.backend.hogql_queries.recommendation_identity import (
    ACCOUNT_AGNOSTIC_RULES,
    SEARCH_TERM_RULES,
    RecommendationKey,
    recommendation_identity,
)

PER_RULE_LIMIT = 10
# Bounds the cached results. Resolutions apply after the cache, so a rule keeps spare candidates to fill the slots of
# the ones someone resolved.
CANDIDATES_PER_RULE = 100
# Share of impressions that become clicks once a page reaches the top 3 organic results. A rough industry figure.
TOP3_CTR = 0.15
# Below this, reaching the top 3 brings too few clicks to be worth editing the page.
STRIKING_MIN_MONTHLY_IMPRESSIONS = 100
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
# Google Ads pages for the whole account. A link cannot open one campaign, because that needs an
# interface id the API does not return, so steps also copy the campaign name to search for.
ADS_CAMPAIGNS_URL = "https://ads.google.com/aw/campaigns"
ADS_KEYWORDS_URL = "https://ads.google.com/aw/keywords"
ADS_NEGATIVE_KEYWORDS_URL = "https://ads.google.com/aw/keywords/negative"
ADS_SEARCH_TERMS_URL = "https://ads.google.com/aw/keywords/searchterms"
SEARCH_CONSOLE_PERFORMANCE_URL = "https://search.google.com/search-console/performance/search-analytics"
SEARCH_CONSOLE_URL = "https://search.google.com/search-console"
REVIEW_TERMS_SHOWN = 3
# A non-brand campaign is up for review when its cost per conversion reaches this multiple of its CPA benchmark.
# Without conversions, spend alone must reach that multiple: even one conversion would leave its CPA at or above it.
REVIEW_CPA_MULTIPLE = 3
# A brand search is worth a pause test once it takes this share of the account's search term spend. A share, unlike
# a CPA, also works for an account that only bids on its brand.
BRAND_OVERLAP_MIN_SPEND_SHARE = 0.0025
# From this many non-brand conversions a campaign's own CPA is stable enough to judge its search terms by.
MIN_CAMPAIGN_BENCHMARK_CONVERSIONS = 15
# Below this many Google Ads sessions, a missing utm_term can be a few visits from links shared without it.
MIN_KEYWORD_TRACKING_SESSIONS = 30
# Performance Max and Display clicks have no keyword, so even a configured account leaves some sessions without it.
MAX_KEYWORD_TRACKING_SHARE = 0.05
KEYWORD_PARAMETER = "utm_term={keyword}"
BENCHMARK_LABELS = {
    BenchmarkSource.TARGET_CPA: "the campaign's target CPA",
    BenchmarkSource.CAMPAIGN: "the campaign's non-brand CPA",
    BenchmarkSource.ACCOUNT: "the account's non-brand CPA",
}


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
    target_cpa: float | None = None
    tracking_url_template: str | None = None


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
class RankingPage:
    query: str
    page: str
    impressions: float


@frozen
class TermKeywordStats:
    term: str
    keyword: str
    match_type: str
    cost: float


@frozen
class KeywordTracking:
    account_name: str
    sessions: int
    sessions_with_keyword: int
    account_tracking_url_template: str | None = None
    account_final_url_suffix: str | None = None


@frozen
class RecommendationInputs:
    campaigns: tuple[CampaignStats, ...]
    search_terms: tuple[SearchTermStats, ...]
    organic_queries: tuple[OrganicQueryStats, ...]
    site_urls: tuple[str, ...]
    currency: str | None
    days: int
    term_keywords: tuple[TermKeywordStats, ...] = ()
    ranking_pages: tuple[RankingPage, ...] = ()
    customer_id: str | None = None
    keyword_tracking: KeywordTracking | None = None


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


@frozen
class _Benchmark:
    cpa: float
    source: BenchmarkSource

    @property
    def label(self) -> str:
        return BENCHMARK_LABELS[self.source]

    @property
    def compared(self) -> str:
        # Google Ads bids to a target CPA with every primary conversion, so a campaign meets it on its total CPA.
        return "CPA" if self.source == BenchmarkSource.TARGET_CPA else "non-brand CPA"

    @property
    def compared_conversions(self) -> str:
        return "conversions" if self.source == BenchmarkSource.TARGET_CPA else "non-brand conversions"


@frozen
class _Advice:
    action: str
    steps: tuple[Step, ...]


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


def dedupe_account_agnostic_rules(
    recommendations: Iterable[MarketingAnalyticsRecommendation],
) -> list[MarketingAnalyticsRecommendation]:
    # These rules carry no account ids, so every ad account that buys the search repeats the same recommendation.
    seen: set[str] = set()
    deduped = []
    for recommendation in recommendations:
        if recommendation.rule in ACCOUNT_AGNOSTIC_RULES:
            if recommendation.key in seen:
                continue
            seen.add(recommendation.key)
        deduped.append(recommendation)
    return deduped


def apply_resolutions(
    recommendations: Iterable[MarketingAnalyticsRecommendation],
    resolutions: Mapping[str, MarketingAnalyticsRecommendationResolution],
    *,
    include_resolved: bool,
) -> list[MarketingAnalyticsRecommendation]:
    """Drop resolved recommendations, or annotate them, and cap each search term rule per ad account.

    Account-agnostic rules have no ad account, so their candidates from every account share one cap and the
    highest-impact ones fill it. `resolutions` maps a recommendation key to its resolution. Resolved
    recommendations take no slot, so resolving the top ones lets the next ones surface. With `include_resolved`,
    they follow the unresolved ones of their run.
    """
    shown: dict[tuple[str, str], int] = defaultdict(int)
    applied: list[MarketingAnalyticsRecommendation] = []
    runs = groupby(_pool_account_agnostic_rules(recommendations), key=lambda rec: (rec.rule, rec.identity.customer_id))
    for (rule, customer_id), run in runs:
        resolved = []
        for recommendation in run:
            resolution = resolutions.get(recommendation.key)
            if resolution is not None:
                if include_resolved:
                    resolved.append(recommendation.model_copy(update={"resolution": resolution}))
            elif rule not in SEARCH_TERM_RULES or shown[(rule, customer_id)] < PER_RULE_LIMIT:
                shown[(rule, customer_id)] += 1
                applied.append(recommendation)
        applied.extend(resolved)
    return applied


def _pool_account_agnostic_rules(
    recommendations: Iterable[MarketingAnalyticsRecommendation],
) -> list[MarketingAnalyticsRecommendation]:
    candidates = list(recommendations)
    pooled: dict[MarketingAnalyticsRecommendationRule, list[MarketingAnalyticsRecommendation]] = defaultdict(list)
    for recommendation in candidates:
        if recommendation.rule in ACCOUNT_AGNOSTIC_RULES:
            pooled[recommendation.rule].append(recommendation)
    ordered: list[MarketingAnalyticsRecommendation] = []
    for recommendation in candidates:
        if recommendation.rule not in ACCOUNT_AGNOSTIC_RULES:
            ordered.append(recommendation)
        elif (pool := pooled.pop(recommendation.rule, None)) is not None:
            ordered.extend(sorted(pool, key=lambda rec: -(rec.impact or 0)))
    return ordered


def recommend(inputs: RecommendationInputs) -> list[MarketingAnalyticsRecommendation]:
    return _Recommender(inputs).run()


class _Recommender:
    def __init__(self, inputs: RecommendationInputs) -> None:
        self.inputs = inputs
        self.per_month = 30 / max(inputs.days, 1)
        self.brands = brands_from_site_urls(inputs.site_urls)
        # Query rows come back in no fixed order, and the campaign that carries a shared budget's recommendation must not change between runs.
        self.campaigns = {campaign.id: campaign for campaign in sorted(inputs.campaigns, key=lambda c: c.id)}
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
        top_pages: dict[str, RankingPage] = {}
        for page_row in inputs.ranking_pages:
            current_page = top_pages.get(page_row.query)
            if current_page is None or page_row.impressions > current_page.impressions:
                top_pages[page_row.query] = page_row
        self.ranking_page = {query: row.page for query, row in top_pages.items()}
        self.brand_spend = self._brand_spend_by_campaign()
        self.nonbrand = {
            campaign.id: self._nonbrand_totals(campaign, self.brand_spend.get(campaign.id))
            for campaign in self.campaigns.values()
        }
        self.search_campaigns = [
            campaign
            for campaign in self.campaigns.values()
            if campaign.channel_type == "SEARCH" and not self._is_brand_campaign(campaign, self.brand_spend)
        ]
        # The same campaigns and non-brand basis as the benchmark, so a Search campaign's CPA sits inside the range.
        search_cpas = [cpa for campaign in self.search_campaigns if (cpa := self._nonbrand_cpa(campaign)) is not None]
        self.best_campaign_cpa = min(search_cpas, default=None)
        self.worst_campaign_cpa = max(search_cpas, default=None)
        self.account_cpa = self._account_nonbrand_cpa()

    def run(self) -> list[MarketingAnalyticsRecommendation]:
        campaign_rules = sorted(self._campaign_rules(), key=lambda rec: -(rec.impact or 0))
        return campaign_rules + self._account_rules() + self._search_term_rules()

    # Account rules

    def _account_rules(self) -> list[MarketingAnalyticsRecommendation]:
        tracking = self.inputs.keyword_tracking
        return [self._keyword_tracking(tracking)] if tracking and self._lacks_keyword_tracking(tracking) else []

    def _lacks_keyword_tracking(self, tracking: KeywordTracking) -> bool:
        if (
            tracking.sessions < MIN_KEYWORD_TRACKING_SESSIONS
            or tracking.sessions_with_keyword > MAX_KEYWORD_TRACKING_SHARE * tracking.sessions
        ):
            return False
        # Only Search ads have a keyword to pass.
        serving = [
            campaign
            for campaign in self.campaigns.values()
            if campaign.channel_type == "SEARCH" and campaign.primary_status not in INACTIVE_STATUSES
        ]
        # The settings are read as they are now, so an account that just added the parameter drops out at once,
        # while the sessions in the selected dates still lack it.
        if not serving or _passes_keyword(tracking.account_final_url_suffix):
            return False
        # A campaign's tracking template replaces the account's, while the suffix is a separate setting.
        return not all(
            _passes_keyword(campaign.tracking_url_template or tracking.account_tracking_url_template)
            for campaign in serving
        )

    def _keyword_tracking(self, tracking: KeywordTracking) -> MarketingAnalyticsRecommendation:
        missing = 1 - tracking.sessions_with_keyword / tracking.sessions
        return self._recommendation(
            MarketingAnalyticsRecommendationRule.KEYWORD_TRACKING,
            "account",
            tracking.account_name,
            f"Add {KEYWORD_PARAMETER} to the account's Final URL suffix",
            f"{missing:.0%} of the project's {tracking.sessions:,} Google Ads sessions in the selected dates have no "
            "utm_term, so PostHog conversion goals cannot be tied to the keyword that brought each visitor.",
            None,
            "gain",
            "measured",
            recommendation_identity(MarketingAnalyticsRecommendationRule.KEYWORD_TRACKING, self.inputs.customer_id),
            steps=(
                Step(text="In Google Ads, open Admin, then Account settings, and expand Tracking."),
                Step(
                    text="Add this parameter to the Final URL suffix and save. If the field already has parameters, "
                    "add & before it. Google replaces {keyword} with the keyword that matched the search.",
                    copyValue=KEYWORD_PARAMETER,
                ),
                Step(
                    text="Open Campaigns and, in each Search campaign's settings, expand Campaign URL options. If it "
                    "has a Final URL suffix, add the parameter there too, because a campaign suffix replaces the "
                    "account's. Ad group and keyword suffixes replace it the same way.",
                    url=ADS_CAMPAIGNS_URL,
                    linkText="Campaigns",
                ),
            ),
        )

    # Campaign rules

    def _campaign_rules(self) -> list[MarketingAnalyticsRecommendation]:
        recommendations: list[MarketingAnalyticsRecommendation] = []
        brand_spend, search_campaigns = self.brand_spend, self.search_campaigns
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
                    self._campaign_recommendation(
                        MarketingAnalyticsRecommendationRule.POLICY_LIMITED,
                        campaign,
                        "Check the affected ads in Policy manager",
                        "Some ads or asset groups are limited or disapproved by Google policy, which cuts the campaign's reach.",
                        None,
                        "gain",
                        "measured",
                        cpa=self._campaign_cpa(campaign),
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
            benchmark = self._campaign_benchmark(campaign)
            if benchmark is None:
                continue
            compared = self._compared_spend(campaign, benchmark)
            cpa = self._compared_cpa(campaign, benchmark)
            lost = (campaign.lost_to_budget or 0) + (campaign.lost_to_rank or 0)
            if cpa and compared.conversions >= 5 and cpa <= benchmark.cpa and lost >= 0.4:
                recommendations.append(self._scale(campaign, cpa, benchmark, lost))
            elif (
                search_cost
                and campaign.cost >= 0.05 * search_cost
                and (cpa if cpa is not None else compared.cost) >= REVIEW_CPA_MULTIPLE * benchmark.cpa
            ):
                recommendations.append(self._review(campaign, cpa, compared.cost, benchmark))
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
        return self._campaign_recommendation(
            MarketingAnalyticsRecommendationRule.BUDGET_CONSTRAINED,
            campaign,
            f"Raise the daily budget from {self._money(budget)} to {self._money(recommended)}",
            f"Limited by budget. {lost}{self._money(recommended)} a day is Google's recommended budget.",
            (recommended - budget) * 30,
            "invest",
            "estimated",
            budget_id=campaign.budget_id,
            cpa=self._campaign_cpa(campaign),
        )

    def _brand_leak(
        self, campaign: CampaignStats, leak: _BrandSpend, has_brand_campaign: bool
    ) -> MarketingAnalyticsRecommendation:
        cost, conversions, top_term = leak.cost, leak.conversions, leak.top_term
        share = cost / max(self._term_cost(campaign.id), 1)
        brand = next((brand for brand in self.brands if brand in top_term.replace(" ", "")), top_term)
        check = Step(
            text="After a week, check the campaign's search terms. If misspellings of your brand still show, "
            "add each one the same way.",
            url=ADS_SEARCH_TERMS_URL,
            linkText="search terms",
        )
        # Performance Max takes no negative keywords; brand exclusions are its equivalent.
        if campaign.channel_type == "PERFORMANCE_MAX":
            action = f'Add a brand exclusion for "{brand}"'
            steps = (
                self._open_campaign(campaign.name),
                Step(text="Open the campaign settings, go to Brand exclusions, and create a brand list."),
                Step(text="Add your brand to the list and save it.", copyValue=brand),
                check,
            )
        else:
            action = f'Add "{brand}" as a negative keyword'
            steps = (
                self._open_campaign(campaign.name),
                Step(
                    text="Open Negative keywords and add one for this campaign.",
                    url=ADS_NEGATIVE_KEYWORDS_URL,
                    linkText="Negative keywords",
                ),
                Step(
                    text="Paste this keyword. The quotes make it phrase match, so it blocks searches that contain it "
                    "spelled this way.",
                    copyValue=f'"{brand}"',
                ),
                check,
            )
        follow_up = (
            "Your brand campaign can serve them at a lower cost."
            if has_brand_campaign
            else "People who search your brand often find you without an ad."
        )
        return self._campaign_recommendation(
            MarketingAnalyticsRecommendationRule.BRAND_LEAK,
            campaign,
            action,
            f'{share:.0%} of its search term spend goes to brand searches such as "{top_term}", '
            f"with {conversions:.0f} conversions. {follow_up}",
            cost * self.per_month,
            "save",
            "measured",
            steps=steps,
            cpa=self._campaign_cpa(campaign),
        )

    def _scale(
        self, campaign: CampaignStats, cpa: float, benchmark: _Benchmark, lost: float
    ) -> MarketingAnalyticsRecommendation:
        budget_bound = (campaign.lost_to_budget or 0) >= (campaign.lost_to_rank or 0)
        extra = campaign.cost * min(lost / max(campaign.impression_share or 0.1, 0.1), 1)
        return self._campaign_recommendation(
            MarketingAnalyticsRecommendationRule.SCALE_CAMPAIGN,
            campaign,
            "Raise the budget" if budget_bound else "Raise bids or improve ad quality",
            f"Its {benchmark.compared} is {self._money(cpa)}, against {benchmark.label} of {self._money(benchmark.cpa)}. "
            f"It loses {campaign.lost_to_budget or 0:.0%} of impressions to budget "
            f"and {campaign.lost_to_rank or 0:.0%} to ad rank.",
            extra * self.per_month,
            "invest",
            "estimated",
            cpa=self._cpa(cpa, benchmark),
        )

    def _performance_max_rank(self, campaign: CampaignStats) -> MarketingAnalyticsRecommendation:
        cpa = campaign.cost / campaign.conversions
        lost = (campaign.lost_to_budget or 0) + (campaign.lost_to_rank or 0)
        extra = campaign.cost * min(lost / max(campaign.impression_share or 0.1, 0.1), 1)
        return self._campaign_recommendation(
            MarketingAnalyticsRecommendationRule.SCALE_CAMPAIGN,
            campaign,
            "Raise the target CPA or improve its asset groups",
            f"Converts at a CPA of {self._money(cpa)}. "
            f"It loses {campaign.lost_to_rank or 0:.0%} of eligible search impressions to ad rank "
            f"and {campaign.lost_to_budget or 0:.0%} to budget, so most missed searches go to better-ranked ads.",
            extra * self.per_month,
            "invest",
            "estimated",
            cpa=self._cpa(cpa, self._campaign_benchmark(campaign)),
        )

    def _review(
        self, campaign: CampaignStats, cpa: float | None, compared_cost: float, benchmark: _Benchmark
    ) -> MarketingAnalyticsRecommendation:
        reason = (
            f"Spent {self._money(compared_cost)} ({compared_cost / benchmark.cpa:.1f}x {benchmark.label} "
            f"of {self._money(benchmark.cpa)}) with no {benchmark.compared_conversions}."
            if cpa is None
            else f"Its {benchmark.compared} is {self._money(cpa)}, {cpa / benchmark.cpa:.1f}x {benchmark.label} "
            f"of {self._money(benchmark.cpa)}."
        )
        return self._campaign_recommendation(
            MarketingAnalyticsRecommendationRule.REVIEW_CAMPAIGN,
            campaign,
            "Review bids, ads and landing page, or pause",
            reason,
            campaign.cost * self.per_month,
            "save",
            "measured",
            steps=self._review_steps(campaign, cpa, benchmark),
            cpa=self._cpa(cpa, benchmark),
        )

    def _review_steps(self, campaign: CampaignStats, cpa: float | None, benchmark: _Benchmark) -> tuple[Step, ...]:
        spend: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        # ADDED means the search is already a keyword and EXCLUDED means it is already a negative.
        targeted_or_excluded: set[str] = set()
        excluded: set[str] = set()
        for row in self.inputs.search_terms:
            if row.campaign_id != campaign.id or row.term in self.brand_terms:
                continue
            spend[row.term][0] += row.cost
            spend[row.term][1] += row.conversions
            if row.status not in ("NONE", ""):
                targeted_or_excluded.add(row.term)
            if "EXCLUDED" in row.status:
                excluded.add(row.term)
        competitors = self._competitor_names()
        draining = sorted(
            (
                term
                for term, (cost, conversions) in spend.items()
                if cost >= benchmark.cpa
                and not conversions
                and term not in targeted_or_excluded
                and not self._mentions(term, competitors)
            ),
            key=lambda term: -spend[term][0],
        )[:REVIEW_TERMS_SHOWN]
        converting = sorted(
            (
                term
                for term, (cost, conversions) in spend.items()
                if conversions > 0 and cost / conversions <= benchmark.cpa and term not in excluded
            ),
            key=lambda term: -spend[term][1],
        )[:REVIEW_TERMS_SHOWN]
        steps = [self._open_campaign(campaign.name)]
        if draining:
            listed = ", ".join(f'"{term}" ({self._money(spend[term][0])})' for term in draining)
            steps.append(
                Step(
                    text=f"Start with the searches that spent the most without converting: {listed}. "
                    "Open Negative keywords and add them for the campaign in exact match.",
                    copyValue="\n".join(f"[{term}]" for term in draining),
                    url=ADS_NEGATIVE_KEYWORDS_URL,
                    linkText="Negative keywords",
                )
            )
        if converting:
            listed = ", ".join(
                f'"{term}" ({self._money(spend[term][0] / spend[term][1])} per conversion)' for term in converting
            )
            steps.append(
                Step(
                    text=f"Keep the searches that convert at or below {benchmark.label}: {listed}. "
                    "Check that their keywords stay active."
                )
            )
        steps.append(
            Step(
                text=f"If its {benchmark.compared} is still more than {REVIEW_CPA_MULTIPLE}x {benchmark.label} "
                "after two weeks, pause it in Campaigns."
                if cpa is not None
                else f"If after two weeks it still has no {benchmark.compared_conversions}, or its {benchmark.compared} "
                f"is more than {REVIEW_CPA_MULTIPLE}x {benchmark.label}, pause it in Campaigns.",
                url=ADS_CAMPAIGNS_URL,
                linkText="Campaigns",
            )
        )
        return tuple(steps)

    # Search term rules

    def _search_term_rules(self) -> list[MarketingAnalyticsRecommendation]:
        if not self.terms:
            return []
        terms = list(self.terms.values())
        benchmarks = {
            term.term: benchmark
            for term in terms
            if (benchmark := self._search_term_benchmark(self.campaigns.get(term.top_campaign_id)))
        }
        unranked = [term for term in terms if not term.organic or term.organic.position > 3]
        unranked_clicks = sum(term.clicks for term in unranked)
        average_cpc = sum(term.cost for term in unranked) / unranked_clicks if unranked_clicks else None
        vocabulary = self._vocabulary(terms, benchmarks)
        competitors = self._competitor_names()

        rules: dict[MarketingAnalyticsRecommendationRule, list[MarketingAnalyticsRecommendation]] = defaultdict(list)
        rules[MarketingAnalyticsRecommendationRule.BRAND_OVERLAP] = self._brand_overlap(terms, benchmarks)
        rules[MarketingAnalyticsRecommendationRule.CONTENT_GAP] = [
            self._term_recommendation(
                MarketingAnalyticsRecommendationRule.CONTENT_GAP,
                term,
                benchmark,
                "Create or improve a page for this search",
                f"You pay {self._money(term.cost * self.per_month)}/mo in Ads for this search, which converts "
                f"at a CPA of {self._money(term.cost / term.conversions)} ({benchmark.label} is "
                f"{self._money(benchmark.cpa)}). "
                + (
                    f"It ranks #{term.organic.position:.1f} organically, so moving that page into the top 3 "
                    if term.organic
                    else "It does not rank organically, so a new page in the top 3 "
                )
                + "could bring these visitors without ad spend.",
                term.conversions * benchmark.cpa,
                "gain",
                "measured",
                steps=self._content_gap_steps(term),
            )
            for term in terms
            if (benchmark := benchmarks.get(term.term))
            and term.term not in self.brand_terms
            and term.conversions >= 2
            and term.cost / term.conversions <= benchmark.cpa
            and (not term.organic or term.organic.position > 10)
            and not self._in_striking_distance(term, competitors)
        ]
        rules[MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS] = [
            self._term_recommendation(
                MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS,
                term,
                benchmark,
                advice.action,
                f"Spent {self._money(term.cost)} ({term.cost / benchmark.cpa:.1f}x {benchmark.label}) "
                f"on {term.clicks:.0f} clicks with no conversions",
                term.cost,
                "save",
                "measured",
                steps=advice.steps,
            )
            for term in terms
            if (benchmark := benchmarks.get(term.term))
            and term.term not in self.brand_terms
            and term.conversions == 0
            and term.cost >= 2 * benchmark.cpa
            and term.status in ("NONE", "")
            and self._serving(term)
            for advice in (self._no_conversion_advice(term, competitors),)
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
                    benchmarks.get(term.term),
                    "Improve the ranking page to reach the top 3",
                    f"Position {term.organic.position:.1f} with {term.organic.impressions:.0f} impressions "
                    f"and {term.organic.clicks:.0f} clicks. Paid CPC {self._money(term.cost / term.clicks)}",
                    max(term.organic.impressions * TOP3_CTR - term.organic.clicks, 0) * term.cost / term.clicks,
                    "gain",
                    "estimated",
                    steps=self._improve_page_steps(term.term),
                )
                for term in terms
                if term.organic and self._in_striking_distance(term, competitors)
            ]

        ordered: list[MarketingAnalyticsRecommendation] = []
        for rule in (
            MarketingAnalyticsRecommendationRule.BRAND_OVERLAP,
            MarketingAnalyticsRecommendationRule.CONTENT_GAP,
            MarketingAnalyticsRecommendationRule.KEYWORD_GAP,
            MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS,
            MarketingAnalyticsRecommendationRule.STRIKING_DISTANCE,
        ):
            ordered.extend(sorted(rules.get(rule, []), key=lambda rec: -(rec.impact or 0))[:CANDIDATES_PER_RULE])
        return ordered

    def _no_conversion_advice(self, term: _Term, competitors: set[str]) -> _Advice:
        keyword = self.top_keyword.get(term.term)
        match_type = MATCH_TYPES.get(keyword.match_type, keyword.match_type).lower() if keyword else ""
        open_campaign = self._open_campaign(self._campaign_name(term))
        exact = f"[{term.term}]"
        negative = Step(
            text="Open Negative keywords and add this one for the campaign. The brackets make it exact match, "
            "so it blocks only this search.",
            copyValue=exact,
            url=ADS_NEGATIVE_KEYWORDS_URL,
            linkText="Negative keywords",
        )
        if self._mentions(term.term, competitors):
            matched_by = f' It matched the keyword "{keyword.keyword}" ({match_type} match).' if keyword else ""
            return _Advice(
                action=f"Competitor term: decide whether conquesting is worth it.{matched_by}",
                steps=(
                    open_campaign,
                    Step(
                        text="If showing on this search is not worth it, open Negative keywords and add it "
                        "for the campaign in exact match.",
                        copyValue=exact,
                        url=ADS_NEGATIVE_KEYWORDS_URL,
                        linkText="Negative keywords",
                    ),
                ),
            )
        if not keyword:
            return _Advice(
                action="Review the bid and landing page, or add it as a negative", steps=(open_campaign, negative)
            )
        if match_type in ("broad", "phrase") and keyword.keyword.lower() != term.term:
            return _Advice(
                action=f'Add it as a negative, or change the keyword "{keyword.keyword}" from {match_type} to exact match',
                steps=(
                    open_campaign,
                    negative,
                    Step(
                        text="Or, to stop similar searches too, open Keywords, find this keyword, "
                        "and change its match type to exact.",
                        copyValue=keyword.keyword,
                        url=ADS_KEYWORDS_URL,
                        linkText="Keywords",
                    ),
                ),
            )
        return _Advice(
            action=f'Review the keyword "{keyword.keyword}" ({match_type} match) and its landing page, or pause it',
            steps=(
                open_campaign,
                Step(
                    text="Open Keywords, find this keyword, and check its bid and final URL.",
                    copyValue=keyword.keyword,
                    url=ADS_KEYWORDS_URL,
                    linkText="Keywords",
                ),
                Step(text="If the bid and the page look right and it still does not convert, pause the keyword."),
            ),
        )

    def _brand_overlap(
        self, terms: list[_Term], benchmarks: dict[str, _Benchmark]
    ) -> list[MarketingAnalyticsRecommendation]:
        recommendations = []
        min_cost = BRAND_OVERLAP_MIN_SPEND_SHARE * sum(term.cost for term in terms)
        for term in terms:
            organic = term.organic
            benchmark = benchmarks.get(term.term)
            if (
                term.term not in self.brand_terms
                or not organic
                or organic.position > 3
                or term.cost < min_cost
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
                        benchmark,
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
                        benchmark,
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
                        benchmark,
                        "Test pausing the ad in alternating weeks and compare total clicks",
                        f"{reason} Your ad is at the very top {term.absolute_top:.0%} of the time it shows.",
                        term.cost,
                        "save",
                        "measured",
                    )
                )
        return recommendations

    def _keyword_gap(
        self,
        average_cpc: float,
        vocabulary: dict[str, dict[str, float]],
        competitors: set[str],
    ) -> list[MarketingAnalyticsRecommendation]:
        has_search = any(
            campaign.channel_type == "SEARCH" and campaign.primary_status not in INACTIVE_STATUSES
            for campaign in self.campaigns.values()
        )
        channel = "SEARCH" if has_search else "PERFORMANCE_MAX"
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
            campaign = self._campaign_for_words(matched, vocabulary, channel)
            if has_search:
                steps: tuple[Step, ...] = (
                    self._open_campaign(
                        campaign.name if campaign else None,
                        fallback="In Google Ads, open Campaigns and pick the search campaign closest to this topic, "
                        "or create one.",
                    ),
                    Step(
                        text="Open Keywords and add this one to an ad group of the campaign. The quotes make it "
                        "phrase match, so it also matches longer searches that contain it.",
                        copyValue=f'"{query.query}"',
                        url=ADS_KEYWORDS_URL,
                        linkText="Keywords",
                    ),
                    Step(text="Check that the ad and the landing page answer this search."),
                )
            else:
                steps = (
                    self._open_campaign(
                        campaign.name if campaign else None,
                        fallback="In Google Ads, open Campaigns and pick your Performance Max campaign.",
                    ),
                    Step(text="Open the asset group and add this search theme.", copyValue=query.query),
                )
            recommendations.append(
                self._recommendation(
                    MarketingAnalyticsRecommendationRule.KEYWORD_GAP,
                    "search_term",
                    query.query,
                    "Add as a keyword in Google Ads" if has_search else "Add as a search theme in Performance Max",
                    f"{query.impressions:.0f} organic impressions at position {query.position:.1f}, not bought. "
                    "Its words all appear in paid searches that convert at or below their CPA benchmark",
                    query.impressions * TOP3_CTR * average_cpc * self.per_month,
                    "invest",
                    "estimated",
                    recommendation_identity(
                        MarketingAnalyticsRecommendationRule.KEYWORD_GAP, self.inputs.customer_id, subject=query.query
                    ),
                    campaign.name if campaign else None,
                    steps=steps,
                    cpa=self._cpa(None, self._search_term_benchmark(campaign)),
                )
            )
        return recommendations

    def _campaign_for_words(
        self, words: list[str], vocabulary: dict[str, dict[str, float]], channel: str
    ) -> CampaignStats | None:
        # The campaign with the most conversions on searches that use the query's words already serves the topic.
        conversions: dict[str, float] = defaultdict(float)
        for word in words:
            for campaign_id, count in vocabulary.get(word, {}).items():
                conversions[campaign_id] += count
        candidates = [
            campaign
            for campaign_id in conversions
            if (campaign := self.campaigns.get(campaign_id))
            and campaign.channel_type == channel
            and campaign.primary_status not in INACTIVE_STATUSES
        ]
        return max(candidates, key=lambda campaign: conversions[campaign.id], default=None)

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

    def _vocabulary(self, terms: list[_Term], benchmarks: dict[str, _Benchmark]) -> dict[str, dict[str, float]]:
        # Words from non-brand terms that convert at or below their CPA benchmark: the account's own
        # definition of a relevant search. Terms that convert only at a high cost do not count.
        # Each word maps to the conversions per campaign of the terms that contain it.
        vocabulary: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for term in terms:
            if (
                term.conversions <= 0
                or term.term in self.brand_terms
                or ((benchmark := benchmarks.get(term.term)) and term.cost / term.conversions > benchmark.cpa)
            ):
                continue
            for word in term.term.split():
                if len(word) >= 3 and word not in GENERIC_WORDS:
                    vocabulary[word][term.top_campaign_id] += term.conversions
        return vocabulary

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

    def _campaign_name(self, term: _Term) -> str | None:
        campaign = self.campaigns.get(term.top_campaign_id)
        return campaign.name if campaign else None

    @staticmethod
    def _open_campaign(
        name: str | None,
        fallback: str = "In Google Ads, open Campaigns and pick the campaign that shows ads for this search.",
    ) -> Step:
        if name is None:
            return Step(text=fallback, url=ADS_CAMPAIGNS_URL, linkText="Campaigns")
        return Step(
            text="In Google Ads, open Campaigns and search for this campaign.",
            copyValue=name,
            url=ADS_CAMPAIGNS_URL,
            linkText="Campaigns",
        )

    def _in_striking_distance(self, term: _Term, competitors: set[str]) -> bool:
        return bool(
            term.organic
            and term.term not in self.brand_terms
            and 5 <= term.organic.position <= 20
            and term.organic.impressions * self.per_month >= STRIKING_MIN_MONTHLY_IMPRESSIONS
            and term.clicks >= 5
            and term.term not in competitors
        )

    def _content_gap_steps(self, term: _Term) -> tuple[Step, ...]:
        keep_ad = Step(text="Keep the ad running until the page reaches the top 3, then test pausing it.")
        if term.organic:
            return (*self._improve_page_steps(term.term), keep_ad)
        return (
            Step(
                text="Create a page that answers this search. Use the search in the page title and main heading.",
                copyValue=term.term,
            ),
            self._internal_links_step(),
            Step(
                text="In Search Console, use URL inspection to request indexing of the new page.",
                url=self._search_console_url(SEARCH_CONSOLE_URL),
                linkText="Search Console",
            ),
            keep_ad,
        )

    def _improve_page_steps(self, query: str) -> tuple[Step, ...]:
        page = self.ranking_page.get(query)
        find_page = (
            Step(text="Open the page that ranks for this search.", copyValue=page, url=page, linkText="page")
            if page
            else Step(
                text="In Search Console, open Performance, filter by this search and check the Pages tab to find "
                "the page that ranks.",
                copyValue=query,
                url=self._search_console_url(SEARCH_CONSOLE_PERFORMANCE_URL),
                linkText="Performance",
            )
        )
        return (
            find_page,
            Step(
                text="Use the search in the page title and main heading, and answer it near the top of the page.",
                copyValue=query,
            ),
            self._internal_links_step(),
            Step(
                text="In Search Console, use URL inspection to request indexing of the updated page.",
                url=self._search_console_url(SEARCH_CONSOLE_URL),
                linkText="Search Console",
            ),
        )

    def _search_console_url(self, url: str) -> str:
        # With several properties the right one is unknown, so Search Console opens its property picker.
        sites = set(self.inputs.site_urls)
        return f"{url}?resource_id={quote(sites.pop(), safe='')}" if len(sites) == 1 else url

    @staticmethod
    def _internal_links_step() -> Step:
        return Step(text="Link to the page from related pages on your site, using the search as the link text.")

    def _term_recommendation(
        self,
        rule: MarketingAnalyticsRecommendationRule,
        term: _Term,
        benchmark: _Benchmark | None,
        action: str,
        reason: str,
        impact: float,
        direction: Direction,
        impact_type: Literal["measured", "estimated"],
        steps: tuple[Step, ...] = (),
    ) -> MarketingAnalyticsRecommendation:
        return self._recommendation(
            rule,
            "search_term",
            term.term,
            action,
            reason,
            impact * self.per_month,
            direction,
            impact_type,
            recommendation_identity(rule, self.inputs.customer_id, subject=term.term),
            self._campaign_name(term),
            steps=steps,
            cpa=self._cpa(term.cost / term.conversions if term.conversions else None, benchmark),
        )

    def _campaign_recommendation(
        self,
        rule: MarketingAnalyticsRecommendationRule,
        campaign: CampaignStats,
        action: str,
        reason: str,
        impact: float | None,
        direction: Direction,
        impact_type: Literal["measured", "estimated"],
        steps: tuple[Step, ...] = (),
        budget_id: str | None = None,
        cpa: MarketingAnalyticsRecommendationCpa | None = None,
    ) -> MarketingAnalyticsRecommendation:
        return self._recommendation(
            rule,
            "campaign",
            campaign.name,
            action,
            reason,
            impact,
            direction,
            impact_type,
            recommendation_identity(rule, self.inputs.customer_id, campaign_id=campaign.id, subject=budget_id),
            steps=steps,
            cpa=cpa,
        )

    def _recommendation(
        self,
        rule: MarketingAnalyticsRecommendationRule,
        level: Literal["account", "campaign", "search_term"],
        subject: str,
        action: str,
        reason: str,
        impact: float | None,
        direction: Direction,
        impact_type: Literal["measured", "estimated"],
        identity: MarketingAnalyticsRecommendationIdentity,
        campaign: str | None = None,
        steps: tuple[Step, ...] = (),
        cpa: MarketingAnalyticsRecommendationCpa | None = None,
    ) -> MarketingAnalyticsRecommendation:
        return MarketingAnalyticsRecommendation(
            rule=rule,
            level=level,
            subject=subject,
            campaign=campaign,
            identity=identity,
            key=RecommendationKey.from_identity(identity).encoded,
            action=action,
            reason=reason,
            impact=round(impact) if impact is not None else None,
            impactDirection=direction,
            impactType=impact_type,
            currency=self.inputs.currency,
            steps=list(steps),
            cpa=cpa,
        )

    def _nonbrand_cpa(self, campaign: CampaignStats) -> float | None:
        totals = self.nonbrand[campaign.id]
        return totals.cost / totals.conversions if totals.conversions else None

    def _compared_spend(self, campaign: CampaignStats, benchmark: _Benchmark | None) -> _Spend:
        if benchmark is not None and benchmark.source == BenchmarkSource.TARGET_CPA:
            return _Spend(cost=campaign.cost, conversions=campaign.conversions)
        return self.nonbrand[campaign.id]

    def _compared_cpa(self, campaign: CampaignStats, benchmark: _Benchmark | None) -> float | None:
        spend = self._compared_spend(campaign, benchmark)
        return spend.cost / spend.conversions if spend.conversions else None

    def _campaign_cpa(self, campaign: CampaignStats) -> MarketingAnalyticsRecommendationCpa:
        benchmark = self._campaign_benchmark(campaign)
        return self._cpa(self._compared_cpa(campaign, benchmark), benchmark)

    def _account_nonbrand_cpa(self) -> float | None:
        # An account without Search campaigns, such as one that only runs Performance Max, still needs a benchmark.
        campaigns = self.search_campaigns or [
            campaign for campaign in self.campaigns.values() if not self._is_brand_campaign(campaign, self.brand_spend)
        ]
        cost = sum(self.nonbrand[campaign.id].cost for campaign in campaigns)
        conversions = sum(self.nonbrand[campaign.id].conversions for campaign in campaigns)
        return cost / conversions if conversions else None

    def _campaign_benchmark(self, campaign: CampaignStats | None) -> _Benchmark | None:
        if campaign is not None and campaign.target_cpa:
            return _Benchmark(cpa=campaign.target_cpa, source=BenchmarkSource.TARGET_CPA)
        # A zero CPA comes from conversions without cost, and nothing can be measured against it.
        if self.account_cpa:
            return _Benchmark(cpa=self.account_cpa, source=BenchmarkSource.ACCOUNT)
        return None

    def _search_term_benchmark(self, campaign: CampaignStats | None) -> _Benchmark | None:
        # A search term is judged against the campaign that serves it. Campaign rules use _campaign_benchmark,
        # which skips the campaign's own CPA so a campaign is never compared with itself.
        if (
            campaign is not None
            and not campaign.target_cpa
            and self.nonbrand[campaign.id].conversions >= MIN_CAMPAIGN_BENCHMARK_CONVERSIONS
            and (own := self._nonbrand_cpa(campaign))
        ):
            return _Benchmark(cpa=own, source=BenchmarkSource.CAMPAIGN)
        return self._campaign_benchmark(campaign)

    def _cpa(self, value: float | None, benchmark: _Benchmark | None) -> MarketingAnalyticsRecommendationCpa:
        return MarketingAnalyticsRecommendationCpa(
            value=_round_money(value),
            benchmark=_round_money(benchmark.cpa if benchmark else None),
            benchmarkSource=benchmark.source if benchmark else None,
            bestCampaign=_round_money(self.best_campaign_cpa),
            worstCampaign=_round_money(self.worst_campaign_cpa),
        )

    def _money(self, amount: float) -> str:
        currency = self.inputs.currency or ""
        return f"${amount:,.0f}" if currency in ("USD", "") else f"{amount:,.0f} {currency}"


def _passes_keyword(url_option: str | None) -> bool:
    return url_option is not None and KEYWORD_PARAMETER in url_option.lower()


def _round_money(amount: float | None) -> float | None:
    return round(amount, 2) if amount is not None else None
