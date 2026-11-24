import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from difflib import SequenceMatcher
from itertools import groupby
from typing import Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

import tldextract

from posthog.schema import (
    MarketingAnalyticsRecommendation,
    MarketingAnalyticsRecommendationCpa,
    MarketingAnalyticsRecommendationCpaBenchmarkSource as BenchmarkSource,
    MarketingAnalyticsRecommendationDetectedChange as DetectedChange,
    MarketingAnalyticsRecommendationIdentity,
    MarketingAnalyticsRecommendationResolution,
    MarketingAnalyticsRecommendationRule,
    MarketingAnalyticsRecommendationStep as Step,
)

from posthog.dataclasses import frozen
from posthog.taxonomy.taxonomy import CAMPAIGN_PROPERTIES

from products.marketing_analytics.backend.hogql_queries.recommendation_identity import (
    ACCOUNT_AGNOSTIC_RULES,
    SEARCH_TERM_RULES,
    RecommendationKey,
    recommendation_identity,
)

RECOMMENDATION_SOURCE_TYPES = ("GoogleAds", "GoogleSearchConsole")
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
LIMITED_APPROVALS = frozenset({"APPROVED_LIMITED", "AREA_OF_INTEREST_ONLY"})
DISAPPROVED = "DISAPPROVED"
# Google also lists findings that do not restrict an ad, such as the language it detected.
POLICY_ISSUE_TYPES = frozenset({"PROHIBITED", "LIMITED", "FULLY_LIMITED", "AREA_OF_INTEREST_ONLY"})
POLICY_ADS_SHOWN = 3
POLICY_EVIDENCE_SHOWN = 3
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
WORD = re.compile(r"[a-z0-9]+")
# Words almost every ad and search contain, so sharing one says nothing about whether a search fits the ads.
STOP_WORDS = frozenset(
    {
        "and",
        "are",
        "but",
        "can",
        "for",
        "from",
        "get",
        "how",
        "not",
        "our",
        "the",
        "this",
        "that",
        "what",
        "with",
        "you",
        "your",
    }
)
# Below this, a search has too few clicks to call it unrelated to the ads that showed on it.
OFF_TOPIC_MIN_CLICKS = 5
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
# How close a search must spell the brand to count as a misspelling of it, as a SequenceMatcher ratio.
MIN_MISSPELLING_SIMILARITY = 0.75
MAX_BRAND_MISSPELLINGS = 5
# The bundled public suffix snapshot, so parsing a site never fetches the list over the network.
DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)

Direction = Literal["save", "gain", "invest", "keep"]
# Google Ads KeywordMatchType values, for tables that stored the enum number.
MATCH_TYPES = {"2": "EXACT", "3": "PHRASE", "4": "BROAD"}
# Google Ads pages for the whole account. A link cannot open one campaign, because that needs an
# interface id the API does not return, so steps also copy the campaign name to search for.
ADS_ACCOUNT_SETTINGS_URL = "https://ads.google.com/aw/settings/account"
ADS_CAMPAIGNS_URL = "https://ads.google.com/aw/campaigns"
ADS_KEYWORDS_URL = "https://ads.google.com/aw/keywords"
ADS_ADS_URL = "https://ads.google.com/aw/ads"
ADS_ASSET_GROUPS_URL = "https://ads.google.com/aw/assetgroup"
ADS_POLICY_ISSUES_URL = "https://ads.google.com/aw/policy/ads/issues"
ADS_NEGATIVE_KEYWORDS_URL = "https://ads.google.com/aw/keywords/negative"
ADS_SEARCH_TERMS_URL = "https://ads.google.com/aw/keywords/searchterms"
SEARCH_CONSOLE_PERFORMANCE_URL = "https://search.google.com/search-console/performance/search-analytics"
SEARCH_CONSOLE_URL = "https://search.google.com/search-console"
REVIEW_TERMS_SHOWN = 3
# A non-brand campaign is up for review when its cost per conversion reaches this multiple of its CPA benchmark.
# Without conversions, spend alone must reach that multiple: even one conversion would leave its CPA at or above it.
REVIEW_CPA_MULTIPLE = 3
# Below this share of Search spend, a campaign costs too little for its CPA to be worth reviewing.
REVIEW_MIN_SPEND_SHARE = 0.05
# A brand search is worth a pause test once it takes this share of the account's search term spend. A share, unlike
# a CPA, also works for an account that only bids on its brand.
BRAND_OVERLAP_MIN_SPEND_SHARE = 0.0025
MINOR_IMPACT_SHARE = 0.01
# From this many non-brand conversions a campaign's own CPA is stable enough to judge its search terms by.
MIN_CAMPAIGN_BENCHMARK_CONVERSIONS = 15
# Below this many Google Ads sessions, a missing utm_term can be a few visits from links shared without it.
MIN_KEYWORD_TRACKING_SESSIONS = 30
# Performance Max and Display clicks have no keyword, so even a configured account leaves some sessions without it.
MAX_KEYWORD_TRACKING_SHARE = 0.05
KEYWORD_PARAMETER = "utm_term={keyword}"
CAMPAIGN_PARAMETERS = frozenset(CAMPAIGN_PROPERTIES)
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
class ExcludedSearch:
    term: str
    campaign_id: str


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
    ad_group_ids: tuple[str, ...] = ()


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
    campaign_id: str
    keyword: str
    match_type: str
    cost: float


