from dataclasses import replace

from django.test import SimpleTestCase

from parameterized import parameterized

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations import (
    SEARCH_CONSOLE_PERFORMANCE_URL,
    CampaignStats,
    KeywordTracking,
    OrganicQueryStats,
    RankingPage,
    RecommendationInputs,
    SearchTermStats,
    TermKeywordStats,
    brands_from_site_urls,
    dedupe_account_agnostic_rules,
    recommend,
)
from products.marketing_analytics.backend.hogql_queries.recommendation_identity import validate_identity


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
    ranking_pages: tuple[RankingPage, ...] = (),
) -> RecommendationInputs:
    return RecommendationInputs(
        term_keywords=term_keywords,
        ranking_pages=ranking_pages,
        campaigns=campaigns,
        search_terms=terms,
        organic_queries=organic,
        site_urls=("sc-domain:example.com",),
        currency="USD",
        days=30,
        customer_id="1234567890",
    )


class TestMarketingRecommendations(SimpleTestCase):
    @parameterized.expand(
        [
            ("cpa_below_target", ("BUDGET_CONSTRAINED",), "ELIGIBLE", 300.0, {"target_cpa": 200.0}, (), True),
            ("no_google_recommendation", ("BUDGET_CONSTRAINED",), "ELIGIBLE", None, {}, (), False),
            ("not_budget_constrained", ("UNKNOWN",), "ELIGIBLE", 300.0, {}, (), False),
            ("paused_campaign", ("BUDGET_CONSTRAINED",), "PAUSED", 300.0, {}, (), False),
            ("cpa_above_target", ("BUDGET_CONSTRAINED",), "ELIGIBLE", 300.0, {"target_cpa": 50.0}, (), False),
            (
                "brand_campaign",
                ("BUDGET_CONSTRAINED",),
                "ELIGIBLE",
                300.0,
                {"target_cpa": 200.0},
                (_term("example login", "c1", 1000, 10),),
                False,
            ),
        ]
    )
    def test_budget_rule_needs_a_budget_limit_google_recommendation_and_cpa_within_benchmark(
        self,
        _name: str,
        reasons: tuple[str, ...],
        status: str,
        recommended: float | None,
        overrides: dict[str, object],
        terms: tuple[SearchTermStats, ...],
        expected: bool,
    ) -> None:
        campaign = _campaign(
            status_reasons=reasons, primary_status=status, recommended_daily_budget=recommended, **overrides
        )
        rules = [rec for rec in recommend(_inputs((campaign,), terms)) if rec.rule == "budget_constrained"]
        assert bool(rules) == expected
        if expected:
            assert rules[0].action == "Raise the daily budget from $100 to $300"
            assert rules[0].impact == 6000
            assert rules[0].cpa is not None
            assert (rules[0].cpa.value, rules[0].cpa.benchmark) == (100, 200)

    @parameterized.expand(
        [
            (
                "cheap_campaign_losing_impressions",
                "Cheap",
                None,
                "scale_campaign",
                50.0,
                133.33,
                "account",
                "at or below the account's",
            ),
            ("expensive_campaign", "Expensive", None, "review_campaign", 600.0, 133.33, "account", "4.5x"),
            ("bids_to_a_target_cpa", "Expensive", 150.0, "review_campaign", 600.0, 150.0, "target_cpa", "4.0x"),
        ]
    )
    def test_campaign_cpa_fields_and_reason_name_the_benchmark(
        self,
        _name: str,
        subject: str,
        target_cpa: float | None,
        rule: str,
        value: float,
        benchmark: float,
        source: str,
        reason_benchmark: str,
    ) -> None:
        campaigns = (
            _campaign(id="a", name="Cheap", cost=1000, conversions=20, lost_to_budget=0.3, lost_to_rank=0.2),
            _campaign(id="b", name="Expensive", cost=3000, conversions=5, target_cpa=target_cpa),
            _campaign(id="c", name="Average", cost=2000, conversions=20),
        )

        rec = next(rec for rec in recommend(_inputs(campaigns)) if rec.subject == subject)

        assert rec.rule == rule
        assert rec.cpa is not None
        assert rec.cpa.model_dump(mode="json") == {
            "value": value,
            "benchmark": benchmark,
            "benchmarkSource": source,
            "bestCampaign": 50.0,
            "worstCampaign": 600.0,
        }
        assert reason_benchmark in rec.reason

    @parameterized.expand(
        [
            ("spent_less_than_the_bar", 200.0, 0.0, None),
            (
                "spent_past_the_bar",
                360.0,
                0.0,
                "Spent $360 (4.3x the account's non-brand CPA) with no non-brand conversions.",
            ),
            ("only_brand_spend_past_the_bar", 360.0, 160.0, None),
        ]
    )
    def test_campaign_without_conversions_needs_enough_spend_to_review(
        self, _name: str, cost: float, brand_cost: float, reason: str | None
    ) -> None:
        campaigns = (
            _campaign(id="a", name="Converting", cost=1000, conversions=20),
            _campaign(id="b", name="Silent", cost=cost, conversions=0),
            _campaign(id="c", name="Average", cost=2000, conversions=20),
        )
        terms = (
            (
                _term("example", "b", cost=brand_cost, conversions=0),
                _term("other", "b", cost=cost - brand_cost, conversions=0),
            )
            if brand_cost
            else ()
        )

        reviews = [rec for rec in recommend(_inputs(campaigns, terms)) if rec.rule == "review_campaign"]

        pause = (
            "If after two weeks it still has no non-brand conversions, or its non-brand CPA is more than 3x "
            "the account's non-brand CPA, pause it in Campaigns."
        )
        assert [(rec.subject, rec.reason, (rec.steps or [])[-1].text) for rec in reviews] == (
            [("Silent", reason, pause)] if reason else []
        )

    def test_conversions_without_cost_leave_no_benchmark(self) -> None:
        campaigns = (
            _campaign(id="c1", cost=0, conversions=20),
            _campaign(id="c2", name="Other", cost=500, conversions=0, channel_type="PERFORMANCE_MAX"),
        )
        terms = (_term("free", "c1", cost=0, conversions=20), _term("waste", "c2", cost=500, conversions=0))

        recs = recommend(_inputs(campaigns, terms))

        assert all(rec.cpa is None or rec.cpa.benchmark is None for rec in recs)

    @parameterized.expand(
        [
            ("few_conversions_use_the_account", 10, None, 100.0, "account", "3.0x the account's non-brand CPA"),
            ("enough_conversions_use_the_campaign", 20, None, 50.0, "campaign", "6.0x the campaign's non-brand CPA"),
            ("target_cpa_wins", 20, 120.0, 120.0, "target_cpa", "2.5x the campaign's target CPA"),
            (
                "performance_max_only_account",
                10,
                None,
                100.0,
                "account",
                "3.0x the account's non-brand CPA",
                "PERFORMANCE_MAX",
            ),
        ]
    )
    def test_search_terms_are_judged_against_their_campaigns_benchmark(
        self,
        _name: str,
        conversions: float,
        target_cpa: float | None,
        benchmark: float,
        source: str,
        reason: str,
        channel: str = "SEARCH",
    ) -> None:
        campaigns = (
            _campaign(id="brand", name="Brand", cost=100, conversions=100),
            _campaign(id="c1", cost=1000, conversions=conversions, target_cpa=target_cpa, channel_type=channel),
            _campaign(id="c2", name="Other", cost=1000, conversions=20 - conversions, channel_type=channel),
        )
        terms = (
            _term("example", "brand", cost=100, conversions=100),
            _term("converter", "c1", cost=700, conversions=conversions),
            _term("waste", "c1", cost=300, conversions=0),
        )

        waste = next(rec for rec in recommend(_inputs(campaigns, terms)) if rec.subject == "waste")

        assert waste.rule == "spend_without_conversions"
        assert waste.cpa is not None
        assert (waste.cpa.benchmark, waste.cpa.benchmarkSource) == (benchmark, source)
        assert reason in waste.reason

    def test_campaigns_sharing_a_budget_get_one_budget_recommendation(self) -> None:
        shared = {"status_reasons": ("BUDGET_CONSTRAINED",), "recommended_daily_budget": 300.0, "budget_id": "b1"}
        campaigns = (
            _campaign(id="c2", name="Search 2", **shared),
            _campaign(id="c1", **shared),
            _campaign(id="c3", name="Search 3", status_reasons=("BUDGET_CONSTRAINED",), recommended_daily_budget=200.0),
        )

        budget_rows = [rec for rec in recommend(_inputs(campaigns)) if rec.rule == "budget_constrained"]

        assert [(rec.subject, rec.identity.campaign_id, rec.identity.subject) for rec in budget_rows] == [
            ("Search", "", "b1"),
            ("Search 3", "c3", ""),
        ]

    @parameterized.expand(
        [
            (
                "campaign_renamed",
                (_campaign(name="Search", status_reasons=("HAS_ADS_DISAPPROVED",)),),
                (_campaign(name="Search 2026", status_reasons=("HAS_ADS_DISAPPROVED",)),),
                (),
                (),
                ("policy_limited", "1234567890", "c1", ""),
            ),
            (
                "another_campaign_spends_most_on_the_term_in_the_new_range",
                (_campaign(), _campaign(id="c2", name="Replay")),
                (_campaign(), _campaign(id="c2", name="Replay")),
                (_term("spy website traffic", "c1", 500, 0), _term("product analytics", "c1", 500, 10)),
                (_term("spy website traffic", "c2", 500, 0), _term("product analytics", "c1", 500, 10)),
                ("spend_without_conversions", "1234567890", "", "spy website traffic"),
            ),
        ]
    )
    def test_identity_stays_the_same_across_runs(
        self,
        _name: str,
        campaigns_before: tuple[CampaignStats, ...],
        campaigns_after: tuple[CampaignStats, ...],
        terms_before: tuple[SearchTermStats, ...],
        terms_after: tuple[SearchTermStats, ...],
        expected: tuple[str, str, str, str],
    ) -> None:
        rule = expected[0]
        before, after = (
            [rec for rec in recommend(_inputs(campaigns, terms)) if rec.rule == rule]
            for campaigns, terms in ((campaigns_before, terms_before), (campaigns_after, terms_after))
        )

        identity = [
            (rec.identity.rule, rec.identity.customer_id, rec.identity.campaign_id, rec.identity.subject)
            for rec in before
        ]
        assert identity == [expected]
        assert [rec.key for rec in before] == [rec.key for rec in after]
        for rec in before:
            validate_identity(rec.identity)

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
        assert [step.copyValue for step in leak.steps or [] if step.copyValue] == ["Generic", '"example"']
        assert not any(rec.rule == "scale_campaign" and rec.subject == "Generic" for rec in recs)

    def test_review_campaign_steps_start_with_the_searches_that_waste_spend(self) -> None:
        good = _campaign(id="c1", name="Good", cost=1000, conversions=10)
        costly = _campaign(id="c2", name="Costly", cost=2000, conversions=2)
        terms = (
            _term("product analytics", "c1", cost=1000, conversions=10),
            _term("drain small", "c2", cost=300, conversions=0),
            _term("drain big", "c2", cost=400, conversions=0),
            _term("drain too small", "c2", cost=20, conversions=0),
            replace(_term("already a keyword", "c2", cost=500, conversions=0), status="ADDED"),
            _term("example login", "c2", cost=600, conversions=0),
            _term("cheap keeper", "c2", cost=50, conversions=1),
            replace(_term("cheap but excluded", "c2", cost=40, conversions=1), status="EXCLUDED"),
            _term("costly converter", "c2", cost=300, conversions=1),
        )

        review = next(rec for rec in recommend(_inputs((good, costly), terms)) if rec.rule == "review_campaign")

        steps = review.steps or []
        assert review.subject == "Costly"
        assert [step.copyValue for step in steps if step.copyValue] == ["Costly", "[drain big]\n[drain small]"]
        assert '"cheap keeper"' in steps[2].text
        assert "costly converter" not in steps[2].text and "cheap but excluded" not in steps[2].text
        assert all(step.linkText and step.linkText in step.text for step in steps if step.url)

    @parameterized.expand(
        [
            ("near_top_3_with_known_page", 8.0, True, "striking_distance", "https://example.com/funnels"),
            (
                "near_top_3_without_page_table",
                8.0,
                False,
                "striking_distance",
                f"{SEARCH_CONSOLE_PERFORMANCE_URL}?resource_id=sc-domain%3Aexample.com",
            ),
            ("ranks_beyond_page_one", 30.0, True, "content_gap", "https://example.com/funnels"),
            ("does_not_rank", None, True, "content_gap", None),
        ]
    )
    def test_organic_steps_start_from_the_page_that_ranks(
        self, _name: str, position: float | None, has_pages: bool, rule: str, first_url: str | None
    ) -> None:
        terms = (
            _term("funnel analysis", "c1", cost=100, conversions=5),
            _term("session replay", "c1", cost=900, conversions=5),
        )
        organic = (
            (OrganicQueryStats(query="funnel analysis", clicks=20, impressions=2000, position=position),)
            if position
            else ()
        )
        pages = (
            RankingPage(query="funnel analysis", page="https://example.com/blog", impressions=300),
            RankingPage(query="funnel analysis", page="https://example.com/funnels", impressions=1700),
        )

        recs = recommend(_inputs((_campaign(),), terms, organic, ranking_pages=pages if has_pages else ()))

        organic_recs = [rec for rec in recs if rec.subject == "funnel analysis" and rec.rule == rule]
        assert len(organic_recs) == 1
        steps = organic_recs[0].steps or []
        assert steps[0].url == first_url
        if first_url is None:
            assert steps[0].text.startswith("Create a page")
        assert all(step.linkText and step.linkText in step.text for step in steps if step.url)

    @parameterized.expand(
        [
            ("page_two_is_only_striking_distance", 15.0, 2000, {"striking_distance"}),
            ("page_two_with_few_impressions_is_a_content_gap", 15.0, 20, {"content_gap"}),
            ("page_one_with_few_impressions_is_neither", 8.0, 20, set()),
        ]
    )
    def test_a_ranking_search_gets_one_organic_rule(
        self, _name: str, position: float, impressions: float, expected: set[str]
    ) -> None:
        terms = (
            _term("funnel analysis", "c1", cost=100, conversions=5),
            _term("session replay", "c1", cost=900, conversions=5),
        )
        organic = (OrganicQueryStats(query="funnel analysis", clicks=1, impressions=impressions, position=position),)

        recs = recommend(_inputs((_campaign(),), terms, organic))

        organic_recs = [rec for rec in recs if rec.rule in ("content_gap", "striking_distance")]
        assert {rec.rule for rec in organic_recs if rec.subject == "funnel analysis"} == expected
        assert all(rec.identity.customer_id == rec.identity.campaign_id == "" for rec in organic_recs)
        other_account = recommend(replace(_inputs((_campaign(),), terms, organic), customer_id="9876543210"))
        merged = [
            rec.rule for rec in dedupe_account_agnostic_rules(recs + other_account) if rec.subject == "funnel analysis"
        ]
        assert sorted(merged) == sorted(expected)
        assert all(rec.cpa is None for rec in recs if rec.rule == "striking_distance")

    @parameterized.expand(
        [
            ("another_ad_often_shows_above", 0.6, "keep", "Keep the ad"),
            ("ad_owns_the_top_spot", 0.95, "save", "Test pausing"),
            ("top_spot_not_measured", None, "save", "Check whether other ads show above yours"),
            ("account_without_conversions", 0.6, "keep", "Keep the ad", 0),
        ]
    )
    def test_brand_overlap_keeps_the_ad_when_another_ad_shows_above(
        self, _name: str, absolute_top: float | None, direction: str, action_start: str, conversions: float = 5
    ) -> None:
        brand = _campaign(id="brand", name="Brand")
        terms = (
            replace(
                _term("example", "brand", cost=1000, conversions=conversions), absolute_top_percentage=absolute_top
            ),
            _term("analytics", "brand", cost=100, conversions=conversions),
        )
        organic = (OrganicQueryStats(query="example", clicks=500, impressions=1000, position=1.0),)

        overlap = [rec for rec in recommend(_inputs((brand,), terms, organic)) if rec.rule == "brand_overlap"]

        assert [(rec.subject, rec.impactDirection) for rec in overlap] == [("example", direction)]
        assert overlap[0].action.startswith(action_start)
        assert overlap[0].cpa is None

    @parameterized.expand(
        [
            ("every_word_converts_cheaply", "funnel analysis", True),
            ("one_word_never_converted", "funnel spy", False),
            ("only_generic_words", "free online tool", False),
        ]
    )
    def test_keyword_gap_needs_every_meaningful_word_to_convert(self, _name: str, query: str, expected: bool) -> None:
        campaigns = (_campaign(id="c2", name="Replay"), _campaign())
        terms = (
            _term("funnel tracking", "c1", cost=100, conversions=10),
            _term("analysis software", "c1", cost=100, conversions=10),
            _term("spy", "c1", cost=1000, conversions=1),
            _term("session replay", "c2", cost=100, conversions=10),
        )
        organic = tuple(OrganicQueryStats(query=f"filler {i}", clicks=1, impressions=1, position=50) for i in range(30))
        organic += (OrganicQueryStats(query=query, clicks=1, impressions=5000, position=25),)

        gaps = {
            rec.subject: (rec.campaign, rec.identity.customer_id, rec.identity.campaign_id)
            for rec in recommend(_inputs(campaigns, terms, organic))
            if rec.rule == "keyword_gap"
        }

        assert (query in gaps) == expected
        if expected:
            assert gaps[query] == ("Search", "", "")

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

        recs = [rec for rec in recommend(_inputs((pmax,), terms)) if rec.level == "campaign"]

        assert {(rec.rule.value, rec.action) for rec in recs} == {
            ("brand_leak", 'Add a brand exclusion for "example"'),
            ("scale_campaign", "Raise the target CPA or improve its asset groups"),
            ("policy_limited", "Check the affected ads in Policy manager"),
        }
        assert all(rec.cpa is None for rec in recs)
        leak = next(rec for rec in recs if rec.rule == "brand_leak")
        assert [step.copyValue for step in leak.steps or [] if step.copyValue] == ["PMax", "example"]

    @parameterized.expand(
        [
            (
                "broad",
                "BROAD",
                'Add it as a negative, or change the keyword "website traffic" from broad to exact match',
                [
                    ("Search", "campaigns"),
                    ("[spy website traffic]", "keywords/negative"),
                    ("website traffic", "keywords"),
                ],
            ),
            (
                "phrase_enum_number",
                "3",
                'Add it as a negative, or change the keyword "website traffic" from phrase to exact match',
                [
                    ("Search", "campaigns"),
                    ("[spy website traffic]", "keywords/negative"),
                    ("website traffic", "keywords"),
                ],
            ),
            (
                "exact",
                "EXACT",
                'Review the keyword "website traffic" (exact match) and its landing page, or pause it',
                [("Search", "campaigns"), ("website traffic", "keywords")],
            ),
        ]
    )
    def test_spend_without_conversions_names_the_keyword_that_matched(
        self, _name: str, match_type: str, expected: str, expected_copy: list[tuple[str, str]]
    ) -> None:
        terms = (
            _term("spy website traffic", "c1", cost=500, conversions=0),
            _term("product analytics", "c1", cost=500, conversions=10),
        )
        keywords = (
            TermKeywordStats(term="spy website traffic", keyword="website traffic", match_type=match_type, cost=400),
            TermKeywordStats(term="spy website traffic", keyword="traffic", match_type="BROAD", cost=100),
        )

        recs = [
            rec
            for rec in recommend(_inputs((_campaign(),), terms, term_keywords=keywords))
            if rec.rule == "spend_without_conversions"
        ]

        assert [(rec.action, rec.campaign, rec.identity.campaign_id) for rec in recs] == [(expected, "Search", "")]
        assert [
            (step.copyValue, (step.url or "").removeprefix("https://ads.google.com/aw/"))
            for step in recs[0].steps or []
            if step.copyValue
        ] == expected_copy
        assert all(step.linkText and step.linkText in step.text for step in recs[0].steps or [] if step.url)

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

    @parameterized.expand(
        [
            ("keyword_missing", {}, {}, True),
            (
                "set_in_the_account_suffix",
                {"account_final_url_suffix": "utm_source=google&utm_term={keyword}"},
                {},
                False,
            ),
            ("passed_under_another_name", {"account_final_url_suffix": "kw={keyword}"}, {}, True),
            ("set_in_the_account_template", {"account_tracking_url_template": "{lpurl}?utm_term={keyword}"}, {}, False),
            (
                "campaign_template_replaces_the_accounts",
                {"account_tracking_url_template": "{lpurl}?utm_term={keyword}"},
                {"tracking_url_template": "{lpurl}?utm_source=google"},
                True,
            ),
            ("set_on_every_search_campaign", {}, {"tracking_url_template": "{lpurl}?utm_term={keyword}"}, False),
            ("most_sessions_carry_it", {"sessions_with_keyword": 40}, {}, False),
            ("too_few_sessions", {"sessions": 20, "sessions_with_keyword": 0}, {}, False),
            ("no_search_campaign", {}, {"channel_type": "PERFORMANCE_MAX"}, False),
            ("search_campaign_paused", {}, {"primary_status": "PAUSED"}, False),
        ]
    )
    def test_keyword_tracking_needs_search_ads_sessions_without_utm_term(
        self, _name: str, tracking: dict[str, object], campaign: dict[str, object], expected: bool
    ) -> None:
        values: dict = {"account_name": "Acme Ads", "sessions": 400, "sessions_with_keyword": 4, **tracking}
        inputs = replace(_inputs((_campaign(**campaign),)), keyword_tracking=KeywordTracking(**values))

        rows = [rec for rec in recommend(inputs) if rec.rule == "keyword_tracking"]

        assert [(rec.level, rec.subject, rec.reason[:4]) for rec in rows] == (
            [("account", "Acme Ads", "99% ")] if expected else []
        )
        if expected:
            assert [step.copyValue for step in rows[0].steps or [] if step.copyValue] == ["utm_term={keyword}"]
