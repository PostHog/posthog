import time

import pytest

from products.marketing_analytics.backend.services.campaign_mapping_suggester import (
    BATCH_SCORE,
    MIN_EVENT_COUNT,
    SCORE_CUTOFF,
    differs_only_by_period,
    suggest_campaign_name_mappings,
)
from products.marketing_analytics.backend.services.types import Campaign, TeamMappings

NO_MAPPINGS = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})


def _campaign(name: str, campaign_id: str = "1", spend: float = 1000.0, source: str = "google") -> Campaign:
    return Campaign(
        campaign_name=name,
        campaign_id=campaign_id,
        source_name=source,
        spend=spend,
        clicks=0,
        impressions=0,
    )


def _events(*rows: tuple[str, str, int]) -> dict[tuple[str, str], int]:
    return {(campaign, source): count for campaign, source, count in rows}


class TestPeriodGuard:
    """`brand_us_q1` vs `brand_us_q2` scores ~96 on WRatio and is a different campaign."""

    @pytest.mark.parametrize(
        "a,b",
        [
            ("brand_us_q1", "brand_us_q2"),
            ("sale_2024", "sale_2025"),
            ("promo", "promo_march"),
            ("brand-h1", "brand-h2"),
            ("retarget_w1", "retarget_w2"),
            ("brand_fy24", "brand_fy25"),
            ("launch_2024q1", "launch_2024q2"),
        ],
    )
    def test_rejects_period_siblings(self, a, b):
        assert differs_only_by_period(a, b) is True

    @pytest.mark.parametrize(
        "a,b",
        [
            ("sprng_sale_2024", "spring_sale_2024"),
            ("brand_us", "brnd_us"),
            ("brand_us_q1", "brand-us-q1"),
            ("brand_us_q1", "q1_us_brand"),
            ("sprng_sale_q1", "spring_sale_q2"),
        ],
    )
    def test_allows_real_matches(self, a, b):
        assert differs_only_by_period(a, b) is False