@frozen
class Keyword:
    text: str
    campaign_id: str
    # Read from the campaign table, so a campaign without spend in the selected dates still counts.
    channel_type: str | None
    campaign_status: str | None


@frozen
class KeywordTracking:
    account_name: str
    sessions: int
    sessions_with_keyword: int
    account_tracking_url_template: str | None = None
    account_final_url_suffix: str | None = None


@frozen
class Ad:
    ad_group_id: str
    campaign_id: str
    texts: tuple[str, ...]
    final_urls: tuple[str, ...]


@frozen
class PolicyTopic:
    topic: str
    type: str
    texts: tuple[str, ...] = ()


@frozen
class FlaggedAd:
    campaign_id: str
    ad_id: str
    headline: str
    policy_topics: tuple[PolicyTopic, ...]


@frozen
class PolicyAds:
    campaign_id: str
    disapproved: int
    limited: int


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
    ads: tuple[Ad, ...] = ()
    keywords: tuple[Keyword, ...] = ()
    excluded_searches: frozenset[ExcludedSearch] = frozenset()
    policy_ads: tuple[PolicyAds, ...] = ()
    flagged_ads: tuple[FlaggedAd, ...] = ()


@frozen
class _Term:
    term: str
    clicks: float
    impressions: float
    cost: float
    conversions: float
    status: str
    excluded_everywhere: bool
    # Spend in the campaigns that still serve the search, or all of it once every campaign blocks it.
    serving_clicks: float
    serving_cost: float
    top_campaign_id: str
    ad_group_ids: frozenset[str]
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


def _is_meaningful(word: str) -> bool:
    return len(word) >= 3 and word not in GENERIC_WORDS


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _policy_issues(ad: FlaggedAd) -> tuple[PolicyTopic, ...]:
    return tuple(topic for topic in ad.policy_topics if topic.type in POLICY_ISSUE_TYPES)


def _policy_issue_text(topic: PolicyTopic) -> str:
    # Google names a policy by its topic id, such as TRADEMARKS_IN_AD_TEXT.
    name = topic.topic.replace("_", " ").capitalize()
    # Only a prohibited topic is a violation. The other types restrict where the ad can show.
    verb = "breaks" if topic.type == "PROHIBITED" else "is limited by"
    if not topic.texts:
        return f'{verb} the policy "{name}"'
    quoted = ", ".join(f'"{text}"' for text in topic.texts[:POLICY_EVIDENCE_SHOWN])
    return f'{verb} the policy "{name}" (flagged text: {quoted})'


def _policy_fix(ad: FlaggedAd, headline_repeats: bool) -> Step:
    issues = " and ".join(_policy_issue_text(topic) for topic in _policy_issues(ad))
    if ad.headline and not headline_repeats:
        return Step(text=f'The ad "{ad.headline}" {issues}.', copyValue=ad.headline)
    # Ads often share a pinned first headline, and searching Ads for it would list all of them.
    named = f'The ad "{ad.headline}" with ID {ad.ad_id}' if ad.headline else f"The ad with ID {ad.ad_id}"
    return Step(text=f"{named} {issues}.", copyValue=ad.ad_id or None)


def _word_stems(text: str) -> frozenset[str]:
    # Plurals fold into one stem, so "funnels" in a search still matches "funnel" in an ad.
    return frozenset(
        stem
        for word in WORD.findall(text.lower())
        if _is_meaningful(word) and word not in STOP_WORDS and _is_meaningful(stem := _singular(word))
    )


def _is_keyword(status: str) -> bool:
    # Google reports ADDED_EXCLUDED for a search that is both a keyword and a negative.
    return "ADDED" in status


def _page_key(url: str) -> str:
    # Search Console and ad final URLs spell the same page differently, such as with or without www or a final slash.
    parts = urlsplit(url)
    page = parts.netloc.lower().removeprefix("www.") + parts.path.rstrip("/")
    # A query parameter can pick the page, such as product.php?id=100, but click and campaign tags never do.
    query = sorted(
        (name, value)
        for name, value in parse_qsl(parts.query)
        if not name.lower().startswith("utm_") and name.lower() not in CAMPAIGN_PARAMETERS
    )
    return f"{page}?{urlencode(query)}" if query else page


def _similarity(brand: str, compact_term: str) -> float:
    return SequenceMatcher(None, brand, compact_term).ratio()


