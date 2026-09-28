from datetime import UTC, datetime, timedelta
from uuid import UUID

import time_machine
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
from posthog.hogql.context import HogQLContext
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
    PRECOMPUTE_ONLY_MAX_STALE_SECONDS,
    REVALIDATION_TRIGGER,
)


class TestAttributionSessionsRead(SimpleTestCase):
    def setUp(self) -> None:
        self.enterContext(
            patch.object(
                MarketingAnalyticsAttributionQueryRunner,
                "_shared_hogql_context",
                new_callable=PropertyMock,
                return_value=HogQLContext(team_id=1),
            )
        )
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

    @parameterized.expand(
        [
            ("fixed", "UTC", "2023-04-01T12:00:00Z", "2023-01-01", "2023-03-31", 90, 90, None),
            ("utc", "UTC", "2024-07-05T12:00:00Z", "-90d", None, 30, 90, None),
            ("west", "America/Los_Angeles", "2024-07-05T02:00:00Z", "-90d", None, 30, 90, None),
            ("east", "Pacific/Auckland", "2024-07-05T16:00:00Z", "-90d", None, 90, 90, None),
            ("spring", "America/Los_Angeles", "2024-03-15T18:00:00Z", "-90d", None, 30, 90, None),
            ("fall", "America/Los_Angeles", "2024-11-15T18:00:00Z", "-90d", None, 30, 90, None),
            ("configured", "UTC", "2024-07-05T12:00:00Z", "-7d", None, 7, 7, None),
            ("too_wide", "UTC", "2024-07-05T12:00:00Z", "-91d", None, 30, 90, "window_over_max"),
        ]
    )
    def test_display_window_fits_writer_coverage(
        self,
        _name: str,
        timezone: str,
        now: str,
        date_from: str,
        date_to: str | None,
        lookback: int,
        display_days: int,
        expected_reason: str | None,
    ) -> None:
        self.team.timezone = timezone
        self.team.marketing_analytics_config.attribution_window_days = lookback
        with (
            time_machine.travel(now, tick=False),
            patch.object(marketing_sessions_precompute, "PRECOMPUTE_WINDOW_DAYS", display_days),
        ):
            runner = MarketingAnalyticsAttributionQueryRunner(
                team=self.team,
                modifiers=HogQLQueryModifiers(personsOnEventsMode="person_id_override_properties_on_events"),
                query=MarketingAnalyticsAttributionQuery(
                    conversionGoalId="goal",
                    properties=[],
                    dateRange=DateRange(date_from=date_from, date_to=date_to),
                ),
            )
            assert runner.lookback_window_days == lookback
            assert attribution_sessions_read.ineligible_reason(runner, runner.query_date_range) == expected_reason
            if expected_reason is None:
                read = attribution_sessions_read.window(runner, runner.query_date_range)
                required_start = read.start - timedelta(days=marketing_sessions_precompute.SESSION_READ_REACHBACK_DAYS)
                assert (
                    marketing_sessions_precompute.precompute_window_start(self.team, datetime.now(UTC))
                    <= required_start
                )

    @parameterized.expand(
        [
            ("stale_user", False, True, True),
            ("revalidation", True, False, True),
            ("cold_user", False, False, False),
        ]
    )
    def test_stale_policy_and_revalidation(self, _name: str, refreshing: bool, stale: bool, ready: bool) -> None:
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
                marketing_sessions_precompute, "create_default_modifiers_for_team", return_value=runner.modifiers
            ),
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
                None if refreshing else PRECOMPUTE_ONLY_MAX_STALE_SECONDS
            )
            assert revalidate.call_count == int(stale)

    def test_failed_precompute_lookup_falls_back(self) -> None:
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
        with patch.object(
            attribution_sessions_read,
            "ensure_marketing_sessions_precomputed",
            side_effect=RuntimeError("Precompute lookup failed"),
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
                "custom_channel_rules_mismatch",
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
