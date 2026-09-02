from products.marketing_analytics.backend.services.campaign_field_suggester import (
    COLLISION_CONFIDENCE,
    MAX_CONFIDENCE,
    MIN_CONFIDENCE,
    suggest_campaign_field_preferences,
)
from products.marketing_analytics.backend.services.types import (
    Campaign,
    CampaignAuditResult,
    TeamMappings,
    UtmIssue,
    UtmIssueKind,
    UtmIssueSeverity,
)

NO_MAPPINGS = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})
PREFERS_ID = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={"google": "campaign_id"})


def _campaign(name: str, campaign_id: str, spend: float = 100.0, source: str = "google") -> Campaign:
    return Campaign(
        campaign_name=name,
        campaign_id=campaign_id,
        source_name=source,
        spend=spend,
        clicks=0,
        impressions=0,
    )


def _utm(*campaign_values: str, source: str = "google") -> dict[tuple[str, str], int]:
    return {(value, source): 100 for value in campaign_values}


def _named_campaigns(count: int, *, source: str = "google", spend: float = 100.0) -> list[Campaign]:
    return [_campaign(f"camp_{i}", f"{1000 + i}", spend=spend, source=source) for i in range(count)]


def _collision(source: str, shared_with: list[str], campaign_name: str = "camp_0") -> CampaignAuditResult:
    return CampaignAuditResult(
        campaign_name=campaign_name,
        campaign_id="1000",
        source_name=source,
        spend=100.0,
        clicks=0,
        impressions=0,
        has_utm_events=False,
        event_count=0,
        issues=[
            UtmIssue(
                field="utm_campaign",
                severity=UtmIssueSeverity.WARNING,
                kind=UtmIssueKind.NAME_COLLISION,
                shared_with_integrations=shared_with,
            )
        ],
    )


class TestClearWinner:
    def test_suggests_id_when_ids_match_and_names_do_not(self):
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_id for c in campaigns])

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.integration == "GoogleAds"
        assert suggestion.current_match_field == "campaign_name"
        assert suggestion.suggested_match_field == "campaign_id"
        assert suggestion.suggested.spend_rate == 1.0
        assert suggestion.current.spend_rate == 0.0
        assert suggestion.confidence == MAX_CONFIDENCE
        assert suggestion.safe_to_batch is True
        assert suggestion.triggered_by_collision is False

    def test_suggests_name_when_team_wrongly_prefers_id(self):
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_name for c in campaigns])

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, PREFERS_ID)

        assert len(suggestions) == 1
        assert suggestions[0].current_match_field == "campaign_id"
        assert suggestions[0].suggested_match_field == "campaign_name"

    def test_reports_spend_at_risk_against_the_current_field(self):
        campaigns = _named_campaigns(10, spend=50.0)
        utm_events = _utm(*[c.campaign_id for c in campaigns])

        suggestion = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)[0]

        assert suggestion.spend_at_risk == 500.0
        assert suggestion.total_spend == 500.0