class TestProposals:
    def test_proposes_mapping_for_a_typo(self):
        campaigns = [_campaign("spring_sale_2024", spend=8200.0)]
        utm_events = _events(("sprng_sale_2024", "google", 1340))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert len(result.proposals) == 1
        proposal = result.proposals[0]
        assert proposal.raw_utm_campaign == "sprng_sale_2024"
        assert proposal.clean_name == "spring_sale_2024"
        assert proposal.integration == "GoogleAds"
        assert proposal.event_count == 1340
        assert proposal.campaign_spend == 8200.0
        assert proposal.method == "fuzzy_exact_scope"
        assert proposal.expected_utm_campaign == "spring_sale_2024"
        assert proposal.expected_utm_source == "google"

    def test_confidence_never_reaches_certainty(self):
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("sprng_sale_2024", "google", 500))

        proposal = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS).proposals[0]

        assert 0.5 <= proposal.confidence <= 0.9

    def test_proposes_the_id_when_integration_matches_on_id(self):
        # A name proposed to an id-matching integration never joins.
        prefers_id = TeamMappings(
            source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"}
        )
        campaigns = [_campaign("spring_sale_2024", campaign_id="promo_1234x")]
        utm_events = _events(("promo_1234y", "google", 500))

        result = suggest_campaign_name_mappings(campaigns, utm_events, prefers_id)

        assert len(result.proposals) == 1
        assert result.proposals[0].clean_name == "promo_1234x"

    def test_a_campaign_already_receiving_traffic_is_never_a_target(self):
        # Mixed case is the point: the guard compared a lowercased candidate against a set
        # built with original casing.
        campaigns = [_campaign("Spring_Sale_2024", spend=8200.0)]
        utm_events = _events(
            ("Spring_Sale_2024", "google", 900),  # already linked, mixed case
            ("sprng_sale_2024", "google", 500),  # the orphan that must not land on it
        )

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []

    def test_a_quarterly_family_does_not_bury_a_real_match(self):
        # The siblings score 93.33 and the real match 92.86, so truncating to 3 before the period
        # filter buried it. Here the platform campaign carries the typo, not the URL.
        campaigns = [
            _campaign("winter_promo_q2", campaign_id="2"),
            _campaign("winter_promo_q3", campaign_id="3"),
            _campaign("winter_promo_q4", campaign_id="4"),
            _campaign("wintr_prom_q1", campaign_id="1", spend=9000.0),
        ]
        utm_events = _events(("winter_promo_q1", "google", 700))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert [p.clean_name for p in result.proposals] == ["wintr_prom_q1"]

    def test_another_platform_traffic_does_not_veto_a_starved_candidate(self):
        # A global `seen` set let Meta's traffic on "brand" disqualify Google's own "brand".
        campaigns = [
            _campaign("brand", campaign_id="1", spend=9000.0, source="google"),
            _campaign("brand", campaign_id="2", spend=4000.0, source="meta"),
        ]
        utm_events = _events(
            ("brand", "facebook", 1200),  # Meta's own traffic, correctly attributed
            ("brnd", "google", 800),  # the Google orphan that should map onto Google's "brand"
        )

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert [(p.raw_utm_campaign, p.clean_name, p.integration) for p in result.proposals] == [
            ("brnd", "brand", "GoogleAds")
        ]

    def test_a_runner_up_below_the_cutoff_still_counts_as_ambiguity(self):
        # 90.9 and 85.5 are the scorer's real numbers: the runner-up is below the cutoff, so
        # ranking with it applied reported margin 100 against a real 5.4.
        campaigns = [
            _campaign("uk_uss", campaign_id="1", spend=5000.0),
            _campaign("email_uk", campaign_id="2", spend=4000.0),
        ]
        utm_events = _events(("uk_us", "google", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert [a.raw_utm_campaign for a in result.ambiguous] == ["uk_us"]

    def test_purely_numeric_id_near_miss_is_refused(self):
        # `1234` vs `12345` is indistinguishable from one real id beside another.
        prefers_id = TeamMappings(
            source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"}
        )
        campaigns = [_campaign("spring_sale_2024", campaign_id="12345")]
        utm_events = _events(("1234", "google", 500))

        result = suggest_campaign_name_mappings(campaigns, utm_events, prefers_id)

        assert result.proposals == []
        assert [u.raw_utm_campaign for u in result.unresolved] == ["1234"]

    def test_numeric_only_typo_is_refused_and_handed_to_the_ai_layer(self):
        # A truncated year is a real typo, but indistinguishable from next year's campaign.
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("spring_sale_202", "google", 500))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert [u.raw_utm_campaign for u in result.unresolved] == ["spring_sale_202"]

    def test_a_period_sibling_refusal_names_the_campaign_it_refused(self):
        # The generic reason claims nothing was within the cutoff, which reads as false when the
        # campaign is right there at 93.3 and was refused on purpose.
        campaigns = [_campaign("holiday_push_q4")]
        utm_events = _events(("holiday_push_q3", "google", 500))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        reason = result.unresolved[0].reason
        assert "holiday_push_q4" in reason
        assert "period" in reason
        assert "similarity" not in reason

    def test_a_candidate_between_the_ranking_floor_and_the_cutoff_is_no_match(self):
        # 85.7: survives MARGIN_FLOOR's 73 and gets ranked, then fails SCORE_CUTOFF's 88. The
        # module's headline threshold, and the only line applying it had no test — every other
        # refusal here goes through the period guard or the margin instead.
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("sprig_sl_204", "google", 500))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert result.ambiguous == []
        assert [u.raw_utm_campaign for u in result.unresolved] == ["sprig_sl_204"]

    def test_orders_proposals_by_spend_at_stake(self):
        campaigns = [_campaign("cheap_campaign", spend=10.0), _campaign("costly_campaign", "2", spend=50000.0)]
        utm_events = _events(("cheap_campaig", "google", 900), ("costly_campaig", "google", 100))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert [p.clean_name for p in result.proposals] == ["costly_campaign", "cheap_campaign"]


