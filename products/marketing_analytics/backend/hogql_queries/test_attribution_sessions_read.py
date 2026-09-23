from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from unittest.mock import PropertyMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    ConversionGoalFilter1,
    CustomChannelRule,
    DateRange,
    HogQLQueryModifiers,
    MarketingAnalyticsAttributionQuery,
    PropertyMathType,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.query_tagging import Feature, tags_context
from posthog.models import Organization, Team
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationQuery,
    LazyComputationResult,
    LazyComputationTable,
    compute_query_hash,
)
from products.marketing_analytics.backend.hogql_queries import attribution_sessions_read, marketing_sessions_precompute
from products.marketing_analytics.backend.hogql_queries.attribution_table_query_runner import (
    MarketingAnalyticsAttributionQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_lazy_precompute import (
    REVALIDATION_TRIGGER,
    STALE_WHILE_REVALIDATE_SECONDS,
)


class TestAttributionSessionsRead(SimpleTestCase):
    def setUp(self) -> None:
        self.enterContext(
            patch.object(
                MarketingAnalyticsAttributionQueryRunner,
                "_shared_hogql_context",
                new_callable=PropertyMock,
                return_value=None,
            )
        )
        self.coverage = self.enterContext(
            patch.object(
                attribution_sessions_read, "execute_hogql_query", return_value=SimpleNamespace(results=[], error=None)
            )
        )
        self.enterContext(patch.object(attribution_sessions_read, "serve_stale_enabled", return_value=False))
        self.team = Team(id=1, organization=Organization(id=UUID(int=1)))
        self.team.modifiers = {"personsOnEventsMode": "person_id_override_properties_on_events"}
        config = TeamMarketingAnalyticsConfig(team=self.team)
        config.conversion_goals = [
            ConversionGoalFilter1(
                event="purchase",
                name="Purchases",
                conversion_goal_id="goal",
                conversion_goal_name="Purchases",
                schema_map={},
                math=PropertyMathType.SUM,
                math_property="revenue",
            ).model_dump()
        ]
        self.enterContext(
            patch.object(Team, "marketing_analytics_config", new_callable=PropertyMock, return_value=config)
        )
        self.enterContext(
            patch(
                "products.marketing_analytics.backend.hogql_queries.marketing_analytics_config.feature_enabled_or_false",
                return_value=False,
            )
        )
        self.enterContext(patch.object(attribution_sessions_read, "team_has_property_access_rules", return_value=False))

    @parameterized.expand([("repeat", True), ("first_only", False)])
    def test_session_join_does_not_repeat_revenue_aggregation(self, _name: str, repeat: bool) -> None:
        runner = MarketingAnalyticsAttributionQueryRunner(
            team=self.team,
            modifiers=HogQLQueryModifiers(personsOnEventsMode="person_id_override_properties_on_events"),
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId="goal",
                properties=[],
                dateRange=DateRange(date_from="2023-01-10", date_to="2023-01-11"),
                lookbackWindowDays=4,
                allowMultipleConversionsPerVisitor=repeat,
            ),
        )
        with patch.object(
            attribution_sessions_read,
            "ensure_marketing_sessions_precomputed",
            return_value=LazyComputationResult(ready=True, job_ids=[UUID(int=1)]),
        ):
            runner.config.sessions_precomputation_enabled = True
            query = attribution_sessions_read.build_person_arrays(runner, runner.query_date_range)
            assert query is not None
            query.ctes = attribution_sessions_read.session_ctes(runner, runner.query_date_range)
        assert query is not None
        sql = query.to_hogql()
        assert sql.count("groupArray(") == 1
        assert sql.count("events.properties.revenue") == 1
        assert "AS first_conversion" in sql
        assert ("conv.last_conversion" in sql) is repeat

    def test_default_lookback_and_ninety_display_days_fit_writer_coverage(self) -> None:
        runner = MarketingAnalyticsAttributionQueryRunner(
            team=self.team,
            modifiers=HogQLQueryModifiers(personsOnEventsMode="person_id_override_properties_on_events"),
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId="goal",
                properties=[],
                dateRange=DateRange(date_from="2023-01-01", date_to="2023-03-31"),
            ),
        )
        assert runner.lookback_window_days == 90
        assert marketing_sessions_precompute.precompute_window_days(self.team) == 181
        assert attribution_sessions_read.ineligible_reason(runner, runner.query_date_range) is None
        with patch.object(
            attribution_sessions_read,
            "window",
            return_value=attribution_sessions_read.ReadWindow(
                start=datetime(2023, 1, 1, tzinfo=UTC), end=datetime(2023, 7, 1, tzinfo=UTC)
            ),
        ):
            assert attribution_sessions_read.ineligible_reason(runner, runner.query_date_range) == "window_over_max"

    @parameterized.expand(
        [
            ("stale_user", True, False, True, True),
            ("flag_off", False, False, False, False),
            ("revalidation", True, True, False, True),
            ("cold_user", True, False, False, False),
        ]
    )
    def test_stale_policy_and_revalidation(
        self, _name: str, flag: bool, refreshing: bool, stale: bool, ready: bool
    ) -> None:
        runner = MarketingAnalyticsAttributionQueryRunner(
            team=self.team,
            modifiers=HogQLQueryModifiers(personsOnEventsMode="person_id_override_properties_on_events"),
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId="goal",
                properties=[],
                lookbackWindowDays=4,
                dateRange=DateRange(date_from="2023-01-10", date_to="2023-01-11"),
            ),
        )
        with (
            tags_context(trigger=REVALIDATION_TRIGGER if refreshing else "test", feature=Feature.QUERY),
            patch.object(
                marketing_sessions_precompute,
                "execute_hogql_query",
                return_value=SimpleNamespace(results=[], error=None),
            ),
            patch.object(
                marketing_sessions_precompute, "create_default_modifiers_for_team", return_value=runner.modifiers
            ),
            patch.object(attribution_sessions_read, "serve_stale_enabled", return_value=flag),
            patch.object(attribution_sessions_read, "handle_stale_served") as revalidate,
            patch.object(
                marketing_sessions_precompute,
                "ensure_precomputed",
                return_value=LazyComputationResult(ready=ready, stale=stale, job_ids=[UUID(int=1)] if ready else []),
            ) as ensure,
        ):
            result = attribution_sessions_read._ensure(runner, runner.query_date_range)
            assert (result is not None) is ready
            assert attribution_sessions_read._ensure(runner, runner.query_date_range) == result
            ensure.assert_called_once()
            assert ensure.call_args.kwargs["run_inserts"] is refreshing
            assert ensure.call_args.kwargs["stale_while_revalidate_seconds"] == (
                STALE_WHILE_REVALIDATE_SECONDS if flag and not refreshing else None
            )
            assert revalidate.call_count == int(stale)
            assert self.coverage.call_count == int(ready)

    @parameterized.expand([("older_session", [[1]], None), ("unproven", [], "Coverage query failed")])
    def test_unproven_session_coverage_falls_back(self, _name: str, rows: list[list[int]], error: str | None) -> None:
        runner = MarketingAnalyticsAttributionQueryRunner(
            team=self.team,
            modifiers=HogQLQueryModifiers(personsOnEventsMode="person_id_override_properties_on_events"),
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId="goal",
                properties=[],
                lookbackWindowDays=4,
                dateRange=DateRange(date_from="2023-01-10", date_to="2023-01-11"),
            ),
        )
        self.coverage.return_value.results = rows
        self.coverage.return_value.error = error
        with patch.object(
            attribution_sessions_read,
            "ensure_marketing_sessions_precomputed",
            return_value=LazyComputationResult(ready=True, job_ids=[UUID(int=1)]),
        ) as ensure:
            assert attribution_sessions_read.build_person_arrays(runner, runner.query_date_range) is None
        ensure.assert_called_once()

    @parameterized.expand(
        [
            (HogQLQueryModifiers(), HogQLQueryModifiers(sessionTableVersion="v1"), "session_table_version_mismatch"),
            (HogQLQueryModifiers(), HogQLQueryModifiers(sessionsV2JoinMode="string"), "session_join_mode_mismatch"),
            (HogQLQueryModifiers(), HogQLQueryModifiers(convertToProjectTimezone=False), "project_timezone_disabled"),
            (HogQLQueryModifiers(convertToProjectTimezone=False), HogQLQueryModifiers(), "project_timezone_disabled"),
            (
                HogQLQueryModifiers(
                    customChannelTypeRules=[
                        CustomChannelRule(id="custom", channel_type="Custom", combiner="AND", items=[])
                    ]
                ),
                HogQLQueryModifiers(customChannelTypeRules=[]),
                "custom_channel_rules",
            ),
        ]
    )
    def test_incompatible_dimension_modifiers_fall_back(
        self, team_modifiers: HogQLQueryModifiers, query_modifiers: HogQLQueryModifiers, reason: str
    ) -> None:
        self.team.modifiers.update(team_modifiers.model_dump(exclude_none=True))
        self.team.timezone = "America/New_York"
        runner = MarketingAnalyticsAttributionQueryRunner(
            team=self.team,
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId="goal",
                properties=[],
                lookbackWindowDays=4,
                dateRange=DateRange(date_from="2023-01-10", date_to="2023-01-11"),
                modifiers=query_modifiers,
            ),
        )
        assert attribution_sessions_read.ineligible_reason(runner, runner.query_date_range) == reason
        with patch.object(attribution_sessions_read, "ensure_marketing_sessions_precomputed") as ensure:
            assert attribution_sessions_read.build_person_arrays(runner, runner.query_date_range) is None
        ensure.assert_not_called()
        self.coverage.assert_not_called()

    @parameterized.expand(
        [
            ("America/New_York", "2025-11-02T01:30:00-04:00", "2025-11-03", True, True),
            ("America/New_York", "2025-11-02T01:30:00-05:00", "2025-11-03", True, True),
            ("America/New_York", "2025-11-01", "2025-11-02T01:30:00-04:00", True, True),
            ("America/New_York", "2025-11-01", "2025-11-02T01:30:00-05:00", True, True),
            ("America/New_York", "2025-11-01", "2025-11-03", False, False),
            ("America/Santiago", "2025-04-04", "2025-04-05", False, True),
            ("America/Santiago", "2025-04-04", "2025-04-06", False, False),
        ]
    )
    def test_ambiguous_date_boundaries_fall_back(
        self, timezone: str, date_from: str, date_to: str, explicit: bool, ambiguous: bool
    ) -> None:
        self.team.timezone = timezone
        runner = MarketingAnalyticsAttributionQueryRunner(
            team=self.team,
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId="goal",
                properties=[],
                lookbackWindowDays=4,
                dateRange=DateRange(date_from=date_from, date_to=date_to, explicitDate=explicit),
            ),
        )
        assert attribution_sessions_read.ineligible_reason(runner, runner.query_date_range) == (
            "ambiguous_date_boundary" if ambiguous else None
        )

    def test_classifier_changes_invalidate_shared_query_identity(self) -> None:
        def identity() -> str:
            query = parse_select(
                marketing_sessions_precompute.SESSIONS_INSERT_TEMPLATE,
                placeholders={
                    **marketing_sessions_precompute.base_placeholders(),
                    "time_window_min": ast.Constant(value="MIN"),
                    "time_window_max": ast.Constant(value="MAX"),
                },
            )
            assert isinstance(query, ast.SelectQuery)
            return compute_query_hash(
                LazyComputationQuery(
                    query=query,
                    table=LazyComputationTable.WEB_SESSIONS_DIMENSIONAL_PREAGGREGATED,
                )
            )

        original = identity()
        assert identity() == original
        with patch.object(marketing_sessions_precompute, "SESSION_CHANNEL_CLASSIFIER_VERSION", 2):
            assert identity() != original
        with patch.object(
            marketing_sessions_precompute,
            "expand_default_channel_type_call",
            return_value=ast.Constant(value="Changed"),
        ):
            assert identity() != original

    def test_disabled_reader_does_not_check_jobs_or_session_coverage(self) -> None:
        runner = MarketingAnalyticsAttributionQueryRunner(
            team=self.team,
            modifiers=HogQLQueryModifiers(personsOnEventsMode="person_id_override_properties_on_events"),
            query=MarketingAnalyticsAttributionQuery(
                conversionGoalId="goal",
                properties=[],
                lookbackWindowDays=4,
                dateRange=DateRange(date_from="2023-01-10", date_to="2023-01-11"),
            ),
        )
        runner.config.sessions_precomputation_enabled = False
        with patch.object(attribution_sessions_read, "ensure_marketing_sessions_precomputed") as ensure:
            runner.to_query()
        ensure.assert_not_called()
        self.coverage.assert_not_called()