class TestNoSuggestion:
    def test_silent_when_current_field_already_matches(self):
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_name for c in campaigns])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_silent_below_the_delta_threshold(self):
        # 6 by name, 7 by id: +10pp, under the 15pp floor.
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_name for c in campaigns[:6]], *[c.campaign_id for c in campaigns[:7]])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_silent_when_delta_is_big_but_target_rate_is_low(self):
        # 0% -> 30% clears the delta but is still mostly broken; that's what the floor is for.
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_id for c in campaigns[:3]])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_silent_with_too_few_campaigns(self):
        campaigns = _named_campaigns(4)
        utm_events = _utm(*[c.campaign_id for c in campaigns])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_silent_when_campaign_ids_are_mostly_empty(self):
        # id wins 50% to 0% on the numbers, but switching strands the half with no ids.
        with_ids = [_campaign(f"camp_{i}", f"{1000 + i}") for i in range(5)]
        without_ids = [_campaign(f"camp_{i}", "") for i in range(5, 10)]
        campaigns = [*with_ids, *without_ids]
        utm_events = _utm(*[c.campaign_id for c in with_ids])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_suggests_id_once_coverage_clears_the_floor(self):
        with_ids = [_campaign(f"camp_{i}", f"{1000 + i}") for i in range(8)]
        without_ids = [_campaign(f"camp_{i}", "") for i in range(8, 10)]
        campaigns = [*with_ids, *without_ids]
        utm_events = _utm(*[c.campaign_id for c in with_ids])

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)

        assert len(suggestions) == 1
        assert suggestions[0].suggested_match_field == "campaign_id"
        # 8 of 10 by spend, and the two id-less campaigns are named as needing URL fixes.
        assert suggestions[0].suggested.spend_rate == 0.8
        assert set(suggestions[0].still_unmatched_examples) == {"camp_8", "camp_9"}

    def test_silent_when_there_are_no_utm_events_at_all(self):
        campaigns = _named_campaigns(10)

        assert suggest_campaign_field_preferences(campaigns, {}, NO_MAPPINGS) == []

    def test_silent_for_a_non_native_source(self):
        campaigns = _named_campaigns(10, source="some_csv_upload")
        utm_events = _utm(*[c.campaign_id for c in campaigns], source="some_csv_upload")

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []


class TestSourceScoping:
    """Production groups cost and conversions on a (campaign, source) row key, so a rate that
    ignores utm_source does not describe what the table will actually attribute."""

    def test_another_platform_traffic_does_not_prop_up_the_name_rate(self):
        # An unscoped catalogue credited Google with Meta's events on the shared name.
        campaigns = [_campaign(f"shared_{i}", f"{2000 + i}", spend=500.0) for i in range(6)]
        utm_events = {
            **{(c.campaign_name, "facebook"): 100 for c in campaigns},
            **{(c.campaign_id, "google"): 100 for c in campaigns},
        }

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)

        assert [s.suggested_match_field for s in suggestions] == ["campaign_id"]

    def test_a_custom_source_mapping_is_credited_to_its_integration(self):
        # Once "fb_paid" maps to meta its traffic must count, or scoping zeroes out a working team.
        campaigns = _named_campaigns(6, source="meta")
        utm_events = {(c.campaign_name, "fb_paid"): 100 for c in campaigns}
        mapped = TeamMappings(source_to_integration={"fb_paid": "meta"}, campaign_aliases={}, field_preferences={})

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, mapped)

        assert suggestions == []

    def test_a_default_alias_is_credited_without_any_mapping(self):
        # 'facebook' resolves to meta with no team config, so scoping can't demand one.
        campaigns = _named_campaigns(6, source="meta")
        utm_events = {(c.campaign_name, "facebook"): 100 for c in campaigns}

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)

        assert suggestions == []


class TestRanking:
    def test_ranks_by_what_switching_recovers_not_by_the_current_gap(self):
        # Meta:   20 campaigns x 500 = 10,000 gap, ids match 12/20 -> recovers 6,000.
        # Google: 10 campaigns x 500 =  5,000 gap, ids match  9/10 -> recovers 4,500.
        meta = [_campaign(f"m_{i}", f"{9000 + i}", spend=500.0, source="meta") for i in range(20)]
        google = [_campaign(f"g_{i}", f"{8000 + i}", spend=500.0, source="google") for i in range(10)]
        utm_events = {
            **{(c.campaign_id, "facebook"): 100 for c in meta[:12]},
            **{(c.campaign_id, "google"): 100 for c in google[:9]},
        }

        suggestions = suggest_campaign_field_preferences(meta + google, utm_events, NO_MAPPINGS)

        assert [s.integration for s in suggestions] == ["MetaAds", "GoogleAds"]
        assert [round(s.spend_recovered) for s in suggestions] == [6000, 4500]
        # Both keys agree in this fixture; the disagreeing case is pinned below.
        assert [round(s.spend_at_risk) for s in suggestions] == [10000, 5000]

    def test_a_barely_helpful_switch_does_not_outrank_a_repair(self):
        # Big has the larger gap but recovers less, so spend_at_risk ranked it first.
        big = [_campaign(f"b_{i}", f"{7000 + i}", spend=1000.0, source="meta") for i in range(10)]
        small = [_campaign(f"s_{i}", f"{6000 + i}", spend=800.0, source="google") for i in range(10)]
        utm_events = {
            # Meta: gap 10,000, ids match 6/10 -> recovers 6,000.
            **{(c.campaign_id, "facebook"): 100 for c in big[:6]},
            # Google: gap 8,000, ids match 9/10 -> recovers 7,200.
            **{(c.campaign_id, "google"): 100 for c in small[:9]},
        }

        suggestions = suggest_campaign_field_preferences(big + small, utm_events, NO_MAPPINGS)

        assert [round(s.spend_at_risk) for s in suggestions] == [8000, 10000]
        assert [s.integration for s in suggestions] == ["GoogleAds", "MetaAds"]
        assert [round(s.spend_recovered) for s in suggestions] == [7200, 6000]


