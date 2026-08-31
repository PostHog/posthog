import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from pydantic import ValidationError

from products.marketing_analytics.backend.services.attribution_health import AttributionHealthResponse
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    ConversionGoalsListResponse,
    ConversionGoalSummary,
)
from products.marketing_analytics.backend.services.event_suggestions import CandidateEvent, EventSuggestionsResponse
from products.marketing_analytics.backend.services.mapping_suggester import (
    SourceMappingSuggestion,
    UtmMappingSuggestionsResponse,
)
from products.marketing_analytics.backend.services.marketing_diagnostic import (
    IntegrationDiagnostic,
    MarketingDiagnosticResponse,
)
from products.marketing_analytics.backend.services.setup_plan import get_setup_plan
from products.marketing_analytics.backend.services.setup_types import (
    MAPPING_KINDS,
    Capability,
    OpenOauth,
    ReadinessStatus,
    Severity,
    Suggestion,
    SuggestionKind,
)
from products.marketing_analytics.backend.services.types import Campaign, TeamMappings

_MODULE = "products.marketing_analytics.backend.services.setup_plan"

NO_MAPPINGS = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})


def _integration(
    key="google_ads",
    source_type="GoogleAds",
    status="healthy",
    last_error=None,
    schema_missing=None,
    unmatched=0,
    matched=0,
    paid=0,
    tagged_medium=0,
) -> IntegrationDiagnostic:
    data_source = None
    if status != "events_only":
        from products.marketing_analytics.backend.services.data_source_health import DataSourceHealthEntry

        data_source = DataSourceHealthEntry(
            source_type=source_type,
            is_native=True,
            display_name=key,
            connected=True,
            last_sync_at=None,
            last_sync_status="ok",
            last_error=last_error,
            rows_last_24h=0,
            rows_last_7d=0,
            sources_map_present=True,
            schema_columns_mapped=[],
            schema_columns_required_missing=schema_missing or [],
            required_tables=[],
            settings_url="/settings/env",
            schemas_url="/schemas/1",
            diagnosis=f"{key} diagnosis",
            fix_suggestion=None,
        )

    attribution = None
    if unmatched or matched:
        from products.marketing_analytics.backend.services.attribution_health import AttributionHealthEntry

        attribution = AttributionHealthEntry(
            integration_key=key,
            display_name=key,
            events_with_utm_last_7d=unmatched + matched,
            events_matched_last_7d=matched,
            events_unmatched_likely_yours_last_7d=unmatched,
            last_event_with_matching_utm_at=None,
            matched_pct=0.0,
            sample_unmatched_utm_sources=[],
            events_matched_paid_last_7d=paid,
            events_matched_tagged_medium_last_7d=tagged_medium,
        )

    return IntegrationDiagnostic(
        integration_key=key,
        source_type=source_type,
        display_name=key.replace("_", " ").title(),
        overall_status=status,
        diagnosis=f"{key} diagnosis",
        data_source=data_source,
        attribution=attribution,
    )


def _goal(goal_id="g1", name="Signup", count=1000, misconfigured=False) -> ConversionGoalSummary:
    return ConversionGoalSummary(
        conversion_goal_id=goal_id,
        name=name,
        # What the inspector actually emits — it defaults to "EventsNode", not "events".
        kind="EventsNode",
        target_label=name,
        last_30d_count=count,
        integrated_count=count,
        events_without_utm_source=0,
        events_with_unmatched_utm_source=0,
        non_integrated_count=0,
        integrated_pct=1.0,
        is_misconfigured=misconfigured,
        misconfig_reason="references a deleted action" if misconfigured else None,
    )


def _attribution(total=1000, matched=900) -> AttributionHealthResponse:
    return AttributionHealthResponse(
        lookback_days=90,
        integrations=[],
        total_events_with_utm=total,
        total_events_matched_to_any_integration=matched,
        total_events_unmatched=total - matched,
        sample_globally_unmatched=[],
    )


