from dataclasses import replace

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import MarketingAnalyticsRecommendationResolution

from products.marketing_analytics.backend.hogql_queries.marketing_recommendations import (
    PER_RULE_LIMIT,
    SEARCH_CONSOLE_PERFORMANCE_URL,
    SEARCH_CONSOLE_URL,
    Ad,
    CampaignStats,
    ExcludedSearch,
    Keyword,
    KeywordTracking,
    OrganicQueryStats,
    PolicyAds,
    RankingPage,
    RecommendationInputs,
    SearchTermStats,
    TermKeywordStats,
    apply_resolutions,
    brands_from_site_urls,
    dedupe_account_agnostic_rules,
    recommend,
)
from products.marketing_analytics.backend.hogql_queries.recommendation_identity import validate_identity

COPY = ("Product analytics for teams", "Understand your users")


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


def _term(
    term: str, campaign_id: str, cost: float, conversions: float, clicks: float = 10, impressions: float = 100
) -> SearchTermStats:
    return SearchTermStats(
        term=term,
        campaign_id=campaign_id,
        clicks=clicks,
        impressions=impressions,
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
    keywords: tuple[Keyword, ...] = (),
) -> RecommendationInputs:
    return RecommendationInputs(
        keywords=keywords,
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
            steps = rules[0].steps or []
            assert [step.copyValue for step in steps if step.copyValue][-1] == "300"
            assert all(step.linkText and step.linkText in step.text for step in steps if step.url)

    @parameterized.expand(
        [
            ("under_one_percent_of_account_spend", 500.0, True),
            ("one_percent_or_more", 1000.0, False),
        ]
    )
    def test_minor_marks_impact_under_one_percent_of_monthly_account_spend(
        self, _name: str, wasted: float, expected: bool
    ) -> None:
        campaign = _campaign(cost=100000, conversions=1000, status_reasons=("HAS_ADS_DISAPPROVED",))
        terms = (_term("product analytics", "c1", 99000, 1000), _term("waste", "c1", wasted, 0))
        inputs = replace(_inputs((campaign,), terms), days=15)

        recs = {rec.rule.value: rec for rec in recommend(inputs)}

        assert (recs["spend_without_conversions"].impact, recs["spend_without_conversions"].minor) == (
            wasted * 2,
            expected,
        )
        assert recs["policy_limited"].minor is False

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
        assert rec.steps
        assert all(step.linkText and step.linkText in step.text for step in rec.steps if step.url)

    @parameterized.expand(
        [
            ("loses_more_to_budget", 0.3, 0.2, None, "Click its budget"),
            ("loses_more_to_rank", 0.1, 0.4, None, "raise the bids"),
            ("loses_more_to_rank_on_a_target_cpa", 0.1, 0.4, 100.0, "raise the target CPA"),
        ]
    )
    def test_scale_campaign_step_matches_what_limits_it(
        self, _name: str, lost_to_budget: float, lost_to_rank: float, target_cpa: float | None, expected: str
    ) -> None:
        campaigns = (
            _campaign(
                id="a",
                name="Cheap",
                cost=1000,
                conversions=20,
                lost_to_budget=lost_to_budget,
                lost_to_rank=lost_to_rank,
                target_cpa=target_cpa,
            ),
            _campaign(id="b", name="Expensive", cost=3000, conversions=5),
            _campaign(id="c", name="Average", cost=2000, conversions=20),
        )

        rec = next(rec for rec in recommend(_inputs(campaigns)) if rec.rule == "scale_campaign")

        assert expected in (rec.steps or [])[1].text

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

    def test_per_rule_limit_shows_the_top_unresolved_recommendations(self) -> None:
        terms = (
            *(_term(f"waste term {i:02d}", "c1", cost=500 + i, conversions=0) for i in range(12)),
            _term("product analytics", "c1", cost=500, conversions=100),
        )
        candidates = recommend(_inputs((_campaign(),), terms))

        def wasted(
            resolutions: dict[str, MarketingAnalyticsRecommendationResolution], include_resolved: bool
        ) -> list[tuple[str, str | None]]:
            return [
                (rec.subject, rec.resolution.resolution if rec.resolution else None)
                for rec in apply_resolutions(candidates, resolutions, include_resolved=include_resolved)
                if rec.rule == "spend_without_conversions"
            ]

        first = wasted({}, include_resolved=False)
        assert len(first) == 10
        dismissed = {
            rec.key: MarketingAnalyticsRecommendationResolution(
                id=str(i), resolution="dismissed", resolved_at="2026-01-01T00:00:00+00:00"
            )
            for i, rec in enumerate(candidates)
            if (rec.subject, None) in first
        }

        assert wasted(dismissed, include_resolved=False) == [("waste term 01", None), ("waste term 00", None)]
        annotated = wasted(dismissed, include_resolved=True)
        assert annotated[:2] == [("waste term 01", None), ("waste term 00", None)]
        assert sorted(annotated[2:]) == sorted((subject, "dismissed") for subject, _ in first)

        organic = tuple(
            OrganicQueryStats(query=f"{word} analysis", clicks=20, impressions=2000, position=12.0)
            for word in (
                *("funnel", "cohort", "retention", "trend", "path", "lifecycle"),
                *("stickiness", "survey", "experiment", "heatmap", "replay", "warehouse"),
            )
        )
        cheap_account = recommend(
            _inputs(
                (_campaign(),),
                tuple(_term(query.query, "c1", cost=100, conversions=5) for query in organic[:6]),
                organic,
            )
        )
        costly_account = recommend(
            replace(
                _inputs(
                    (_campaign(),),
                    tuple(_term(query.query, "c1", cost=900, conversions=5) for query in organic[6:]),
                    organic,
                ),
                customer_id="9876543210",
            )
        )
        striking = [
            rec.subject
            for rec in apply_resolutions(
                dedupe_account_agnostic_rules(cheap_account + costly_account), {}, include_resolved=False
            )
            if rec.rule == "striking_distance"
        ]
        assert len(striking) == 10
        assert {query.query for query in organic[6:]} <= set(striking)

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

    @parameterized.expand(
        [
            ("misspelling_is_blocked_too", "NONE", '"example"\n"exampel"'),
            ("misspelling_bought_on_purpose", "ADDED", '"example"'),
        ]
    )
    def test_brand_leak_negates_the_brand_when_the_top_search_is_a_misspelling(
        self, _name: str, misspelling_status: str, negatives: str
    ) -> None:
        campaign = _campaign(id="generic", name="Generic", cost=2000, conversions=20)
        terms = (
            replace(_term("exampel", "generic", cost=600, conversions=1), status=misspelling_status),
            _term("example pricing", "generic", cost=200, conversions=1),
            _term("analytics tool", "generic", cost=100, conversions=1),
            _term("product analytics", "generic", cost=1200, conversions=18),
        )
        # A generic search the site ranks first for also counts as brand, but it is no misspelling.
        organic = (
            OrganicQueryStats(query="exampel", clicks=100, impressions=200, position=1.0),
            OrganicQueryStats(query="analytics tool", clicks=90, impressions=200, position=1.0),
        )

        recs = recommend(_inputs((campaign,), terms, organic))

        leak = next(rec for rec in recs if rec.rule == "brand_leak")
        assert leak.action == 'Add "example" as a negative keyword'
        assert [step.copyValue for step in leak.steps or [] if step.copyValue] == ["Generic", negatives]

    def test_brand_leaking_in_several_campaigns_gets_one_shared_negative_list(self) -> None:
        campaigns = (
            _campaign(id="a", name="Alpha", cost=2000, conversions=20),
            _campaign(id="b", name="Beta", cost=2000, conversions=20),
            _campaign(id="pmax", name="PMax", channel_type="PERFORMANCE_MAX", cost=1000, conversions=10),
        )
        terms = (
            _term("example pricing", "a", cost=300, conversions=1),
            _term("product analytics", "a", cost=1700, conversions=19),
            _term("example login", "b", cost=500, conversions=1),
            _term("session replay", "b", cost=1500, conversions=19),
            _term("example", "pmax", cost=200, conversions=1),
            _term("project planning software", "pmax", cost=800, conversions=9),
        )

        leaks = [rec for rec in recommend(_inputs(campaigns, terms)) if rec.rule == "brand_leak"]

        assert sorted((rec.level, rec.subject, rec.action) for rec in leaks) == [
            ("account", "2 non-brand campaigns", 'Add "example" to a shared negative keyword list'),
            ("campaign", "PMax", 'Add a brand exclusion for "example"'),
        ]
        shared = next(rec for rec in leaks if rec.level == "account")
        assert [step.copyValue for step in shared.steps or [] if step.copyValue] == ['"example"', "Beta\nAlpha"]
        assert (shared.identity.campaign_id, shared.identity.subject) == ("", "example")
        validate_identity(shared.identity)

    @parameterized.expand(
        [
            ("negated_in_both", ("EXCLUDED", "EXCLUDED"), "NONE", ["brand_negative"]),
            ("one_campaign_still_serves_it", ("EXCLUDED", "NONE"), "NONE", [None]),
            ("added_then_excluded_counts", ("EXCLUDED", "ADDED_EXCLUDED"), "NONE", ["brand_negative"]),
            ("misspelling_negated_too", ("EXCLUDED", "EXCLUDED"), "EXCLUDED", ["brand_negative"]),
            ("single_campaign_negated", ("EXCLUDED", None), "NONE", ["brand_negative"]),
        ]
    )
    def test_brand_leak_is_applied_once_the_brand_is_negated_in_every_leaking_campaign(
        self, _name: str, statuses: tuple[str, str | None], misspelling_status: str, expected: list[str | None]
    ) -> None:
        campaigns = (
            _campaign(id="a", name="Alpha", cost=2000, conversions=20),
            _campaign(id="b", name="Beta", cost=2000, conversions=20),
        )
        terms: tuple[SearchTermStats, ...] = (
            replace(_term("example pricing", "a", cost=300, conversions=1), status=statuses[0]),
            replace(_term("exampel", "a", cost=20, conversions=0), status=misspelling_status),
            _term("product analytics", "a", cost=1700, conversions=19),
            _term("session replay", "b", cost=1500, conversions=19),
        )
        if statuses[1] is not None:
            terms += (replace(_term("example login", "b", cost=500, conversions=1), status=statuses[1]),)
        excluded = frozenset(
            ExcludedSearch(term=term.term, campaign_id=term.campaign_id) for term in terms if "EXCLUDED" in term.status
        )

        recs = recommend(replace(_inputs(campaigns, terms), excluded_searches=excluded))

        leaks = [rec for rec in recs if rec.rule == "brand_leak"]
        assert [rec.detectedChange for rec in leaks] == expected
        assert len(apply_resolutions(recs, {}, include_resolved=False)) == len(recs) - (expected != [None])

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
            _term("cheap but excluded", "c2", cost=40, conversions=1),
            _term("costly converter", "c2", cost=300, conversions=1),
        )
        inputs = replace(
            _inputs((good, costly), terms),
            excluded_searches=frozenset({ExcludedSearch(term="cheap but excluded", campaign_id="c2")}),
        )

        review = next(rec for rec in recommend(inputs) if rec.rule == "review_campaign")

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
            (
                "several_properties_open_the_last_one_viewed",
                8.0,
                False,
                "striking_distance",
                SEARCH_CONSOLE_URL,
                ("sc-domain:example.com", "https://example.com/"),
            ),
            ("ranks_beyond_page_one", 30.0, True, "content_gap", "https://example.com/funnels"),
            ("does_not_rank", None, True, "content_gap", None),
        ]
    )
    def test_organic_steps_start_from_the_page_that_ranks(
        self,
        _name: str,
        position: float | None,
        has_pages: bool,
        rule: str,
        first_url: str | None,
        site_urls: tuple[str, ...] = ("sc-domain:example.com",),
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

        inputs = _inputs((_campaign(),), terms, organic, ranking_pages=pages if has_pages else ())
        recs = recommend(replace(inputs, site_urls=site_urls))

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

    def test_content_gap_impact_is_the_ad_spend_a_top_3_page_replaces(self) -> None:
        terms = (
            _term("funnel analysis", "c1", cost=300, conversions=5, clicks=60, impressions=200),
            _term("cohort analysis", "c1", cost=300, conversions=5, clicks=60, impressions=1000),
            _term("session replay", "c1", cost=400, conversions=0),
        )

        gaps = {
            rec.subject: (rec.impact, rec.impactDirection, rec.impactType)
            for rec in recommend(_inputs((_campaign(),), terms))
            if rec.rule == "content_gap"
        }

        assert gaps == {
            "funnel analysis": (150, "gain", "estimated"),
            "cohort analysis": (300, "gain", "estimated"),
        }

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
            ("every_word_converts_cheaply", "funnel analysis", "Search"),
            ("one_word_never_converted", "funnel spy", None),
            ("only_generic_words", "free online tool", None),
            ("ranks_on_a_landing_page_of_the_ads", "funnel spy", "Replay", "https://www.example.com/replay/"),
            ("landing_page_of_a_paused_campaign", "funnel spy", None, "https://example.com/replay", None, "PAUSED"),
            (
                "landing_page_of_a_campaign_up_for_review",
                "funnel spy",
                None,
                "https://example.com/replay",
                None,
                "ELIGIBLE",
                1,
            ),
            (
                "landing_page_with_click_tags",
                "funnel spy",
                "Replay",
                "https://example.com/replay?utm_source=google&gad_source=1&gclid=abc",
            ),
            ("same_path_with_a_different_page_parameter", "funnel spy", None, "https://example.com/replay?id=200"),
            ("page_parameter_in_a_different_case", "funnel spy", None, "https://example.com/replay?id=ABC"),
            (
                "low_spend_landing_campaign_without_conversions",
                "funnel spy",
                "Replay",
                "https://example.com/replay",
                None,
                "ELIGIBLE",
                0,
                40,
            ),
            ("ranks_on_the_homepage_the_ads_link_to", "funnel spy", None, "https://example.com/"),
            ("ranks_on_a_page_no_ad_links_to", "funnel spy", None, "https://example.com/blog"),
            ("landing_page_query_without_a_converting_word", "crm spy", None, "https://example.com/replay"),
            ("already_a_keyword", "funnel analysis", None, None, "funnel analysis"),
        ]
    )
    def test_keyword_gap_takes_queries_whose_words_convert_or_that_rank_on_a_landing_page(
        self,
        _name: str,
        query: str,
        expected_campaign: str | None,
        ranking_page: str | None = None,
        keyword: str | None = None,
        landing_status: str = "ELIGIBLE",
        landing_conversions: float = 10,
        landing_cost: float = 1000,
    ) -> None:
        campaigns = (
            _campaign(
                id="c2",
                name="Replay",
                primary_status=landing_status,
                conversions=landing_conversions,
                cost=landing_cost,
            ),
            _campaign(),
        )
        terms = (
            _term("funnel tracking", "c1", cost=100, conversions=10),
            _term("analysis software", "c1", cost=100, conversions=10),
            _term("spy", "c1", cost=1000, conversions=1),
            _term("session replay", "c2", cost=100, conversions=10),
        )
        organic = tuple(OrganicQueryStats(query=f"filler {i}", clicks=1, impressions=1, position=50) for i in range(30))
        organic += (OrganicQueryStats(query=query, clicks=1, impressions=5000, position=25),)
        pages = (RankingPage(query=query, page=ranking_page, impressions=5000),) if ranking_page else ()
        keywords = (
            (TermKeywordStats(term="funnel tracking", keyword=keyword, match_type="PHRASE", cost=100),)
            if keyword
            else ()
        )
        ads = (
            Ad(
                ad_group_id="ag2",
                campaign_id="c2",
                texts=(),
                final_urls=("https://example.com/replay", "https://example.com/replay?id=abc", "https://example.com/"),
            ),
        )
        inputs = replace(_inputs(campaigns, terms, organic, keywords, pages), ads=ads)

        gaps = {
            rec.subject: (rec.campaign, rec.identity.customer_id, rec.identity.campaign_id)
            for rec in recommend(inputs)
            if rec.rule == "keyword_gap"
        }

        if expected_campaign is None:
            assert query not in gaps
        else:
            assert gaps[query] == (expected_campaign, "", "")

    @parameterized.expand(
        [
            ("keyword_in_active_search_campaign", "c1", "keyword_added"),
            ("keyword_in_paused_campaign", "paused", None),
            ("keyword_in_unknown_campaign", "gone", None),
        ]
    )
    def test_keyword_gap_is_applied_once_the_search_is_a_keyword(
        self, _name: str, keyword_campaign: str, expected: str | None
    ) -> None:
        campaigns = (_campaign(), _campaign(id="paused", name="Paused", primary_status="PAUSED"))
        terms = (_term("funnel tracking", "c1", cost=100, conversions=10),)
        organic = (OrganicQueryStats(query="funnel tracking tool", clicks=1, impressions=5000, position=25),)

        recs = recommend(
            _inputs(
                campaigns,
                terms,
                organic,
                keywords=(Keyword(text="funnel tracking tool", campaign_id=keyword_campaign),),
            )
        )

        gap = next(rec for rec in recs if rec.rule == "keyword_gap")
        assert gap.detectedChange == expected

    @parameterized.expand(
        [
            (
                "disapproved_and_limited",
                (PolicyAds(campaign_id="c1", disapproved=2, limited=1),),
                "2 ads are disapproved and 1 ad is limited by Google policy, which cuts the campaign's reach.",
            ),
            (
                "only_limited",
                (PolicyAds(campaign_id="c1", disapproved=0, limited=1),),
                "1 ad is limited by Google policy, which cuts the campaign's reach.",
            ),
            (
                "only_another_campaigns_ads",
                (PolicyAds(campaign_id="other", disapproved=3, limited=0),),
                "Some ads or asset groups are limited or disapproved by Google policy, which cuts the campaign's reach.",
            ),
        ]
    )
    def test_policy_limited_counts_affected_ads_and_links_to_the_fix(
        self, _name: str, policy_ads: tuple[PolicyAds, ...], expected_reason: str
    ) -> None:
        campaign = _campaign(status_reasons=("HAS_ADS_DISAPPROVED",))

        inputs = replace(_inputs((campaign,)), policy_ads=policy_ads)
        rec = next(rec for rec in recommend(inputs) if rec.rule == "policy_limited")

        assert rec.reason == expected_reason
        steps = rec.steps or []
        assert [step.copyValue for step in steps if step.copyValue] == ["Search"]
        assert [step.linkText for step in steps if step.url] == ["Campaigns", "Ads", "Policy manager"]
        assert all(step.linkText and step.linkText in step.text for step in steps if step.url)

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
            ("policy_limited", "Fix or appeal the policy issues in this campaign"),
        }
        assert all(rec.cpa is None for rec in recs)
        leak = next(rec for rec in recs if rec.rule == "brand_leak")
        assert [step.copyValue for step in leak.steps or [] if step.copyValue] == ["PMax", "example"]
        scale = next(rec for rec in recs if rec.rule == "scale_campaign")
        assert "target CPA" in (scale.steps or [])[1].text
        policy = next(rec for rec in recs if rec.rule == "policy_limited")
        assert [step.linkText for step in policy.steps or [] if step.linkText] == [
            "Campaigns",
            "Asset groups",
            "Policy manager",
        ]

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

    @parameterized.expand(
        [
            (
                "unrelated_to_copy_and_keyword",
                COPY,
                10,
                "analytics",
                ["crm for dentist", "analytics pricing"],
                'None of the main words in this search appear in the ads that showed on it or in the keyword "analytics".',
            ),
            (
                "unrelated_to_copy_without_keyword_data",
                COPY,
                10,
                None,
                ["crm for dentist", "analytics pricing"],
                "None of the main words in this search appear in the ads that showed on it.",
            ),
            ("ad_table_not_synced", (), 10, "analytics", ["analytics pricing", "crm for dentist"], None),
            ("too_few_clicks", COPY, 3, "analytics", ["analytics pricing", "crm for dentist"], None),
            (
                "copy_mentions_the_plural",
                ("CRM for dentists",),
                10,
                None,
                ["analytics pricing", "crm for dentist"],
                None,
            ),
            ("keyword_mentions_it", COPY, 10, "dental crm", ["analytics pricing", "crm for dentist"], None),
            (
                "keyword_insertion_without_keyword_data",
                ("{KeyWord:Product analytics}",),
                10,
                None,
                ["analytics pricing", "crm for dentist"],
                None,
            ),
            (
                "another_ad_group_that_showed_mentions_it",
                COPY,
                10,
                None,
                ["analytics pricing", "crm for dentist"],
                None,
                ("CRM for dentists",),
            ),
        ]
    )
    def test_spend_without_conversions_ranks_searches_unrelated_to_the_ads_first(
        self,
        _name: str,
        copy: tuple[str, ...],
        clicks: float,
        keyword: str | None,
        expected_order: list[str],
        expected_reason_end: str | None,
        other_group_copy: tuple[str, ...] | None = None,
    ) -> None:
        terms = (
            replace(_term("crm for dentist", "c1", cost=240, conversions=0, clicks=clicks), ad_group_ids=("ag1",)),
            replace(_term("crm for dentist", "c2", cost=10, conversions=0, clicks=0), ad_group_ids=("ag2",)),
            replace(_term("analytics pricing", "c1", cost=400, conversions=0), ad_group_ids=("ag1",)),
            replace(_term("product analytics", "c1", cost=350, conversions=10), ad_group_ids=("ag1",)),
        )
        keywords = (
            (TermKeywordStats(term="crm for dentist", keyword=keyword, match_type="BROAD", cost=250),)
            if keyword
            else ()
        )
        ads = (
            (
                Ad(ad_group_id="ag1", campaign_id="c1", texts=copy, final_urls=()),
                Ad(ad_group_id="ag2", campaign_id="c2", texts=other_group_copy or copy, final_urls=()),
            )
            if copy
            else ()
        )

        recs = [
            rec
            for rec in recommend(replace(_inputs((_campaign(),), terms, term_keywords=keywords), ads=ads))
            if rec.rule == "spend_without_conversions"
        ]

        assert [rec.subject for rec in recs] == expected_order
        unrelated = next(rec for rec in recs if rec.subject == "crm for dentist")
        if expected_reason_end:
            assert unrelated.reason.endswith(f"with no conversions. {expected_reason_end}")
        else:
            assert unrelated.reason.endswith("with no conversions")

    def test_unrelated_searches_go_first_only_among_the_costliest_wasted_searches(self) -> None:
        unrelated = tuple(
            replace(_term(f"dentist {i}", "c1", cost=210 + i, conversions=0), ad_group_ids=("ag1",))
            for i in range(PER_RULE_LIMIT)
        )
        terms = (
            *unrelated,
            replace(_term("analytics pricing", "c1", cost=3000, conversions=0), ad_group_ids=("ag1",)),
            replace(_term("product analytics", "c1", cost=350, conversions=10), ad_group_ids=("ag1",)),
        )
        ads = (Ad(ad_group_id="ag1", campaign_id="c1", texts=COPY, final_urls=()),)

        recs = [
            rec.subject
            for rec in apply_resolutions(
                recommend(replace(_inputs((_campaign(),), terms), ads=ads)), {}, include_resolved=False
            )
            if rec.rule == "spend_without_conversions"
        ]

        assert len(recs) == PER_RULE_LIMIT
        assert recs[-1] == "analytics pricing"

    @parameterized.expand(
        [
            ("serving", "ELIGIBLE", ("NONE",), [None], 1),
            ("paused", "PAUSED", ("NONE",), [], 0),
            ("removed", "REMOVED", ("NONE",), [], 0),
            ("already_a_keyword", "ELIGIBLE", ("ADDED",), [], 0),
            ("now_a_negative", "ELIGIBLE", ("EXCLUDED",), ["negative_keyword"], 0),
            ("keyword_and_negative", "ELIGIBLE", ("ADDED_EXCLUDED",), ["negative_keyword"], 0),
            ("negative_in_one_of_two_campaigns", "ELIGIBLE", ("EXCLUDED", "NONE"), [None], 1),
            ("keyword_and_negative_in_one_of_two_campaigns", "ELIGIBLE", ("ADDED_EXCLUDED", "NONE"), [None], 1),
        ]
    )
    def test_spend_without_conversions_needs_a_serving_campaign_and_detects_negatives(
        self,
        _name: str,
        campaign_status: str,
        term_statuses: tuple[str, ...],
        expected_changes: list[str | None],
        expected_unresolved: int,
    ) -> None:
        campaigns = (_campaign(primary_status=campaign_status), _campaign(id="c2", name="Other"))
        terms = (
            *(
                replace(_term("free analytics template", campaign_id, cost=500, conversions=0), status=status)
                for campaign_id, status in zip(("c1", "c2"), term_statuses)
            ),
            _term("product analytics", "c2", cost=500, conversions=10),
        )

        excluded = frozenset(
            ExcludedSearch(term="free analytics template", campaign_id=campaign_id)
            for campaign_id, status in zip(("c1", "c2"), term_statuses)
            if "EXCLUDED" in status
        )
        inputs = replace(_inputs(campaigns, terms), excluded_searches=excluded)

        rows = [rec for rec in recommend(inputs) if rec.rule == "spend_without_conversions"]

        assert [rec.detectedChange for rec in rows] == expected_changes
        assert len(apply_resolutions(rows, {}, include_resolved=False)) == expected_unresolved
        # Spend in a campaign that already blocks the search can't be saved, and that campaign needs no new negative.
        serving = [name for name, status in zip(("Search", "Other"), term_statuses) if "EXCLUDED" not in status]
        assert [(rec.campaign, rec.reason.split(" (")[0]) for rec in rows] == [
            (serving[0] if serving else "Search", f"Spent ${500 * max(len(serving), 1):,}")
        ] * len(rows)
        assert apply_resolutions(rows, {}, include_resolved=True) == rows

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
            assert [step.linkText for step in rows[0].steps or []] == ["Account settings", None, "Campaigns"]