class TestCollisionOverride:
    def test_surfaces_collision_even_below_threshold(self):
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_name for c in campaigns])
        audit = [_collision("google", ["meta"])]

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, audit)

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.triggered_by_collision is True
        assert suggestion.suggested_match_field == "campaign_id"
        assert suggestion.colliding_integrations == ["meta"]
        assert suggestion.confidence == COLLISION_CONFIDENCE
        assert suggestion.safe_to_batch is False
        # The structured field keeps the raw key (asserted above); only the prose is humanised.
        assert "Meta Ads" in suggestion.reason

    def test_a_collision_never_suggests_going_back_to_names(self):
        # Already on the cure; "whatever isn't current" suggested switching back to the ambiguity.
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_id for c in campaigns])
        audit = [_collision("google", ["meta"])]

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, PREFERS_ID, audit)

        assert [s.suggested_match_field for s in suggestions] == []

    def test_collision_reason_names_the_other_platform_the_way_a_human_would(self):
        # One sentence mixed both vocabularies: "Google Ads shares campaign names with meta".
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_name for c in campaigns])
        audit = [_collision("google", ["meta"])]

        suggestion = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, audit)[0]

        assert "Meta Ads" in suggestion.reason
        assert "with meta" not in suggestion.reason

    def test_collision_reason_counts_the_shared_campaigns(self):
        # An absent-from-catalogue set read "0 campaign(s) worth $0.00" here.
        campaigns = _named_campaigns(10, spend=250.0)
        utm_events = _utm(*[c.campaign_name for c in campaigns])
        audit = [_collision("google", ["meta"])]

        suggestion = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, audit)[0]

        assert "10 campaign(s)" in suggestion.reason
        assert "2,500" in suggestion.reason

    def test_spend_delta_wins_over_collision_framing(self):
        # Arithmetic wins over the collision path: higher confidence.
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_id for c in campaigns])
        audit = [_collision("google", ["meta"])]

        suggestion = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, audit)[0]

        assert suggestion.triggered_by_collision is False
        assert suggestion.confidence > COLLISION_CONFIDENCE
        assert suggestion.colliding_integrations == ["meta"]

    def test_non_collision_issues_do_not_trigger(self):
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_name for c in campaigns])
        not_linked = _collision("google", [])
        not_linked.issues[0].kind = UtmIssueKind.NOT_LINKED

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, [not_linked]) == []


class TestSpendWeighting:
    def test_spend_decides_not_campaign_count(self):
        # By count name wins 90/10; by spend id wins 91/9. Spend is what the ROAS column uses.
        cheap = [_campaign(f"cheap_{i}", f"{i}", spend=100.0) for i in range(9)]
        expensive = _campaign("expensive", "99999", spend=9000.0)
        campaigns = [*cheap, expensive]
        utm_events = _utm(*[c.campaign_name for c in cheap], expensive.campaign_id)

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.suggested_match_field == "campaign_id"
        assert suggestion.suggested.spend_rate > suggestion.current.spend_rate
        assert suggestion.suggested.count_rate < suggestion.current.count_rate
        assert "By campaign count the gap is smaller" in suggestion.reason


