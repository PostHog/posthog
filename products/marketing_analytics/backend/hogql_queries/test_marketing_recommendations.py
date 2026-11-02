from dataclasses import replace

from django.test import SimpleTestCase

from parameterized import parameterized

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations import (
    CampaignStats,
    OrganicQueryStats,
    RecommendationInputs,
    SearchTermStats,
    TermKeywordStats,
    brands_from_site_urls,
    recommend,
)


def _campaign(**overrides: object) -> CampaignStats:
    values: dict = {
        "id": "c1",
        "name": "Search",
        "channel_type": "SEARCH",
        "primary_status": "ELIGIBLE",
        "status_reasons": (),
        "daily_budget": 100.0,
        "recommended_daily_budget": None,
        "cost": 1000.0,
        "conversions": 10.0,
        "impression_share": 0.5,
        "lost_to_budget": 0.1,
        "lost_to_rank": 0.1,
        **overrides,
    }
    return CampaignStats(**values)


def _term(term: str, campaign_id: str, cost: float, conversions: float, clicks: float = 10) -> SearchTermStats:
    return SearchTermStats(
        term=term,
        campaign_id=campaign_id,
        clicks=clicks,
        impressions=100,
        cost=cost,
        conversions=conversions,
        status="NONE",
    )


def _inputs(
    campaigns: tuple[CampaignStats, ...] = (),
    terms: tuple[SearchTermStats, ...] = (),
    organic: tuple[OrganicQueryStats, ...] = (),
    term_keywords: tuple[TermKeywordStats, ...] = (),
) -> RecommendationInputs:
    return RecommendationInputs(
        term_keywords=term_keywords,
        campaigns=campaigns,
        search_terms=terms,
        organic_queries=organic,
        site_urls=("sc-domain:example.com",),
        currency="USD",
        days=30,
    )