class SetupPlanTestCase(APIBaseTest):
    """Every leaf the plan gathers is mocked; these tests are about how the plan
    composes, ranks and explains, not about the leaves' own logic."""

    def setUp(self):
        super().setUp()
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration()],
            overall_status="healthy",
            summary="ok",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )
        self.attribution = _attribution()
        self.candidates = EventSuggestionsResponse(candidates=[])
        self.campaigns: list[Campaign] = []
        self.utm_events: dict[tuple[str, str], int] = {}
        self.goal_flags: dict[str, dict] = {"g1": {"counts_as_revenue": True, "counts_as_customer": True}}
        self.utm_mappings = UtmMappingSuggestionsResponse()

        # Every mock reads its attribute at call time, not at setUp time — tests
        # reassign `self.diagnostic` etc. after setUp has already run, and a captured
        # `return_value` would silently keep serving the default fixture.
        attribute_by_target = {
            "get_marketing_diagnostic": "diagnostic",
            "get_attribution_health": "attribution",
            "suggest_conversion_goals": "candidates",
            "get_campaigns_with_spend_async": "campaigns",
            "get_utm_campaign_catalogue_async": "utm_events",
            "_load_goal_flags": "goal_flags",
            "suggest_utm_mappings": "utm_mappings",
        }
        self.mocks = {}
        for target, attribute in attribute_by_target.items():
            mock = AsyncMock(side_effect=self._current(attribute))
            self.mocks[target] = mock
            patcher = patch(f"{_MODULE}.{target}", new=mock)
            patcher.start()
            self.addCleanup(patcher.stop)

        mappings_mock = AsyncMock(side_effect=lambda *args, **kwargs: NO_MAPPINGS)
        self.mocks["_load_mappings"] = mappings_mock
        mappings_patcher = patch(f"{_MODULE}._load_mappings", new=mappings_mock)
        mappings_patcher.start()
        self.addCleanup(mappings_patcher.stop)

    def _current(self, attribute: str):
        def read(*args, **kwargs):
            return getattr(self, attribute)

        return read


