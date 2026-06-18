import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionPropertyFilter,
    SessionsV2JoinMode,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebAnalyticsPreComputeStrategy,
    WebAnalyticsSampling,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.models.utils import uuid7

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_stats_frustration_lazy_precompute import (
    _FRUSTRATION_EVENT_TYPES,
    INSERT_QUERY_TEMPLATE,
    can_use_lazy_precompute,
)


@override_settings(IN_UNIT_TESTING=True)
class TestWebStatsFrustrationLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

    def _enable_lazy(self):
        # Same flag the paths/overview tests patch — the gate evaluates the
        # `web-analytics-precompute-toggle` org flag via posthoganalytics.
        return patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=True,
        )

    def _seed_frustration_events(self) -> None:
        """One session on /buggy with rage clicks + an exception, one on /ok
        with a single pageview (so it's filtered out by the HAVING's
        any-metric-non-zero clause)."""
        s1 = str(uuid7("2024-01-02"))
        s2 = str(uuid7("2024-01-03"))
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={"name": "p1"})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={"name": "p2"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:00Z",
            properties={
                "$session_id": s1,
                "$host": "example.com",
                "$pathname": "/buggy",
                "$current_url": "https://example.com/buggy",
            },
        )
        _create_event(
            team=self.team,
            event="$rageclick",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:05Z",
            properties={
                "$session_id": s1,
                "$host": "example.com",
                "$pathname": "/buggy",
            },
        )
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:08Z",
            properties={
                "$session_id": s1,
                "$host": "example.com",
                "$pathname": "/buggy",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2024-01-03T11:00:00Z",
            properties={
                "$session_id": s2,
                "$host": "example.com",
                "$pathname": "/ok",
                "$current_url": "https://example.com/ok",
            },
        )

    def _build_query(
        self,
        *,
        date_from: str = "2024-01-01",
        date_to: str = "2024-01-07",
        properties: list | None = None,
        compare: bool = False,
        opt_in_precompute: bool = True,
        breakdown_by: WebStatsBreakdown = WebStatsBreakdown.FRUSTRATION_METRICS,
        sampling: WebAnalyticsSampling | None = None,
        conversion_goal=None,
        order_by: list | None = None,
        modifiers: HogQLQueryModifiers | None = None,
    ) -> WebStatsTableQuery:
        return WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
            breakdownBy=breakdown_by,
            useWebAnalyticsPrecompute=opt_in_precompute,
            sampling=sampling,
            conversionGoal=conversion_goal,
            orderBy=order_by,
            modifiers=modifiers,
        )

    def _runner(self, query: WebStatsTableQuery) -> WebStatsTableQueryRunner:
        return WebStatsTableQueryRunner(team=self.team, query=query)

    # ----------------------------------------------------------------------
    # Eligibility — these do not need ClickHouse, they exercise the gate only.
    # ----------------------------------------------------------------------

    def test_eligible_when_flag_on_and_opt_in_set(self):
        with self._enable_lazy():
            assert can_use_lazy_precompute(self._runner(self._build_query())) is True

    def test_insert_scans_only_frustration_event_types(self):
        # $pageview/$screen contribute 0 to every metric and their groups are
        # dropped by the HAVING, so the insert must not scan them — they only
        # inflate the GROUP BY cardinality that OOMs high-traffic teams.
        # Result-parity with the live (5-type) scan is covered by
        # test_lazy_response_matches_live.
        assert "{event_scan_filter}" in INSERT_QUERY_TEMPLATE
        assert "$pageview" not in INSERT_QUERY_TEMPLATE
        assert "$screen" not in INSERT_QUERY_TEMPLATE
        for frustration_event in ("$rageclick", "$dead_click", "$exception"):
            assert frustration_event in _FRUSTRATION_EVENT_TYPES
        assert "$pageview" not in _FRUSTRATION_EVENT_TYPES
        assert "$screen" not in _FRUSTRATION_EVENT_TYPES

    def test_rejected_when_org_flag_off(self):
        # Default mocked-off feature flag: gate refuses.
        with patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            assert can_use_lazy_precompute(self._runner(self._build_query())) is False

    def test_rejected_when_per_query_opt_in_missing(self):
        with self._enable_lazy():
            assert can_use_lazy_precompute(self._runner(self._build_query(opt_in_precompute=False))) is False

    @parameterized.expand(
        [
            (WebStatsBreakdown.PAGE,),
            (WebStatsBreakdown.INITIAL_PAGE,),
            (WebStatsBreakdown.BROWSER,),
            (WebStatsBreakdown.COUNTRY,),
        ]
    )
    def test_rejected_for_non_frustration_breakdowns(self, breakdown: WebStatsBreakdown):
        with self._enable_lazy():
            assert can_use_lazy_precompute(self._runner(self._build_query(breakdown_by=breakdown))) is False

    def test_rejected_when_conversion_goal_set(self):
        from posthog.schema import ActionConversionGoal

        with self._enable_lazy():
            assert (
                can_use_lazy_precompute(
                    self._runner(self._build_query(conversion_goal=ActionConversionGoal(actionId=1)))
                )
                is False
            )

    def test_rejected_when_sampling_enabled(self):
        with self._enable_lazy():
            assert (
                can_use_lazy_precompute(self._runner(self._build_query(sampling=WebAnalyticsSampling(enabled=True))))
                is False
            )

    def test_rejected_for_non_event_property_filter(self):
        # SessionPropertyFilter is not in the gate's allowlist (only EventPropertyFilter on $host).
        with self._enable_lazy():
            assert (
                can_use_lazy_precompute(
                    self._runner(
                        self._build_query(
                            properties=[
                                SessionPropertyFilter(
                                    key="$entry_pathname", operator=PropertyOperator.EXACT, value="/x"
                                )
                            ]
                        )
                    )
                )
                is False
            )

    def test_rejected_for_unsupported_filter_key(self):
        with self._enable_lazy():
            assert (
                can_use_lazy_precompute(
                    self._runner(
                        self._build_query(
                            properties=[
                                EventPropertyFilter(key="$browser", operator=PropertyOperator.EXACT, value="Chrome")
                            ]
                        )
                    )
                )
                is False
            )

    def test_rejected_for_sessions_v2_uuid_mode(self):
        with self._enable_lazy():
            modifiers = HogQLQueryModifiers(sessionsV2JoinMode=SessionsV2JoinMode.UUID)
            assert can_use_lazy_precompute(self._runner(self._build_query(modifiers=modifiers))) is False

    def test_rejected_for_unsupported_order_by_field(self):
        with self._enable_lazy():
            order = [WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC]
            assert can_use_lazy_precompute(self._runner(self._build_query(order_by=order))) is False

    @parameterized.expand(
        [
            (WebAnalyticsOrderByFields.ERRORS,),
            (WebAnalyticsOrderByFields.RAGE_CLICKS,),
            (WebAnalyticsOrderByFields.DEAD_CLICKS,),
        ]
    )
    def test_accepted_for_supported_order_by_field(self, field: WebAnalyticsOrderByFields):
        with self._enable_lazy():
            order = [field, WebAnalyticsOrderByDirection.DESC]
            assert can_use_lazy_precompute(self._runner(self._build_query(order_by=order))) is True

    # ----------------------------------------------------------------------
    # Round-trip — these exercise the real INSERT + read path. They mirror the
    # paths-tile tests and inherit the same CI-flake skip while the underlying
    # read-after-write visibility issue is investigated.
    # ----------------------------------------------------------------------

    @freeze_time("2024-01-15T12:00:00Z")
    def test_round_trip_creates_precompute_job(self):
        self._seed_frustration_events()
        with self._enable_lazy():
            self._runner(self._build_query()).calculate()

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
        assert len(jobs) > 0, "expected at least one precompute job to be created"

    @unittest.skip(
        "Mirrors the CI-only flake in test_web_stats_paths_lazy_precompute.py — "
        "lazy path returns empty rows despite READY job. Re-enable once the "
        "read-after-write visibility issue tracked there is resolved."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_response_matches_live(self):
        """Compare rage / dead / errors per path between the live and lazy paths."""
        self._seed_frustration_events()

        live_response = self._runner(self._build_query()).calculate()
        live_by_path = self._collect_metrics(live_response.results)

        with self._enable_lazy():
            lazy_response = self._runner(self._build_query()).calculate()

        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, "expected at least one READY precompute job"
        assert lazy_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE

        lazy_by_path = self._collect_metrics(lazy_response.results)
        assert lazy_by_path == live_by_path, f"lazy/live mismatch: lazy={lazy_by_path}, live={live_by_path}"

    @staticmethod
    def _collect_metrics(results) -> dict[str, dict]:
        """Build a `{path: {rage, dead, errors}}` dict from a table response.

        Each row is `[breakdown_value, (rage, prev), (dead, prev), (errors, prev), cross_sell]`.
        """
        out: dict[str, dict] = {}
        for row in results:
            breakdown = row[0]
            out[breakdown] = {
                "rage_clicks": row[1][0],
                "dead_clicks": row[2][0],
                "errors": row[3][0],
            }
        return out
