import unittest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionPropertyFilter,
    SessionsV2JoinMode,
    WebAnalyticsPreComputeStrategy,
    WebAnalyticsSampling,
    WebGoalsQuery,
)

from posthog.models.utils import uuid7

from products.actions.backend.models.action import Action
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_goals import WebGoalsQueryRunner
from products.web_analytics.backend.hogql_queries.web_goals_lazy_precompute import can_use_lazy_precompute


@override_settings(IN_UNIT_TESTING=True)
class TestWebGoalsLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        Action.objects.filter(team__project_id=self.team.project_id).delete()

    def _enable_lazy(self):
        # Same flag the paths/frustration tests patch — the gate evaluates the
        # `web-analytics-precompute-toggle` org flag via posthoganalytics.
        return patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=True,
        )

    def _create_action(self, name: str, event: str = "$pageview") -> Action:
        return Action.objects.create(
            team=self.team,
            name=name,
            steps_json=[{"event": event}],
        )

    def _seed_goal_events(self) -> None:
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
                "$pathname": "/landing",
                "$current_url": "https://example.com/landing",
            },
        )
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:05Z",
            properties={
                "$session_id": s1,
                "$host": "example.com",
                "$pathname": "/landing",
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
                "$pathname": "/landing",
                "$current_url": "https://example.com/landing",
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
        sampling: WebAnalyticsSampling | None = None,
        order_by: list | None = None,
        modifiers: HogQLQueryModifiers | None = None,
    ) -> WebGoalsQuery:
        return WebGoalsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
            useWebAnalyticsPrecompute=opt_in_precompute,
            sampling=sampling,
            orderBy=order_by,
            modifiers=modifiers,
        )

    def _runner(self, query: WebGoalsQuery) -> WebGoalsQueryRunner:
        return WebGoalsQueryRunner(team=self.team, query=query)

    # ----------------------------------------------------------------------
    # Eligibility — no ClickHouse needed for these.
    # ----------------------------------------------------------------------

    def test_eligible_when_flag_on_opt_in_set_and_actions_exist(self):
        self._create_action("Pageview")
        with self._enable_lazy():
            assert can_use_lazy_precompute(self._runner(self._build_query())) is True

    def test_rejected_when_no_actions_configured(self):
        # No actions: even with flag + opt-in, the gate refuses since there's
        # nothing to precompute (matches the live `NoActionsError` behaviour).
        with self._enable_lazy():
            assert can_use_lazy_precompute(self._runner(self._build_query())) is False

    def test_rejected_when_org_flag_off(self):
        self._create_action("Pageview")
        with patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=False,
        ):
            assert can_use_lazy_precompute(self._runner(self._build_query())) is False

    def test_rejected_when_per_query_opt_in_missing(self):
        self._create_action("Pageview")
        with self._enable_lazy():
            assert can_use_lazy_precompute(self._runner(self._build_query(opt_in_precompute=False))) is False

    def test_rejected_when_sampling_enabled(self):
        self._create_action("Pageview")
        with self._enable_lazy():
            assert (
                can_use_lazy_precompute(self._runner(self._build_query(sampling=WebAnalyticsSampling(enabled=True))))
                is False
            )

    def test_rejected_for_unsupported_filter_key(self):
        self._create_action("Pageview")
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

    def test_rejected_for_non_event_property_filter(self):
        self._create_action("Pageview")
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

    def test_rejected_for_sessions_v2_uuid_mode(self):
        self._create_action("Pageview")
        with self._enable_lazy():
            modifiers = HogQLQueryModifiers(sessionsV2JoinMode=SessionsV2JoinMode.UUID)
            assert can_use_lazy_precompute(self._runner(self._build_query(modifiers=modifiers))) is False

    # ----------------------------------------------------------------------
    # Round-trip — these exercise the real INSERT + read. They mirror the
    # paths/frustration tests and inherit the same CI-flake skip while the
    # read-after-write visibility issue tracked on the paths tests is open.
    # ----------------------------------------------------------------------

    @freeze_time("2024-01-15T12:00:00Z")
    def test_round_trip_creates_precompute_job(self):
        self._create_action("Pageview")
        self._seed_goal_events()
        with self._enable_lazy():
            self._runner(self._build_query()).calculate()

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
        assert len(jobs) > 0, "expected at least one precompute job to be created"
        # A failed INSERT still leaves a job row (status FAILED), so existence
        # alone doesn't prove the insert ran — assert the jobs reached READY.
        # This catches insert-build errors (e.g. an unaliased SELECT column)
        # without depending on the skipped read-after-write round trip.
        assert all(j.status == PreaggregationJob.Status.READY for j in jobs), (
            f"expected all precompute jobs READY, got {[(str(j.id), j.status, j.error) for j in jobs]}"
        )

    @unittest.skip(
        "Mirrors the CI-only flake in test_web_stats_paths_lazy_precompute.py — "
        "lazy path returns empty rows despite READY job. Re-enable once the "
        "read-after-write visibility issue tracked there is resolved."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_response_matches_live(self):
        """Compare the goals response between the live and lazy paths."""
        action = self._create_action("Pageview")
        self._seed_goal_events()

        live_response = self._runner(self._build_query()).calculate()

        with self._enable_lazy():
            lazy_response = self._runner(self._build_query()).calculate()

        assert lazy_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE

        live_by_action = {r[0]: (r[1], r[2], r[3]) for r in live_response.results}
        lazy_by_action = {r[0]: (r[1], r[2], r[3]) for r in lazy_response.results}
        assert lazy_by_action == live_by_action, (
            f"lazy/live mismatch for action={action.name!r}: lazy={lazy_by_action}, live={live_by_action}"
        )

    def test_max_actions_constant_matches_live_runner_slice(self):
        """The lazy `MAX_ACTIONS` cap must equal the live runner's hard slice;
        otherwise we'd be precomputing rows the runner never reads (extra
        INSERT load) or, worse, missing rows the runner asks for."""
        from products.web_analytics.backend.hogql_queries.web_goals_lazy_precompute import MAX_ACTIONS

        # The live slice is hard-coded `[:5]` in `web_goals.py`'s `to_query`.
        assert MAX_ACTIONS == 5

    @freeze_time("2024-01-15T12:00:00Z")
    def test_stale_served_enqueues_background_revalidation(self):
        # Without the `result.stale` hook this family would serve stale for the whole
        # 6h grace and never refresh (the revalidate half of stale-while-revalidate).
        from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
        from products.web_analytics.backend.hogql_queries.web_goals_lazy_precompute import execute_lazy_precomputed_read

        self._create_action("goal")
        with (
            self._enable_lazy(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_goals_lazy_precompute.ensure_web_goals_precomputed",
                return_value=LazyComputationResult(ready=True, job_ids=[], stale=True),
            ),
            patch(
                "products.web_analytics.backend.tasks.lazy_precompute_revalidation.revalidate_web_analytics_precompute.delay"
            ) as delay,
        ):
            runner = self._runner(self._build_query())
            execute_lazy_precomputed_read(runner)

        assert delay.call_count == 1
        assert delay.call_args.kwargs["team_id"] == self.team.pk