class TestReporting:
    def test_lists_campaigns_still_unmatched_after_switching(self):
        campaigns = _named_campaigns(10)
        # 8 of 10 match by id; the other two need their ad URLs fixed instead.
        utm_events = _utm(*[c.campaign_id for c in campaigns[:8]])

        suggestion = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)[0]

        assert set(suggestion.still_unmatched_examples) == {"camp_8", "camp_9"}

    def test_confidence_scales_with_the_delta_and_is_never_certain(self):
        campaigns = _named_campaigns(10)
        modest = _utm(*[c.campaign_name for c in campaigns[:4]], *[c.campaign_id for c in campaigns[:6]])
        total = _utm(*[c.campaign_id for c in campaigns])

        modest_suggestion = suggest_campaign_field_preferences(campaigns, modest, NO_MAPPINGS)[0]
        total_suggestion = suggest_campaign_field_preferences(campaigns, total, NO_MAPPINGS)[0]

        assert MIN_CONFIDENCE <= modest_suggestion.confidence < total_suggestion.confidence <= MAX_CONFIDENCE
        assert total_suggestion.confidence < 1.0

    def test_orders_integrations_by_the_spend_a_switch_recovers(self):
        # Both match 0% by name, so the two spend figures coincide and only the ordering is
        # pinned here; they disagree in `test_a_barely_helpful_switch_does_not_outrank_a_repair`.
        google = _named_campaigns(10, source="google", spend=100.0)
        meta = _named_campaigns(10, source="meta", spend=900.0)
        utm_events = {
            **_utm(*[c.campaign_id for c in google], source="google"),
            **_utm(*[c.campaign_id for c in meta], source="meta"),
        }

        suggestions = suggest_campaign_field_preferences([*google, *meta], utm_events, NO_MAPPINGS)

        assert [s.integration for s in suggestions] == ["MetaAds", "GoogleAds"]

    def test_mapped_aliases_are_excluded_from_both_rates(self):
        # An alias resolves under either field, so crediting the name side suppresses a warranted
        # switch.
        campaigns = _named_campaigns(10)
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={c.campaign_name: {f"alias_{i}"} for i, c in enumerate(campaigns)},
            field_preferences={},
        )
        utm_events = _utm(*[f"alias_{i}" for i in range(10)], *[c.campaign_id for c in campaigns])

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, mappings)

        assert len(suggestions) == 1
        assert suggestions[0].current.spend_rate == 0.0
        assert suggestions[0].suggested_match_field == "campaign_id"

    def test_an_alias_spelled_like_the_campaign_name_is_still_excluded(self):
        # Above, `alias_0` never equals `camp_0`, so the name rate reads 0 whether or not aliases
        # are excluded. Aliasing each campaign to its own name is what makes it observable.
        campaigns = _named_campaigns(10)
        mappings = TeamMappings(
            source_to_integration={},
            campaign_aliases={c.campaign_name: {c.campaign_name} for c in campaigns},
            field_preferences={},
        )
        utm_events = _utm(*[c.campaign_name for c in campaigns], *[c.campaign_id for c in campaigns])

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, mappings)

        assert len(suggestions) == 1
        assert suggestions[0].current.spend_rate == 0.0
        assert suggestions[0].suggested_match_field == "campaign_id"

    def test_a_mixed_case_utm_value_matches_the_campaign_it_names(self):
        # Platforms emit names in the account's own casing. The campaign side is always
        # lowercased, so folding one side read a 100%-tagged account as 0% and told it to switch.
        campaigns = [_campaign(f"Camp_{i}", str(1000 + i)) for i in range(10)]
        utm_events = _utm(*[f"Camp_{i}" for i in range(10)], *[str(1000 + i) for i in range(5)])

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)

        assert suggestions == []
