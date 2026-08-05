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
        # Every utm_campaign carries the numeric id, none carry the name.
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
        # The reverse direction has to work too, or a bad switch is unrecoverable.
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

        # Nothing matches by name today, so all 10 x 50 is at risk.
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
        # 0% -> 30% is a +30pp delta but still mostly broken; switching would be
        # cargo-culting a fix. The floor exists for exactly this shape.
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_id for c in campaigns[:3]])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_silent_with_too_few_campaigns(self):
        campaigns = _named_campaigns(4)
        utm_events = _utm(*[c.campaign_id for c in campaigns])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_silent_when_campaign_ids_are_mostly_empty(self):
        # Half the rows carry an id, and every id that exists matches — so on the
        # numbers alone id-matching wins 50% to 0% and would clear both thresholds.
        # It must still be refused: switching would strand the half of the account
        # the adapter doesn't populate ids for.
        with_ids = [_campaign(f"camp_{i}", f"{1000 + i}") for i in range(5)]
        without_ids = [_campaign(f"camp_{i}", "") for i in range(5, 10)]
        campaigns = [*with_ids, *without_ids]
        utm_events = _utm(*[c.campaign_id for c in with_ids])

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []

    def test_suggests_id_once_coverage_clears_the_floor(self):
        # Same shape as above but with 8/10 ids populated — now it is safe to switch.
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
        # Both rates are 0 — that's a broken-URLs problem, not a field-choice one.
        campaigns = _named_campaigns(10)

        assert suggest_campaign_field_preferences(campaigns, {}, NO_MAPPINGS) == []

    def test_silent_for_a_non_native_source(self):
        campaigns = _named_campaigns(10, source="some_csv_upload")
        utm_events = _utm(*[c.campaign_id for c in campaigns], source="some_csv_upload")

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS) == []


class TestCollisionOverride:
    def test_surfaces_collision_even_below_threshold(self):
        campaigns = _named_campaigns(10)
        # Name matching looks fine on the numbers, so only the collision triggers it.
        utm_events = _utm(*[c.campaign_name for c in campaigns])
        audit = [_collision("google", ["meta"])]

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, audit)

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.triggered_by_collision is True
        assert suggestion.suggested_match_field == "campaign_id"
        assert suggestion.colliding_integrations == ["meta"]
        assert suggestion.confidence == COLLISION_CONFIDENCE
        # A human has to decide this one — it must never ride in the safe batch.
        assert suggestion.safe_to_batch is False
        assert "meta" in suggestion.reason

    def test_spend_delta_wins_over_collision_framing(self):
        # When the arithmetic already says switch, report that (higher confidence)
        # rather than downgrading to the collision path.
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_id for c in campaigns])
        audit = [_collision("google", ["meta"])]

        suggestion = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, audit)[0]

        assert suggestion.triggered_by_collision is False
        assert suggestion.confidence > COLLISION_CONFIDENCE
        # Still reported, so the UI can mention it.
        assert suggestion.colliding_integrations == ["meta"]

    def test_non_collision_issues_do_not_trigger(self):
        campaigns = _named_campaigns(10)
        utm_events = _utm(*[c.campaign_name for c in campaigns])
        not_linked = _collision("google", [])
        not_linked.issues[0].kind = UtmIssueKind.NOT_LINKED

        assert suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS, [not_linked]) == []


class TestSpendWeighting:
    def test_spend_decides_not_campaign_count(self):
        # 9 cheap campaigns match by name, 1 expensive one matches by id. By count
        # name wins 90/10; by spend id wins 91/9. Spend is what the ROAS column uses.
        cheap = [_campaign(f"cheap_{i}", f"{i}", spend=100.0) for i in range(9)]
        expensive = _campaign("expensive", "99999", spend=9000.0)
        campaigns = [*cheap, expensive]
        utm_events = _utm(*[c.campaign_name for c in cheap], expensive.campaign_id)

        suggestions = suggest_campaign_field_preferences(campaigns, utm_events, NO_MAPPINGS)

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.suggested_match_field == "campaign_id"
        assert suggestion.suggested.spend_rate > suggestion.current.spend_rate
        # And the count rate moved the other way, so the reason says so out loud.
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

    def test_orders_integrations_by_spend_at_risk(self):
        google = _named_campaigns(10, source="google", spend=100.0)
        meta = _named_campaigns(10, source="meta", spend=900.0)
        utm_events = {
            **_utm(*[c.campaign_id for c in google], source="google"),
            **_utm(*[c.campaign_id for c in meta], source="meta"),
        }

        suggestions = suggest_campaign_field_preferences([*google, *meta], utm_events, NO_MAPPINGS)

        assert [s.integration for s in suggestions] == ["MetaAds", "GoogleAds"]

    def test_mapped_aliases_are_excluded_from_both_rates(self):
        # campaign_name_mappings rewrite whichever field is preferred, so crediting
        # the name side for them would inflate the current field's apparent rate and
        # suppress a switch that is actually warranted.
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