class TestInvariants(SetupPlanTestCase):
    @pytest.mark.asyncio
    async def test_every_mapping_suggestion_carries_the_url_fix(self):
        # Asserted across the whole plan rather than per call site, so a new builder
        # that forgets the pairing fails here.
        self.utm_mappings = UtmMappingSuggestionsResponse(
            source_suggestions=[
                SourceMappingSuggestion(
                    raw_utm_source="fb-ads",
                    suggested_target="meta_ads",
                    suggested_target_display_name="Meta Ads",
                    reason="'fb-ads' contains a known alias of Meta Ads.",
                    event_count_30d=500,
                )
            ]
        )
        self.campaigns = [
            Campaign("spring_sale_2024", "1", "google", 8200.0, 0, 0),
            *[Campaign(f"c{i}", str(i), "google", 100.0, 0, 0) for i in range(9)],
        ]
        self.utm_events = {("sprng_sale_2024", "google"): 1340}

        plan = await get_setup_plan(self.team)

        mapping_suggestions = [s for s in plan.suggestions if s.kind in MAPPING_KINDS]
        assert mapping_suggestions, "expected the fixture to produce mapping suggestions"
        for suggestion in mapping_suggestions:
            ops = [op.op for op in suggestion.also_recommended]
            assert "fix_platform_urls" in ops, f"{suggestion.id} has no URL fix"

    @pytest.mark.asyncio
    async def test_campaign_proposals_are_injected_rather_than_derived_twice(self):
        # `suggest_utm_mappings` derives its own proposals when none are passed, and doing so
        # re-reads campaigns, the UTM catalogue and team mappings — all three of which this
        # function already gathered. Leaving the argument off meant three redundant queries plus
        # a second fuzzy pass, and two independently-computed proposal sets in one response that
        # could disagree. The injection parameter exists precisely to prevent that.
        self.campaigns = [
            Campaign("spring_sale_2024", "1", "google", 8200.0, 0, 0),
            *[Campaign(f"c{i}", str(i), "google", 100.0, 0, 0) for i in range(9)],
        ]
        self.utm_events = {("sprng_sale_2024", "google"): 1340}

        await get_setup_plan(self.team)

        await_args = self.mocks["suggest_utm_mappings"].await_args
        assert await_args is not None, "suggest_utm_mappings was never awaited"
        proposals = await_args.kwargs.get("campaign_proposals")
        assert proposals is not None, "campaign_proposals was not injected"
        # The same object the plan builds its own suggestions from, not an equal-looking copy.
        assert [p.raw_utm_campaign for p in proposals.proposals] == ["sprng_sale_2024"]

    @pytest.mark.asyncio
    async def test_summary_separates_partial_capabilities_from_blocked_ones(self):
        # Counting only UNLOCKED reported "0 of 4 capabilities unlocked" for a team whose four were
        # all partial — which reads as nothing working at all.
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration("google_ads", "GoogleAds", status="healthy"),
                _integration("meta_ads", "MetaAds", status="sync_broken"),
            ],
            overall_status="degraded",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        assert any(r.status == ReadinessStatus.PARTIAL for r in plan.readiness)
        assert "partial" in plan.summary

    def test_a_mapping_kind_cannot_be_built_without_the_url_fix(self):
        # This used to live in a helper the builders had to remember, plus a hardcoded copy of
        # the kind set here — so a new mapping kind bypassed both.
        with pytest.raises(ValidationError) as error:
            Suggestion(
                id="add_source_mapping:x",
                kind=SuggestionKind.ADD_SOURCE_MAPPING,
                severity=Severity.WARNING,
                confidence=0.9,
                title="t",
                evidence="e",
            )

        assert "fix_platform_urls" in str(error.value)

    @pytest.mark.asyncio
    async def test_a_failing_campaign_suggester_degrades_only_its_own_section(self):
        # These run outside the gather, so an unwrapped raise took the whole plan down.
        self.campaigns = [Campaign("spring_sale_2024", "1", "google", 8200.0, 0, 0)]
        self.utm_events = {("sprng_sale_2024", "google"): 1340}

        with patch(f"{_MODULE}.build_audit", side_effect=RuntimeError("bad row")):
            plan = await get_setup_plan(self.team)

        assert "campaign_suggesters" in plan.degraded
        assert not [s for s in plan.suggestions if s.kind in MAPPING_KINDS]
        # The rest of the plan survived, which is the whole point.
        assert plan.readiness

    @pytest.mark.asyncio
    async def test_output_is_byte_stable_across_runs(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration("google_ads", "GoogleAds", status="sync_broken"),
                _integration("meta_ads", "MetaAds", status="events_only", unmatched=900),
            ],
            overall_status="broken",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        first = await get_setup_plan(self.team)
        second = await get_setup_plan(self.team)

        assert first.model_dump(mode="json") == second.model_dump(mode="json")

    @pytest.mark.asyncio
    async def test_suggestion_ids_are_deterministic_not_positional(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration("meta_ads", "MetaAds", status="events_only", unmatched=900)],
            overall_status="degraded",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        # The frontend remembers dismissals by id, so it must describe the finding.
        assert "connect_source:meta_ads" in [s.id for s in plan.suggestions]


class TestRanking(SetupPlanTestCase):
    @pytest.mark.asyncio
    async def test_unblocking_action_outranks_a_higher_volume_one(self):
        # Connecting the platform unblocks the goal-flag work, so it must come first
        # even though the goal suggestion carries far more event volume.
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration("meta_ads", "MetaAds", status="events_only", unmatched=10)],
            overall_status="degraded",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal(count=5_000_000)]),
        )
        self.goal_flags = {"g1": {}}

        plan = await get_setup_plan(self.team)

        kinds = [s.kind for s in plan.suggestions]
        assert kinds[0] == SuggestionKind.CONNECT_SOURCE
        assert SuggestionKind.MARK_GOAL_AS_REVENUE in kinds
        assert kinds.index(SuggestionKind.CONNECT_SOURCE) < kinds.index(SuggestionKind.MARK_GOAL_AS_REVENUE)

    @pytest.mark.asyncio
    async def test_errors_outrank_warnings_at_equal_unblocking(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration("google_ads", "GoogleAds", status="events_broken"),
                _integration("meta_ads", "MetaAds", status="schema_misconfigured", schema_missing=["cost"]),
            ],
            overall_status="degraded",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        severities = [s.severity for s in plan.suggestions]
        assert severities[0] == Severity.ERROR