def _brand_follow_up(has_brand_campaign: bool) -> str:
    if has_brand_campaign:
        return "Your brand campaign can serve them at a lower cost."
    return "People who search your brand often find you without an ad."


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
    recommendations, and those with a detected change, take no slot, so resolving the top ones lets the next
    ones surface. With `include_resolved`, they follow the unresolved ones of their run.
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
            elif recommendation.detectedChange is not None:
                if include_resolved:
                    resolved.append(recommendation)
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
        self.search_cost = sum(
            campaign.cost for campaign in self.campaigns.values() if campaign.channel_type == "SEARCH"
        )
        self.monthly_spend = sum(campaign.cost for campaign in self.campaigns.values()) * self.per_month
        self.organic = _merge_organic(inputs.organic_queries)
        self.term_cost_by_campaign: dict[str, float] = defaultdict(float)
        for row in inputs.search_terms:
            self.term_cost_by_campaign[row.campaign_id] += row.cost
        self.terms = self._aggregate_terms()
        self.brand_terms = {term.term for term in self.terms.values() if self._is_brand(term)}
        self.top_keyword: dict[str, dict[str, TermKeywordStats]] = defaultdict(dict)
        self.keyword_stems: dict[str, set[str]] = defaultdict(set)
        for keyword_row in inputs.term_keywords:
            by_campaign = self.top_keyword[keyword_row.term]
            current = by_campaign.get(keyword_row.campaign_id)
            if current is None or keyword_row.cost > current.cost:
                by_campaign[keyword_row.campaign_id] = keyword_row
            self.keyword_stems[keyword_row.term] |= _word_stems(keyword_row.keyword)
        self.keywords = {keyword_row.keyword.lower() for keyword_row in inputs.term_keywords}
        self.copy_stems: dict[str, set[str]] = defaultdict(set)
        self.keyword_insertion_groups: set[str] = set()
        self.policy_ads = {row.campaign_id: row for row in inputs.policy_ads}
        self.policy_issue_ads: dict[str, list[FlaggedAd]] = defaultdict(list)
        for flagged_ad in inputs.flagged_ads:
            if _policy_issues(flagged_ad):
                self.policy_issue_ads[flagged_ad.campaign_id].append(flagged_ad)
        for ad in inputs.ads:
            for text in ad.texts:
                self.copy_stems[ad.ad_group_id] |= _word_stems(text)
                if "{keyword:" in text.lower():
                    self.keyword_insertion_groups.add(ad.ad_group_id)
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
        self.search_keywords = {
            keyword.text for keyword in inputs.keywords if _serves_search(keyword.channel_type, keyword.campaign_status)
        }

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
            if _serves_search(campaign.channel_type, campaign.primary_status)
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
                Step(
                    text="In Google Ads, open Account settings and expand Tracking.",
                    url=ADS_ACCOUNT_SETTINGS_URL,
                    linkText="Account settings",
                ),
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
        constrained_budgets: set[str] = set()
        for campaign in self.campaigns.values():
            if campaign.primary_status in INACTIVE_STATUSES:
                continue
            budget = (
                None
                if self._is_brand_campaign(campaign, brand_spend)
                else self._budget_constrained(campaign, self._campaign_benchmark(campaign))
            )
            # Campaigns that share a budget each report it as constrained, so one row covers the shared budget.
            if budget and not (campaign.budget_id and campaign.budget_id in constrained_budgets):
                recommendations.append(budget)
                if campaign.budget_id:
                    constrained_budgets.add(campaign.budget_id)
            if POLICY_REASONS.intersection(campaign.status_reasons):
                recommendations.append(self._policy_limited(campaign))

        has_brand_campaign = any(self._is_brand_campaign(c, brand_spend) for c in self.campaigns.values())
        for campaign in self.campaigns.values():
            if campaign.channel_type != "PERFORMANCE_MAX" or campaign.primary_status in INACTIVE_STATUSES:
                continue
            leak = brand_spend.get(campaign.id)
            if leak and leak.cost >= 0.05 * max(self._term_cost(campaign.id), 1):
                recommendations.append(self._brand_leak(campaign, leak, has_brand_campaign))
            if campaign.conversions > 0 and (campaign.lost_to_rank or 0) >= 0.4:
                recommendations.append(self._performance_max_rank(campaign))

        search_leaks: list[tuple[CampaignStats, _BrandSpend]] = []
        for campaign in search_campaigns:
            if campaign.primary_status in INACTIVE_STATUSES:
                continue
            leak = brand_spend.get(campaign.id)
            if leak and leak.cost >= 0.05 * max(self._term_cost(campaign.id), 1):
                search_leaks.append((campaign, leak))
            benchmark = self._campaign_benchmark(campaign)
            if benchmark is None:
                continue
            compared = self._compared_spend(campaign, benchmark)
            cpa = self._compared_cpa(campaign, benchmark)
            lost = (campaign.lost_to_budget or 0) + (campaign.lost_to_rank or 0)
            if cpa and compared.conversions >= 5 and cpa <= benchmark.cpa and lost >= 0.4:
                recommendations.append(self._scale(campaign, cpa, benchmark, lost))
            elif self._needs_review(campaign, benchmark):
                recommendations.append(self._review(campaign, cpa, compared.cost, benchmark))
        recommendations.extend(self._search_brand_leaks(search_leaks, has_brand_campaign))
        return recommendations

    def _budget_constrained(
        self, campaign: CampaignStats, benchmark: _Benchmark | None
    ) -> MarketingAnalyticsRecommendation | None:
        budget, recommended = campaign.daily_budget, campaign.recommended_daily_budget
        cpa = self._compared_cpa(campaign, benchmark)
        if (
            "BUDGET_CONSTRAINED" not in campaign.status_reasons
            or not budget
            or not recommended
            or recommended <= budget
            or benchmark is None
            or cpa is None
            or cpa > benchmark.cpa
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
            f"Limited by budget, and its {benchmark.compared} is at or below {benchmark.label}. "
            f"{lost}{self._money(recommended)} a day is Google's recommended budget.",
            (recommended - budget) * 30,
            "invest",
            "estimated",
            budget_id=campaign.budget_id,
            steps=(
                self._open_campaign(campaign.name),
                Step(
                    text="Click its budget, change it to this daily amount and save. A shared budget changes for "
                    "every campaign that uses it.",
                    # A whole number reads the same in every Google Ads locale and currency.
                    copyValue=str(round(recommended)),
                ),
                self._check_cpa_step(benchmark),
            ),
            cpa=self._cpa(cpa, benchmark),
        )

    def _brand_leak(
        self, campaign: CampaignStats, leak: _BrandSpend, has_brand_campaign: bool
    ) -> MarketingAnalyticsRecommendation:
        cost, conversions, top_term = leak.cost, leak.conversions, leak.top_term
        share = cost / max(self._term_cost(campaign.id), 1)
        brand = self._brand_spelled_by(top_term) or top_term
        check = Step(
            text="After a week, check the campaign's search terms. If misspellings of your brand still show, "
            "add each one the same way.",
            url=ADS_SEARCH_TERMS_URL,
            linkText="search terms",
        )
        detected_change: DetectedChange | None = None
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
                self._paste_brand_negatives(brand, {campaign.id}),
                check,
            )
            if self._brand_negated(brand, {campaign.id}):
                detected_change = DetectedChange.BRAND_NEGATIVE
        return self._campaign_recommendation(
            MarketingAnalyticsRecommendationRule.BRAND_LEAK,
            campaign,
            action,
            f'{share:.0%} of its search term spend goes to brand searches such as "{top_term}", '
            f"with {conversions:,.0f} conversions. {_brand_follow_up(has_brand_campaign)}",
            cost * self.per_month,
            "save",
            "measured",
            steps=steps,
            detected_change=detected_change,
        )

    def _search_brand_leaks(
        self, leaks: list[tuple[CampaignStats, _BrandSpend]], has_brand_campaign: bool
    ) -> list[MarketingAnalyticsRecommendation]:
        by_brand: dict[str, list[tuple[CampaignStats, _BrandSpend]]] = defaultdict(list)
        for campaign, leak in leaks:
            by_brand[self._brand_spelled_by(leak.top_term) or leak.top_term].append((campaign, leak))
        return [
            self._shared_brand_leak(brand, group, has_brand_campaign)
            if len(group) > 1
            else self._brand_leak(group[0][0], group[0][1], has_brand_campaign)
            for brand, group in by_brand.items()
        ]

    def _shared_brand_leak(
        self, brand: str, group: list[tuple[CampaignStats, _BrandSpend]], has_brand_campaign: bool
    ) -> MarketingAnalyticsRecommendation:
        group = sorted(group, key=lambda pair: (-pair[1].cost, pair[0].name))
        cost = sum(leak.cost for _, leak in group)
        conversions = sum(leak.conversions for _, leak in group)
        names = [campaign.name for campaign, _ in group]
        steps = (
            Step(
                text="Open Negative keywords and create a negative keyword list.",
                url=ADS_NEGATIVE_KEYWORDS_URL,
                linkText="Negative keywords",
            ),
            self._paste_brand_negatives(brand, {campaign.id for campaign, _ in group}),
            Step(
                text=f"Apply the list to these {len(names)} campaigns, one name per line.",
                copyValue="\n".join(names),
            ),
            Step(
                text="After a week, check the search terms of these campaigns. If misspellings of your brand still "
                "show, add each one to the list.",
                url=ADS_SEARCH_TERMS_URL,
                linkText="search terms",
            ),
        )
        return self._recommendation(
            MarketingAnalyticsRecommendationRule.BRAND_LEAK,
            "account",
            f"{len(names)} non-brand campaigns",
            f'Add "{brand}" to a shared negative keyword list',
            f"{len(names)} non-brand campaigns spend {self._money(cost)} on brand searches such as "
            f'"{group[0][1].top_term}", with {conversions:,.0f} conversions. One shared list blocks these searches in '
            f"every campaign. {_brand_follow_up(has_brand_campaign)}",
            cost * self.per_month,
            "save",
            "measured",
            recommendation_identity(
                MarketingAnalyticsRecommendationRule.BRAND_LEAK, self.inputs.customer_id, subject=brand
            ),
            steps=steps,
            detected_change=DetectedChange.BRAND_NEGATIVE
            if self._brand_negated(brand, {campaign.id for campaign, _ in group})
            else None,
        )

    def _brand_negated(self, brand: str, campaign_ids: set[str]) -> bool:
        # Misspellings are a follow-up step, so the brand's own spelling decides whether the action is done.
        compact_brand = brand.replace(" ", "")
        searches = {
            ExcludedSearch(term=row.term, campaign_id=row.campaign_id)
            for row in self.inputs.search_terms
            if row.campaign_id in campaign_ids and compact_brand in row.term.replace(" ", "")
        }
        return bool(searches) and searches <= self.inputs.excluded_searches

    def _paste_brand_negatives(self, brand: str, campaign_ids: set[str]) -> Step:
        negatives = [brand, *self._brand_misspellings(campaign_ids, brand)]
        return Step(
            text="Paste this keyword. The quotes make it phrase match, so it blocks searches that contain it "
            "spelled this way."
            if len(negatives) == 1
            else "Paste these keywords, one per line: your brand and the misspellings of it that got clicks. "
            "The quotes make them phrase match, so they block searches that contain them spelled this way.",
            copyValue="\n".join(f'"{negative}"' for negative in negatives),
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
            f"Its {benchmark.compared} is at or below {benchmark.label}. "
            f"It loses {campaign.lost_to_budget or 0:.0%} of impressions to budget "
            f"and {campaign.lost_to_rank or 0:.0%} to ad rank.",
            extra * self.per_month,
            "invest",
            "estimated",
            steps=(
                self._open_campaign(campaign.name),
                Step(text="Click its budget, raise it and save.")
                if budget_bound
                else Step(text="Open the campaign settings, go to Bidding, raise the target CPA and save.")
                if campaign.target_cpa
                else Step(
                    text="Open Keywords, filter by this campaign, and raise the bids of the keywords that convert. "
                    "Check that their ads and landing page match the search.",
                    url=ADS_KEYWORDS_URL,
                    linkText="Keywords",
                ),
                self._check_cpa_step(benchmark),
            ),
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
            steps=(
                self._open_campaign(campaign.name),
                Step(
                    text="Open the campaign settings, go to Bidding, and raise the target CPA or lower the target "
                    "ROAS. Then save."
                ),
                Step(
                    text="Open Asset groups and add assets to the ones with Poor or Average ad strength.",
                    url=ADS_ASSET_GROUPS_URL,
                    linkText="Asset groups",
                ),
            ),
        )

    def _review(
        self, campaign: CampaignStats, cpa: float | None, compared_cost: float, benchmark: _Benchmark
    ) -> MarketingAnalyticsRecommendation:
        reason = (
            f"Spent {self._money(compared_cost)} ({compared_cost / benchmark.cpa:.1f}x {benchmark.label}) "
            f"with no {benchmark.compared_conversions}."
            if cpa is None
            else f"Its {benchmark.compared} is {cpa / benchmark.cpa:.1f}x {benchmark.label}."
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
        # A keyword or a negative already handles the search, so it is not worth listing again.
        targeted_or_excluded: set[str] = set()
        excluded: set[str] = set()
        for row in self.inputs.search_terms:
            if row.campaign_id != campaign.id or row.term in self.brand_terms:
                continue
            spend[row.term][0] += row.cost
            spend[row.term][1] += row.conversions
            is_excluded = self._is_excluded(row)
            if _is_keyword(row.status) or is_excluded:
                targeted_or_excluded.add(row.term)
            if is_excluded:
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
        rules[MarketingAnalyticsRecommendationRule.BRAND_OVERLAP] = self._brand_overlap(terms)
        rules[MarketingAnalyticsRecommendationRule.CONTENT_GAP] = [
            self._term_recommendation(
                MarketingAnalyticsRecommendationRule.CONTENT_GAP,
                term,
                benchmark,
                "Create or improve a page for this search",
                f"You pay {self._money(term.cost * self.per_month)}/mo in Ads for this search, which converts "
                f"at a CPA at or below {benchmark.label}. "
                + (
                    f"It ranks #{term.organic.position:.1f} organically, so moving that page into the top 3 "
                    if term.organic
                    else "It does not rank organically, so a new page in the top 3 "
                )
                + "could bring these visitors without ad spend.",
                term.cost * min(1, term.impressions * TOP3_CTR / max(term.clicks, 1)),
                "gain",
                "estimated",
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
        off_topic = {
            term.term for term in terms if self._is_off_topic(term) and not self._mentions(term.term, competitors)
        }
        rules[MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS] = [
            self._term_recommendation(
                MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS,
                term,
                benchmark,
                advice.action,
                f"Spent {self._money(term.serving_cost)} ({term.serving_cost / benchmark.cpa:.1f}x {benchmark.label}) "
                f"on {term.serving_clicks:,.0f} clicks with no conversions"
                + (self._off_topic_reason(term) if term.term in off_topic else ""),
                term.serving_cost,
                "save",
                "measured",
                steps=advice.steps,
                detected_change=DetectedChange.NEGATIVE_KEYWORD if term.excluded_everywhere else None,
            )
            for term in terms
            if (benchmark := benchmarks.get(term.term))
            and term.term not in self.brand_terms
            and term.conversions == 0
            and term.serving_cost >= 2 * benchmark.cpa
            and (term.excluded_everywhere or not _is_keyword(term.status))
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
                    None,
                    "Improve the ranking page to reach the top 3",
                    f"Position {term.organic.position:.1f} with {term.organic.impressions:,.0f} impressions "
                    f"and {term.organic.clicks:,.0f} clicks. Paid CPC {self._money(term.cost / term.clicks)}",
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
            # Applied ones go last, so they never take a slot from one that still needs doing.
            top = sorted(rules.get(rule, []), key=lambda rec: (rec.detectedChange is not None, -(rec.impact or 0)))[
                :CANDIDATES_PER_RULE
            ]
            # Searches unrelated to the ads that showed on them are the safest negatives, so they come first among the
            # costliest ones that show, without pushing a bigger waste out of the list.
            if rule == MarketingAnalyticsRecommendationRule.SPEND_WITHOUT_CONVERSIONS:
                top[:PER_RULE_LIMIT] = sorted(top[:PER_RULE_LIMIT], key=lambda rec: rec.subject not in off_topic)
            ordered.extend(top)
        return ordered

    def _is_off_topic(self, term: _Term) -> bool:
        # An ad group without synced copy could be the one that mentions the search, so it is not judged.
        if not term.ad_group_ids or any(group not in self.copy_stems for group in term.ad_group_ids):
            return False
        # Keyword insertion puts the matched keyword in the ad, so without the keyword the ad text is unknown.
        if term.ad_group_ids & self.keyword_insertion_groups and term.term not in self.keyword_stems:
            return False
        stems = _word_stems(term.term)
        copy = set().union(*(self.copy_stems[group] for group in term.ad_group_ids))
        return bool(
            stems
            and term.clicks >= OFF_TOPIC_MIN_CLICKS
            and not stems & (copy | self.keyword_stems.get(term.term, set()))
        )

    def _campaign_keyword(self, term: _Term) -> TermKeywordStats | None:
        # Steps open the top campaign, so a keyword that matched in another campaign is not there to edit.
        return self.top_keyword.get(term.term, {}).get(term.top_campaign_id)

    def _off_topic_reason(self, term: _Term) -> str:
        keyword = self._campaign_keyword(term)
        if keyword:
            return (
                ". None of the main words in this search appear in the ads that showed on it "
                f'or in the keyword "{keyword.keyword}".'
            )
        return ". None of the main words in this search appear in the ads that showed on it."

    def _no_conversion_advice(self, term: _Term, competitors: set[str]) -> _Advice:
        keyword = self._campaign_keyword(term)
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

    def _brand_overlap(self, terms: list[_Term]) -> list[MarketingAnalyticsRecommendation]:
        recommendations = []
        min_cost = BRAND_OVERLAP_MIN_SPEND_SHARE * sum(term.cost for term in terms)
        for term in terms:
            organic = term.organic
            if (
                term.term not in self.brand_terms
                or not organic
                or organic.position > 3
                or term.cost < min_cost
                or not self._serving(term)
            ):
                continue
            reason = (
                f"Ranks #{organic.position:.1f} organically with {organic.clicks:,.0f} clicks. "
                f"Ads cost {self._money(term.cost)} for {term.clicks:,.0f} clicks."
            )
            # Another ad above yours on your own brand search means someone bids on it, so pausing hands them the top spot.
            if term.absolute_top is not None and term.absolute_top < BRAND_DEFENSE_ABSOLUTE_TOP:
                recommendations.append(
                    self._term_recommendation(
                        MarketingAnalyticsRecommendationRule.BRAND_OVERLAP,
                        term,
                        None,
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
                        None,
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
                        None,
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
            _serves_search(campaign.channel_type, campaign.primary_status) for campaign in self.campaigns.values()
        )
        channel = "SEARCH" if has_search else "PERFORMANCE_MAX"
        landing_campaigns = self._landing_campaigns()
        impressions = sorted(query.impressions for query in self.organic.values())
        threshold = impressions[int(len(impressions) * 0.95)] if impressions else 0
        recommendations = []
        for query in self.organic.values():
            if (
                query.query in self.terms
                or query.query in self.keywords
                or query.position <= 10
                or query.impressions < threshold
            ):
                continue
            if self._is_brand_query(query.query, query, 0) or self._mentions(query.query, competitors):
                continue
            page = self.ranking_page.get(query.query)
            landing_campaign = landing_campaigns.get(_page_key(page)) if page else None
            words = [word for word in query.query.split() if _is_meaningful(word)]
            matched = [word for word in words if word in vocabulary]
            # A page the ads link to also ranks for loosely related queries, so one word has to convert already.
            if not matched or (landing_campaign is None and len(matched) < len(words)):
                continue
            campaign = landing_campaign or self._campaign_for_words(matched, vocabulary, channel)
            if landing_campaign:
                evidence = f"It ranks on {page}, which this campaign's ads link to"
                ad_group = f"the ad group whose ads link to {page}"
            else:
                evidence = "Its words all appear in paid searches that convert at or below their CPA benchmark"
                ad_group = "an ad group of the campaign"
            if has_search:
                steps: tuple[Step, ...] = (
                    self._open_campaign(
                        campaign.name if campaign else None,
                        fallback="In Google Ads, open Campaigns and pick the search campaign closest to this topic, "
                        "or create one.",
                    ),
                    Step(
                        text=f"Open Keywords and add this one to {ad_group}. The quotes make it "
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
                    Step(
                        text="Open Asset groups, pick the one closest to this search, and add the search as a search theme.",
                        copyValue=query.query,
                        url=ADS_ASSET_GROUPS_URL,
                        linkText="Asset groups",
                    ),
                )
            recommendations.append(
                self._recommendation(
                    MarketingAnalyticsRecommendationRule.KEYWORD_GAP,
                    "search_term",
                    query.query,
                    "Add as a keyword in Google Ads" if has_search else "Add as a search theme in Performance Max",
                    f"{query.impressions:,.0f} organic impressions at position {query.position:.1f}, not bought. "
                    + evidence,
                    query.impressions * TOP3_CTR * average_cpc * self.per_month,
                    "invest",
                    "estimated",
                    recommendation_identity(
                        MarketingAnalyticsRecommendationRule.KEYWORD_GAP, self.inputs.customer_id, subject=query.query
                    ),
                    campaign.name if campaign else None,
                    steps=steps,
                    # Performance Max search themes are not synced, so only a Search keyword shows the change.
                    detected_change=DetectedChange.KEYWORD_ADDED
                    if has_search and query.query in self.search_keywords
                    else None,
                )
            )
        return recommendations

    def _landing_campaigns(self) -> dict[str, CampaignStats]:
        # Only Search ad groups take keywords, and a brand campaign is the wrong home for a non-brand query.
        campaigns: dict[str, CampaignStats] = {}
        for ad in self.inputs.ads:
            campaign = self.campaigns.get(ad.campaign_id)
            if (
                campaign is None
                or campaign.channel_type != "SEARCH"
                or campaign.primary_status in INACTIVE_STATUSES
                or self._is_brand_campaign(campaign, self.brand_spend)
                or (
                    (benchmark := self._campaign_benchmark(campaign)) is not None
                    and self._needs_review(campaign, benchmark)
                )
            ):
                continue
            for url in ad.final_urls:
                key = _page_key(url)
                # Ads that link to the homepage would make almost every query that ranks there look relevant.
                if "/" not in key:
                    continue
                current = campaigns.get(key)
                if current is None or campaign.cost > current.cost:
                    campaigns[key] = campaign
        return campaigns

    def _needs_review(self, campaign: CampaignStats, benchmark: _Benchmark) -> bool:
        cpa = self._compared_cpa(campaign, benchmark)
        spend_per_conversion = cpa if cpa is not None else self._compared_spend(campaign, benchmark).cost
        return (
            self.search_cost > 0
            and campaign.cost >= REVIEW_MIN_SPEND_SHARE * self.search_cost
            and spend_per_conversion >= REVIEW_CPA_MULTIPLE * benchmark.cpa
        )

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

    def _is_excluded(self, row: SearchTermStats) -> bool:
        return ExcludedSearch(term=row.term, campaign_id=row.campaign_id) in self.inputs.excluded_searches

    def _aggregate_terms(self) -> dict[str, _Term]:
        totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        statuses: dict[str, str] = {}
        cost_by_campaign: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        ad_groups: dict[str, set[str]] = defaultdict(set)
        top_impressions: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        serving_campaigns: dict[str, set[str]] = defaultdict(set)
        for row in self.inputs.search_terms:
            if not self._is_excluded(row):
                serving_campaigns[row.term].add(row.campaign_id)
        serving_spend: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for row in self.inputs.search_terms:
            total = totals[row.term]
            total[0] += row.clicks
            total[1] += row.cost
            total[2] += row.conversions
            total[3] += row.impressions
            ad_groups[row.term].update(row.ad_group_ids)
            if row.absolute_top_percentage is not None and row.impressions:
                top_impressions[row.term][0] += row.absolute_top_percentage * row.impressions
                top_impressions[row.term][1] += row.impressions
            # A campaign that already blocks the search needs no change, so it decides nothing while another serves it.
            if row.term in serving_campaigns and row.campaign_id not in serving_campaigns[row.term]:
                continue
            serving_spend[row.term][0] += row.clicks
            serving_spend[row.term][1] += row.cost
            statuses.setdefault(row.term, row.status)
            cost_by_campaign[row.term][row.campaign_id] += row.cost
        return {
            term: _Term(
                term=term,
                clicks=clicks,
                impressions=impressions,
                cost=cost,
                conversions=conversions,
                status=statuses[term],
                excluded_everywhere=term not in serving_campaigns,
                serving_clicks=serving_spend[term][0],
                serving_cost=serving_spend[term][1],
                top_campaign_id=max(cost_by_campaign[term], key=lambda campaign: cost_by_campaign[term][campaign]),
                ad_group_ids=frozenset(ad_groups[term]),
                organic=self.organic.get(term),
                absolute_top=top[0] / top[1] if (top := top_impressions.get(term)) and top[1] else None,
            )
            for term, (clicks, cost, conversions, impressions) in totals.items()
        }

    def _names_brand(self, query: str) -> bool:
        compact = query.replace(" ", "")
        return any(brand in compact for brand in self.brands)

    def _brand_spelled_by(self, term: str) -> str | None:
        compact = term.replace(" ", "")
        if named := next((brand for brand in sorted(self.brands) if brand in compact), None):
            return named
        closest = max(sorted(self.brands), key=lambda brand: _similarity(brand, compact), default=None)
        return closest if closest and _similarity(closest, compact) >= MIN_MISSPELLING_SIMILARITY else None

    def _brand_misspellings(self, campaign_ids: set[str], brand: str) -> list[str]:
        cost_by_term: dict[str, float] = defaultdict(float)
        for row in self.inputs.search_terms:
            # An added term is a keyword the advertiser bids on, maybe on purpose; an excluded one is blocked already.
            if (
                row.campaign_id not in campaign_ids
                or row.status == "ADDED"
                or self._is_excluded(row)
                or row.term not in self.brand_terms
            ):
                continue
            if brand not in row.term.replace(" ", "") and self._brand_spelled_by(row.term) == brand:
                cost_by_term[row.term] += row.cost
        return sorted(cost_by_term, key=lambda term: (-cost_by_term[term], term))[:MAX_BRAND_MISSPELLINGS]

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
                if _is_meaningful(word):
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

    def _check_cpa_step(self, benchmark: _Benchmark) -> Step:
        # Google Ads shows no non-brand CPA, so the check happens on these recommendations.
        return Step(
            text=f"After two weeks, come back here and check that its {benchmark.compared} stays at or below "
            f"{self._money(benchmark.cpa)}, {benchmark.label}."
        )

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
        # A page other than the root needs a property, or it shows a welcome page. The root opens the last
        # property the user viewed.
        sites = set(self.inputs.site_urls)
        return f"{url}?resource_id={quote(sites.pop(), safe='')}" if len(sites) == 1 else SEARCH_CONSOLE_URL

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
        detected_change: DetectedChange | None = None,
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
            cpa=self._cpa(term.cost / term.conversions if term.conversions else None, benchmark) if benchmark else None,
            detected_change=detected_change,
        )

    def _policy_limited(self, campaign: CampaignStats) -> MarketingAnalyticsRecommendation:
        policy_ads = self.policy_ads.get(campaign.id)
        disapproved, limited = (policy_ads.disapproved, policy_ads.limited) if policy_ads else (0, 0)
        counts = [
            f"{count} {'ad is' if count == 1 else 'ads are'} {label}"
            for count, label in ((disapproved, "disapproved"), (limited, "limited"))
            if count
        ]
        reason = (
            f"{' and '.join(counts)} by Google policy, which cuts the campaign's reach."
            if counts
            else "Some ads or asset groups are limited or disapproved by Google policy, which cuts the campaign's reach."
        )
        fix: tuple[Step, ...]
        if campaign.channel_type == "PERFORMANCE_MAX":
            find = Step(
                text="Open Asset groups and look for assets whose status shows a policy issue. "
                "Hover the status to see which policy the asset breaks.",
                url=ADS_ASSET_GROUPS_URL,
                linkText="Asset groups",
            )
            fix = (Step(text="Replace each affected asset with one that follows the policy."),)
        elif flagged := self.policy_issue_ads[campaign.id]:
            find = Step(
                text="Open Ads and search for each ad below. Fix the flagged text or the landing page, then save. "
                "Saving sends the ad to review again. A limited ad may need a certification from Google instead.",
                url=ADS_ADS_URL,
                linkText="Ads",
            )
            shown = flagged[:POLICY_ADS_SHOWN]
            headlines = Counter(ad.headline for ad in flagged)
            fix = tuple(_policy_fix(ad, headlines[ad.headline] > 1) for ad in shown)
            # Some affected ads come without findings, so the count comes from the approval totals.
            if (others := disapproved + limited - len(shown)) > 0:
                fix += (
                    Step(
                        text=f"Filter Ads by the status Disapproved or Eligible (limited) to find {others} more "
                        f"{'ad' if others == 1 else 'ads'}. Hover the status of each ad to see which policy it breaks."
                    ),
                )
        else:
            find = Step(
                text="Open Ads and filter by the status Disapproved or Eligible (limited). "
                "Hover the status of each ad to see which policy it breaks.",
                url=ADS_ADS_URL,
                linkText="Ads",
            )
            fix = (
                Step(
                    text="Edit the ad text or landing page so it follows the policy, then save. Saving sends the ad to review again."
                ),
            )
        steps = (
            self._open_campaign(campaign.name),
            find,
            *fix,
            Step(
                text="If a decision looks wrong, open Policy manager and appeal it from the Policy issues tab.",
                url=ADS_POLICY_ISSUES_URL,
                linkText="Policy manager",
            ),
            Step(text="Come back here after Google reviews the changes, usually within a business day."),
        )
        return self._campaign_recommendation(
            MarketingAnalyticsRecommendationRule.POLICY_LIMITED,
            campaign,
            "Fix or appeal the policy issues in this campaign",
            reason,
            None,
            "gain",
            "measured",
            steps=steps,
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
        detected_change: DetectedChange | None = None,
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
            detected_change=detected_change,
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
        detected_change: DetectedChange | None = None,
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
            minor=impact is not None and impact < MINOR_IMPACT_SHARE * self.monthly_spend,
            currency=self.inputs.currency,
            steps=list(steps),
            cpa=cpa,
            detectedChange=detected_change,
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

    def _cpa(self, value: float | None, benchmark: _Benchmark) -> MarketingAnalyticsRecommendationCpa:
        return MarketingAnalyticsRecommendationCpa(
            value=_round_money(value),
            benchmark=_round_money(benchmark.cpa),
            benchmarkSource=benchmark.source,
            bestCampaign=_round_money(self.best_campaign_cpa),
            worstCampaign=_round_money(self.worst_campaign_cpa),
        )

    def _money(self, amount: float) -> str:
        currency = self.inputs.currency or ""
        return f"${amount:,.0f}" if currency in ("USD", "") else f"{amount:,.0f} {currency}"


def _serves_search(channel_type: str | None, primary_status: str | None) -> bool:
    return channel_type == "SEARCH" and primary_status not in INACTIVE_STATUSES


def _passes_keyword(url_option: str | None) -> bool:
    return url_option is not None and KEYWORD_PARAMETER in url_option.lower()


def _round_money(amount: float | None) -> float | None:
    return round(amount, 2) if amount is not None else None