class TestMarketingRecommendations(SimpleTestCase):
    @parameterized.expand(
        [
            ("google_recommends_more", ("BUDGET_CONSTRAINED",), "ELIGIBLE", 300.0, True),
            ("no_google_recommendation", ("BUDGET_CONSTRAINED",), "ELIGIBLE", None, False),
            ("not_budget_constrained", ("UNKNOWN",), "ELIGIBLE", 300.0, False),
            ("paused_campaign", ("BUDGET_CONSTRAINED",), "PAUSED", 300.0, False),
        ]
    )
    def test_budget_rule_needs_a_budget_limit_and_google_recommendation(
        self, _name: str, reasons: tuple[str, ...], status: str, recommended: float | None, expected: bool
    ) -> None:
        campaign = _campaign(status_reasons=reasons, primary_status=status, recommended_daily_budget=recommended)
        rules = [rec for rec in recommend(_inputs((campaign,))) if rec.rule == "budget_constrained"]
        assert bool(rules) == expected
        if expected:
            assert rules[0].action == "Raise the daily budget from $100 to $300"
            assert rules[0].impact == 6000

    def test_campaigns_sharing_a_budget_get_one_budget_recommendation(self) -> None:
        shared = {"status_reasons": ("BUDGET_CONSTRAINED",), "recommended_daily_budget": 300.0, "budget_id": "b1"}
        campaigns = (
            _campaign(id="c1", **shared),
            _campaign(id="c2", name="Search 2", **shared),
            _campaign(id="c3", name="Search 3", status_reasons=("BUDGET_CONSTRAINED",), recommended_daily_budget=200.0),
        )

        budget_rows = [rec for rec in recommend(_inputs(campaigns)) if rec.rule == "budget_constrained"]

        assert len(budget_rows) == 2

    @parameterized.expand(
        [
            ("domain_property", "sc-domain:example.com", {"example"}),
            ("url_prefix_subdomain", "https://app.example.com/", {"example"}),
            ("country_code_domain", "https://www.example.co.uk/", {"example"}),
            ("private_suffix", "https://example.github.io/", {"example"}),
            ("multi_label_suffix", "sc-domain:example.com.br", {"example"}),
            ("label_too_short_to_match_safely", "sc-domain:ab.io", set()),
        ]
    )
    def test_brand_comes_from_the_registrable_domain(self, _name: str, site_url: str, expected: set[str]) -> None:
        assert brands_from_site_urls([site_url]) == expected

    def test_brand_conversions_do_not_make_a_non_brand_campaign_look_cheap(self) -> None:
        brand_campaign = _campaign(id="brand", name="Brand", cost=500, conversions=100)
        cheap_looking = _campaign(
            id="generic", name="Generic", cost=2000, conversions=20, lost_to_budget=0.3, lost_to_rank=0.3
        )
        other = _campaign(id="other", name="Other", cost=3000, conversions=30)
        terms = (
            _term("example", "brand", cost=500, conversions=100),
            _term("example pricing", "generic", cost=800, conversions=18),
            _term("product analytics", "generic", cost=1200, conversions=2),
            _term("session replay", "other", cost=3000, conversions=30),
        )

        recs = recommend(_inputs((brand_campaign, cheap_looking, other), terms))

        leak = next(rec for rec in recs if rec.rule == "brand_leak")
        assert (leak.subject, leak.action) == ("Generic", 'Add "example" as a negative keyword')
        assert not any(rec.rule == "scale_campaign" and rec.subject == "Generic" for rec in recs)

    @parameterized.expand(
        [
            ("another_ad_often_shows_above", 0.6, "keep", "Keep the ad"),
            ("ad_owns_the_top_spot", 0.95, "save", "Test pausing"),
            ("top_spot_not_measured", None, "save", "Check whether other ads show above yours"),
        ]
    )
    def test_brand_overlap_keeps_the_ad_when_another_ad_shows_above(
        self, _name: str, absolute_top: float | None, direction: str, action_start: str
    ) -> None:
        brand = _campaign(id="brand", name="Brand")
        terms = (
            replace(_term("example", "brand", cost=1000, conversions=5), absolute_top_percentage=absolute_top),
            _term("analytics", "brand", cost=100, conversions=5),
        )
        organic = (OrganicQueryStats(query="example", clicks=500, impressions=1000, position=1.0),)

        overlap = [rec for rec in recommend(_inputs((brand,), terms, organic)) if rec.rule == "brand_overlap"]

        assert [(rec.subject, rec.impactDirection) for rec in overlap] == [("example", direction)]
        assert overlap[0].action.startswith(action_start)

    @parameterized.expand(
        [
            ("every_word_converts_cheaply", "funnel analysis", True),
            ("one_word_never_converted", "funnel spy", False),
            ("only_generic_words", "free online tool", False),
        ]
    )
    def test_keyword_gap_needs_every_meaningful_word_to_convert(self, _name: str, query: str, expected: bool) -> None:
        campaign = _campaign()
        terms = (
            _term("funnel tracking", "c1", cost=100, conversions=10),
            _term("analysis software", "c1", cost=100, conversions=10),
            _term("spy", "c1", cost=1000, conversions=1),
        )
        organic = tuple(OrganicQueryStats(query=f"filler {i}", clicks=1, impressions=1, position=50) for i in range(30))
        organic += (OrganicQueryStats(query=query, clicks=1, impressions=5000, position=25),)

        gaps = [rec.subject for rec in recommend(_inputs((campaign,), terms, organic)) if rec.rule == "keyword_gap"]

        assert (query in gaps) == expected

    def test_performance_max_gets_brand_exclusion_and_rank_advice(self) -> None:
        pmax = _campaign(
            id="pmax",
            name="PMax",
            channel_type="PERFORMANCE_MAX",
            status_reasons=("HAS_ASSET_GROUPS_LIMITED_BY_POLICY",),
            lost_to_rank=0.6,
        )
        terms = (
            _term("example", "pmax", cost=300, conversions=2),
            _term("project planning software", "pmax", cost=700, conversions=8),
        )

        actions = {
            (rec.rule.value, rec.action) for rec in recommend(_inputs((pmax,), terms)) if rec.level == "campaign"
        }

        assert actions == {
            ("brand_leak", 'Add a brand exclusion for "example"'),
            ("scale_campaign", "Raise the target CPA or improve its asset groups"),
            ("policy_limited", "Check the affected ads in Policy manager"),
        }

    @parameterized.expand(
        [
            (
                "broad",
                "BROAD",
                'Add it as a negative, or change the keyword "website traffic" from broad to exact match',
            ),
            (
                "phrase_enum_number",
                "3",
                'Add it as a negative, or change the keyword "website traffic" from phrase to exact match',
            ),
            ("exact", "EXACT", 'Review the keyword "website traffic" (exact match) and its landing page, or pause it'),
        ]
    )
    def test_spend_without_conversions_names_the_keyword_that_matched(
        self, _name: str, match_type: str, expected: str
    ) -> None:
        terms = (
            _term("spy website traffic", "c1", cost=500, conversions=0),
            _term("product analytics", "c1", cost=500, conversions=10),
        )
        keywords = (
            TermKeywordStats(term="spy website traffic", keyword="website traffic", match_type=match_type, cost=400),
            TermKeywordStats(term="spy website traffic", keyword="traffic", match_type="BROAD", cost=100),
        )

        actions = [
            rec.action
            for rec in recommend(_inputs((_campaign(),), terms, term_keywords=keywords))
            if rec.rule == "spend_without_conversions"
        ]

        assert actions == [expected]

    @parameterized.expand([("serving", "ELIGIBLE", 1), ("paused", "PAUSED", 0), ("removed", "REMOVED", 0)])
    def test_spend_without_conversions_skips_campaigns_that_do_not_serve(
        self, _name: str, status: str, expected: int
    ) -> None:
        campaigns = (_campaign(primary_status=status), _campaign(id="c2", name="Other"))
        terms = (
            _term("free analytics template", "c1", cost=500, conversions=0),
            _term("product analytics", "c2", cost=500, conversions=10),
        )

        rows = [rec for rec in recommend(_inputs(campaigns, terms)) if rec.rule == "spend_without_conversions"]

        assert len(rows) == expected

    def test_category_words_are_not_treated_as_competitors(self) -> None:
        terms = (
            _term("trackly logs", "c1", cost=500, conversions=0),
            _term("app analytics", "c1", cost=500, conversions=0),
            _term("product analytics", "c1", cost=500, conversions=10),
        )
        comparisons = ("trackly alternatives", "trackly vs zentrix", "analytics alternatives", "analytics vs bi")
        everyday = tuple(f"analytics report {i}" for i in range(60))
        organic = tuple(
            OrganicQueryStats(query=query, clicks=1, impressions=10, position=30)
            for query in (*comparisons, *everyday, "trackly", "analytics")
        )

        actions = {
            rec.subject: rec.action
            for rec in recommend(_inputs((_campaign(),), terms, organic))
            if rec.rule == "spend_without_conversions"
        }

        assert actions == {
            "trackly logs": "Competitor term: decide whether conquesting is worth it.",
            "app analytics": "Review the bid and landing page, or add it as a negative",
        }