class TestDegradation(SetupPlanTestCase):
    @pytest.mark.asyncio
    async def test_diagnostic_failure_propagates(self):
        # An empty plan would read as "you're all set", which is worse than an error.
        self.mocks["get_marketing_diagnostic"].side_effect = RuntimeError("clickhouse down")

        with pytest.raises(RuntimeError):
            await get_setup_plan(self.team)

    @pytest.mark.asyncio
    async def test_leaf_failure_degrades_without_losing_the_plan(self):
        self.mocks["get_attribution_health"].side_effect = RuntimeError("timeout")
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration("google_ads", "GoogleAds", status="sync_broken")],
            overall_status="broken",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        assert "attribution_health" in plan.degraded
        assert any(s.kind == SuggestionKind.FIX_SYNC for s in plan.suggestions)
        assert "Incomplete" in plan.summary

    @pytest.mark.asyncio
    async def test_campaign_query_failure_skips_only_campaign_suggestions(self):
        # A fixture that *would* produce campaign suggestions, or the absence proves nothing:
        # the plan skips the suggesters on empty input anyway.
        self.campaigns = [
            Campaign("spring_sale_2024", "1", "google", 8200.0, 0, 0),
            *[Campaign(f"c{i}", str(i), "google", 100.0, 0, 0) for i in range(9)],
        ]
        self.utm_events = {("sprng_sale_2024", "google"): 1340}
        self.mocks["get_campaigns_with_spend_async"].side_effect = RuntimeError("nope")

        plan = await get_setup_plan(self.team)

        assert "campaigns" in plan.degraded
        assert not [s for s in plan.suggestions if s.kind == SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING]


class TestReadiness(SetupPlanTestCase):
    def _readiness(self, plan, capability):
        return next(r for r in plan.readiness if r.capability == capability)

    @pytest.mark.asyncio
    async def test_cost_blocked_when_nothing_is_connected(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration("google_ads", "GoogleAds", status="not_connected")],
            overall_status="no_sources",
            conversion_goals=ConversionGoalsListResponse(goals=[]),
        )

        plan = await get_setup_plan(self.team)

        assert self._readiness(plan, Capability.COST).status == ReadinessStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_cost_partial_when_some_integrations_are_broken(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration("google_ads", "GoogleAds", status="healthy"),
                _integration("meta_ads", "MetaAds", status="sync_broken"),
            ],
            overall_status="degraded",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        assert self._readiness(plan, Capability.COST).status == ReadinessStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_roas_blocked_without_a_revenue_flagged_goal(self):
        # Goals exist and spend is fine, yet ROAS stays empty — what readiness is for.
        self.goal_flags = {"g1": {"counts_as_customer": True}}

        plan = await get_setup_plan(self.team)

        roas = self._readiness(plan, Capability.ROAS)
        assert roas.status == ReadinessStatus.BLOCKED
        assert "counts_as_revenue" in roas.explanation
        assert self._readiness(plan, Capability.CAC).status == ReadinessStatus.UNLOCKED

    @pytest.mark.asyncio
    async def test_readiness_links_back_to_the_blocking_suggestions(self):
        self.goal_flags = {"g1": {}}

        plan = await get_setup_plan(self.team)

        # An exact set: "non-empty and a subset" also passes when `_blockers` ignores the
        # capability and returns everything. Both are present here; only one unlocks ROAS.
        roas = self._readiness(plan, Capability.ROAS)
        assert {s.id for s in plan.suggestions} == {"mark_goal_as_revenue:any", "mark_goal_as_customer:any"}
        assert set(roas.blocked_by) == {"mark_goal_as_revenue:any"}
        assert set(self._readiness(plan, Capability.CAC).blocked_by) == {"mark_goal_as_customer:any"}

    @pytest.mark.asyncio
    async def test_roas_names_both_gaps_when_spend_is_missing_too(self):
        # Three of the five branches differ only in their explanation, so a swap would change
        # what the user is told next while every status stayed correct.
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration("google_ads", "GoogleAds", status="not_connected")],
            overall_status="no_sources",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )
        self.goal_flags = {"g1": {}}

        plan = await get_setup_plan(self.team)

        roas = self._readiness(plan, Capability.ROAS)
        assert roas.status == ReadinessStatus.BLOCKED
        assert "Needs spend data and a conversion goal" in roas.explanation

    @pytest.mark.asyncio
    async def test_roas_blames_only_the_spend_when_the_goal_is_flagged(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration("google_ads", "GoogleAds", status="not_connected")],
            overall_status="no_sources",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        roas = self._readiness(plan, Capability.ROAS)
        assert roas.status == ReadinessStatus.BLOCKED
        assert roas.explanation == "A goal is flagged, but there is no spend data to divide by."

    @pytest.mark.asyncio
    async def test_roas_is_partial_when_only_some_integrations_report_spend(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration("google_ads", "GoogleAds", status="healthy"),
                _integration("meta_ads", "MetaAds", status="sync_broken"),
            ],
            overall_status="degraded",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        roas = self._readiness(plan, Capability.ROAS)
        assert roas.status == ReadinessStatus.PARTIAL
        assert roas.explanation == "Available, but only for the integrations whose spend is readable."

    @pytest.mark.asyncio
    async def test_attribution_blocked_when_no_utm_events_arrive(self):
        self.attribution = _attribution(total=0, matched=0)

        plan = await get_setup_plan(self.team)

        assert self._readiness(plan, Capability.ATTRIBUTION).status == ReadinessStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_attribution_partial_when_most_events_do_not_match(self):
        self.attribution = _attribution(total=1000, matched=300)

        plan = await get_setup_plan(self.team)

        attribution = self._readiness(plan, Capability.ATTRIBUTION)
        assert attribution.status == ReadinessStatus.PARTIAL
        assert "30%" in attribution.explanation