class TestRefusals:
    def test_period_sibling_is_never_proposed(self):
        campaigns = [_campaign("brand_us_q1")]
        utm_events = _events(("brand_us_q2", "google", 5000))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert result.ambiguous == []
        assert [u.raw_utm_campaign for u in result.unresolved] == ["brand_us_q2"]

    def test_near_tie_becomes_advice_not_a_guess(self):
        campaigns = [_campaign("brand_usa", "1"), _campaign("brand_use", "2")]
        utm_events = _events(("brand_us", "google", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert len(result.ambiguous) == 1
        assert result.ambiguous[0].raw_utm_campaign == "brand_us"
        assert len(result.ambiguous[0].candidates) >= 2
        assert "needs a human" in result.ambiguous[0].reason

    def test_below_min_event_count_is_skipped(self):
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("sprng_sale_2024", "google", MIN_EVENT_COUNT - 1))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert any("were skipped" in n for n in result.notes)

    def test_already_mapped_value_is_skipped(self):
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={"spring_sale_2024": {"sprng_sale_2024"}},
            field_preferences={},
        )
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("sprng_sale_2024", "google", 1000))

        result = suggest_campaign_name_mappings(campaigns, utm_events, mappings)

        assert result.proposals == []

    def test_exact_match_of_another_integrations_campaign_is_a_collision_not_a_typo(self):
        campaigns = [_campaign("brand_global", "1", source="google"), _campaign("brand_globa", "2", source="meta")]
        # An exact match for meta's name is a collision, not a typo.
        utm_events = _events(("brand_globa", "google", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []

    def test_will_not_map_onto_a_campaign_that_already_has_traffic(self):
        # spring_sale_2024 is already linked under its own name.
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("spring_sale_2024", "google", 4000), ("sprng_sale_2024", "google", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert [u.raw_utm_campaign for u in result.unresolved] == ["sprng_sale_2024"]

    def test_two_platforms_cannot_collapse_into_one_clean_name(self):
        campaigns = [_campaign("spring_sale_2024", spend=5000.0, source="google")]
        utm_events = _events(
            ("sprng_sale_2024", "google", 2000),
            ("spring_sale_2024x", "meta", 1500),
        )

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert len(result.proposals) == 1
        assert result.proposals[0].observed_utm_source == "google"

    def test_no_campaigns_yields_nothing(self):
        assert suggest_campaign_name_mappings([], _events(("whatever", "google", 900)), NO_MAPPINGS).proposals == []


class TestScoping:
    def test_unresolvable_source_uses_the_higher_bar_and_never_batches(self):
        # utm_source resolves to no platform, so the search can't be narrowed.
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("spring_sale_2024!", "some_partner", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert len(result.proposals) == 1
        assert result.proposals[0].method == "fuzzy_unscoped"
        assert result.proposals[0].safe_to_batch is False

    def test_scoped_match_ignores_other_platforms_campaigns(self):
        campaigns = [
            _campaign("spring_sale_2024", "1", source="google"),
            _campaign("sprng_sale_2025", "2", source="meta"),
        ]
        utm_events = _events(("sprng_sale_2024", "google", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert len(result.proposals) == 1
        assert result.proposals[0].integration == "GoogleAds"
        assert result.proposals[0].clean_name == "spring_sale_2024"

    def test_unscoped_refuses_a_name_two_platforms_both_run(self):
        # Identical spellings tie *at* the top, so the margin reads 100 and only the spend
        # tiebreak separated them.
        campaigns = [
            _campaign("spring_sale_2024", "1", spend=9000.0, source="google"),
            _campaign("spring_sale_2024", "2", spend=4000.0, source="meta"),
        ]
        utm_events = _events(("sprng_sale_2024", "some_partner", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert result.proposals == []
        assert len(result.ambiguous) == 1
        assert "GoogleAds and MetaAds" in result.ambiguous[0].reason

    def test_unscoped_verdict_does_not_move_with_the_budget(self):
        # Identical evidence, opposite spend: a verdict that flips here follows the budget.
        def integrations_for(google_spend: float, meta_spend: float) -> list[str]:
            campaigns = [
                _campaign("spring_sale_2024", "1", spend=google_spend, source="google"),
                _campaign("spring_sale_2024", "2", spend=meta_spend, source="meta"),
            ]
            utm_events = _events(("sprng_sale_2024", "some_partner", 900))
            result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)
            return [proposal.integration for proposal in result.proposals]

        assert integrations_for(9000.0, 1000.0) == integrations_for(1000.0, 9000.0) == []

    def test_scoped_still_proposes_when_another_platform_shares_the_name(self):
        # utm_source names google, so the shared name isn't ambiguous and the proposal survives.
        campaigns = [
            _campaign("spring_sale_2024", "1", spend=9000.0, source="google"),
            _campaign("spring_sale_2024", "2", spend=4000.0, source="meta"),
        ]
        utm_events = _events(("sprng_sale_2024", "google", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert len(result.proposals) == 1
        assert result.proposals[0].integration == "GoogleAds"

    def test_canonical_source_alias_still_scopes(self):
        campaigns = [_campaign("spring_sale_2024", source="meta")]
        utm_events = _events(("sprng_sale_2024", "facebook", 900))

        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)

        assert len(result.proposals) == 1
        assert result.proposals[0].method == "fuzzy_exact_scope"
        assert result.proposals[0].integration == "MetaAds"


class TestBatchSafety:
    def test_high_score_clear_margin_is_batchable(self):
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("spring_sale_2024 ", "google", 900))

        proposal = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS).proposals[0]

        assert proposal.safe_to_batch is True

    def test_merely_good_match_is_not_batchable(self):
        campaigns = [_campaign("spring_sale_2024")]
        utm_events = _events(("sprng_sle_2024", "google", 900))

        proposals = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS).proposals

        # 93.3: above the proposal cutoff, below the batch bar. Both halves asserted, because
        # `[] or not safe_to_batch` also passes when nothing is proposed.
        assert len(proposals) == 1
        assert SCORE_CUTOFF < proposals[0].score < BATCH_SCORE
        assert proposals[0].safe_to_batch is False


class TestScale:
    def test_stays_fast_at_the_documented_caps(self):
        # 500 is the query's LIMIT, 100 is MAX_UNMATCHED_VALUES.
        campaigns = [_campaign(f"campaign_number_{i:04d}", str(i), spend=float(i)) for i in range(500)]
        utm_events = _events(*[(f"campaign_numbr_{i:04d}", "google", 100) for i in range(100)])

        started = time.perf_counter()
        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)
        elapsed = time.perf_counter() - started

        assert elapsed < 2.0, f"took {elapsed:.2f}s"
        # Or the timing would pass for a suggester that bailed out. All 100 land in `ambiguous`:
        # 500 names one digit apart is a wall of near-ties, i.e. the slowest path.
        assert len(result.proposals) + len(result.ambiguous) + len(result.unresolved) == 100

    def test_oversized_values_cannot_slow_the_fuzzy_pass(self):
        # `utm_campaign` comes off an event property, which has no length bound. At the documented
        # caps but 20k characters a side this took 309 seconds; the length cap is what holds it at
        # milliseconds, so the assertion is the point of the test rather than the timing.
        pad = "y" * 20_000
        campaigns = [_campaign(f"{pad}_camp_{i:04d}", str(i), spend=float(i)) for i in range(500)]
        utm_events = _events(*[(f"{pad}_camp_{i:04d}z", "google", 100) for i in range(100)])

        started = time.perf_counter()
        result = suggest_campaign_name_mappings(campaigns, utm_events, NO_MAPPINGS)
        elapsed = time.perf_counter() - started

        assert elapsed < 2.0, f"took {elapsed:.2f}s"
        # Dropped outright rather than truncated: a mapping has to carry the whole raw value to
        # apply, and a 20k-character utm_campaign is not a typo of any real campaign name.
        assert result.proposals == []
        assert result.ambiguous == []
        assert result.unresolved == []
