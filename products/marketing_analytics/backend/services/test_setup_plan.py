import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

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
    Capability,
    OpenOauth,
    ReadinessStatus,
    Severity,
    SuggestionKind,
)
from products.marketing_analytics.backend.services.types import Campaign, TeamMappings

_MODULE = "products.marketing_analytics.backend.services.setup_plan"

NO_MAPPINGS = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})

# Mapping suggestions carry these kinds, and every one of them must be paired with
# "fix the ad URL" advice — the mapping is a band-aid, the URL is the cure.
_MAPPING_KINDS = {SuggestionKind.ADD_SOURCE_MAPPING, SuggestionKind.ADD_CAMPAIGN_NAME_MAPPING}


def _integration(
    key="google_ads",
    source_type="GoogleAds",
    status="healthy",
    last_error=None,
    schema_missing=None,
    unmatched=0,
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
    if unmatched:
        from products.marketing_analytics.backend.services.attribution_health import AttributionHealthEntry

        attribution = AttributionHealthEntry(
            integration_key=key,
            display_name=key,
            events_with_utm_last_7d=unmatched,
            events_matched_last_7d=0,
            events_unmatched_likely_yours_last_7d=unmatched,
            last_event_with_matching_utm_at=None,
            matched_pct=0.0,
            sample_unmatched_utm_sources=[],
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
        id=goal_id,
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

        mapping_suggestions = [s for s in plan.suggestions if s.kind in _MAPPING_KINDS]
        assert mapping_suggestions, "expected the fixture to produce mapping suggestions"
        for suggestion in mapping_suggestions:
            ops = [op.op for op in suggestion.also_recommended]
            assert "fix_platform_urls" in ops, f"{suggestion.id} has no URL fix"

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
        # And the summary says so, so the UI can't present it as complete.
        assert "Incomplete" in plan.summary

    @pytest.mark.asyncio
    async def test_campaign_query_failure_skips_only_campaign_suggestions(self):
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
        # The goals exist and spend is fine, but ROAS stays empty and nothing on the
        # dashboard explains why — that's exactly what readiness is for.
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

        roas = self._readiness(plan, Capability.ROAS)
        assert roas.blocked_by
        assert set(roas.blocked_by) <= {s.id for s in plan.suggestions}

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
        # Evidence has to be checkable at a glance, so it names the event and numbers.
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
        # Which goal counts as revenue is a business decision, not a config fix.
        self.goal_flags = {"g1": {}}

        plan = await get_setup_plan(self.team)

        flag_kinds = {SuggestionKind.MARK_GOAL_AS_REVENUE, SuggestionKind.MARK_GOAL_AS_CUSTOMER}
        flags = [s for s in plan.suggestions if s.kind in flag_kinds]
        assert flags
        assert all(s.safe_to_batch is False for s in flags)


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
        # Narrowed rather than indexed: `apply` is the whole ApplyOp union, and only OpenOauth
        # carries `kind`. This also pins that a reconnect emits that op and not another.
        assert isinstance(reconnect.apply, OpenOauth)
        # Snapchat registers as "snapchat", not "snapchat-ads" — a derived kebab-case
        # kind would 400 on authorize.
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