class TestConversionGoals(SetupPlanTestCase):
    @pytest.mark.asyncio
    async def test_names_the_best_candidate_event_when_no_goals_exist(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration()],
            overall_status="healthy",
            conversion_goals=ConversionGoalsListResponse(goals=[]),
        )
        self.candidates = EventSuggestionsResponse(
            candidates=[
                CandidateEvent(
                    event_name="purchase_completed",
                    last_30d_count=4200,
                    distinct_users_30d=3100,
                    pct_with_utm_source=0.82,
                    pct_with_utm_campaign=0.8,
                    top_utm_sources=[("google", 2000)],
                    is_already_a_goal=False,
                    suggestion_score=0.9,
                    suggestion_reason="high volume, well tagged",
                )
            ]
        )
        self.goal_flags = {}

        plan = await get_setup_plan(self.team)

        create = next(s for s in plan.suggestions if s.kind == SuggestionKind.CREATE_CONVERSION_GOAL)
        assert "purchase_completed" in create.evidence
        assert "4,200" in create.evidence

    @pytest.mark.asyncio
    async def test_misconfigured_goal_is_an_error(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration()],
            overall_status="healthy",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal(misconfigured=True)], has_misconfigured=True),
        )

        plan = await get_setup_plan(self.team)

        fix = next(s for s in plan.suggestions if s.kind == SuggestionKind.FIX_CONVERSION_GOAL)
        assert fix.severity == Severity.ERROR
        assert "deleted action" in fix.evidence

    @pytest.mark.asyncio
    async def test_goal_flag_suggestions_are_never_batch_applied(self):
        self.goal_flags = {"g1": {}}

        plan = await get_setup_plan(self.team)

        flag_kinds = {SuggestionKind.MARK_GOAL_AS_REVENUE, SuggestionKind.MARK_GOAL_AS_CUSTOMER}
        flags = [s for s in plan.suggestions if s.kind in flag_kinds]
        assert flags
        assert all(s.safe_to_batch is False for s in flags)


class TestConnectSourceNeedsPaidEvidence(SetupPlanTestCase):
    """`utm_source` maps to an ad platform on the source alone, so `google` also catches
    gmail links and `linkedin` catches organic posts. Suggesting someone connect an ad
    account they don't run is worse than saying nothing."""

    async def _plan_for(self, *, matched=900, **kwargs):
        # `matched`, not `unmatched`: tagged_medium is only accumulated for rows that
        # resolved to an integration, so tagged traffic with zero matched can't happen.
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[_integration("linkedin_ads", "LinkedinAds", status="events_only", matched=matched, **kwargs)],
            overall_status="broken",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )
        return await get_setup_plan(self.team)

    def _connects(self, plan) -> list:
        return [s for s in plan.suggestions if s.kind == SuggestionKind.CONNECT_SOURCE]

    @pytest.mark.asyncio
    async def test_organic_traffic_alone_does_not_ask_you_to_connect_an_ad_account(self):
        plan = await self._plan_for(tagged_medium=900, paid=0)

        assert self._connects(plan) == []

    @pytest.mark.asyncio
    async def test_paid_traffic_still_asks_you_to_connect(self):
        plan = await self._plan_for(tagged_medium=900, paid=900)

        assert len(self._connects(plan)) == 1

    @pytest.mark.asyncio
    async def test_one_paid_event_among_organic_is_enough_to_ask(self):
        # Spend exists; the mix says the team runs both, not that it runs neither.
        plan = await self._plan_for(tagged_medium=900, paid=1)

        assert len(self._connects(plan)) == 1

    @pytest.mark.asyncio
    async def test_untagged_traffic_still_asks_because_absence_is_not_evidence(self):
        # A team that never sets utm_medium tells us nothing either way, and staying
        # silent there would hide the case this suggestion exists for.
        plan = await self._plan_for(tagged_medium=0, paid=0)

        assert len(self._connects(plan)) == 1

    @pytest.mark.asyncio
    async def test_a_tagged_minority_does_not_speak_for_the_untagged_rest(self):
        # Tagged organic posts plus a larger body of untagged traffic. The untagged half
        # is unclassified, not organic, and it's exactly where unlinked ad spend hides —
        # so a team that tags its posts but not its ad links still gets asked.
        plan = await self._plan_for(matched=900, tagged_medium=100, paid=0)

        assert len(self._connects(plan)) == 1


class TestIntegrationSuggestions(SetupPlanTestCase):
    @pytest.mark.asyncio
    async def test_auth_error_becomes_a_reconnect_with_a_valid_oauth_kind(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration("snapchat_ads", "SnapchatAds", status="sync_broken", last_error="token expired")
            ],
            overall_status="broken",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        reconnect = next(s for s in plan.suggestions if s.kind == SuggestionKind.RECONNECT_OAUTH)
        # Narrowed, not indexed: only OpenOauth carries `kind`, so this also pins the op type.
        assert isinstance(reconnect.apply, OpenOauth)
        assert reconnect.apply.kind == "snapchat"

    @pytest.mark.asyncio
    async def test_non_auth_sync_error_becomes_fix_sync_not_reconnect(self):
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration("google_ads", "GoogleAds", status="sync_broken", last_error="rate limit exceeded")
            ],
            overall_status="broken",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        assert any(s.kind == SuggestionKind.FIX_SYNC for s in plan.suggestions)
        assert not any(s.kind == SuggestionKind.RECONNECT_OAUTH for s in plan.suggestions)

    @parameterized.expand(
        [
            ("exact_utm_source_match_only", 0, 700, 700),
            ("fuzzy_match_only", 500, 0, 500),
            ("both_kinds_of_match", 500, 700, 1200),
        ]
    )
    @pytest.mark.asyncio
    async def test_connect_suggestion_counts_every_event_carrying_the_utm_source(
        self, _name, unmatched, matched, expected
    ):
        # `events_only` is set when either counter is non-zero, so a platform whose utm_source
        # matched exactly used to advertise "0 events" as the reason to connect it.
        self.diagnostic = MarketingDiagnosticResponse(
            integrations=[
                _integration(
                    "pinterest_ads", "PinterestAds", status="events_only", unmatched=unmatched, matched=matched
                )
            ],
            overall_status="degraded",
            conversion_goals=ConversionGoalsListResponse(goals=[_goal()]),
        )

        plan = await get_setup_plan(self.team)

        connect = next(s for s in plan.suggestions if s.kind == SuggestionKind.CONNECT_SOURCE)
        assert connect.event_volume == expected
        assert f"{expected:,} events" in connect.evidence

    @pytest.mark.asyncio
    async def test_healthy_integration_produces_nothing(self):
        plan = await get_setup_plan(self.team)

        integration_kinds = {
            SuggestionKind.CONNECT_SOURCE,
            SuggestionKind.RECONNECT_OAUTH,
            SuggestionKind.FIX_SYNC,
            SuggestionKind.MAP_SCHEMA_COLUMNS,
        }
        assert not [s for s in plan.suggestions if s.kind in integration_kinds]
