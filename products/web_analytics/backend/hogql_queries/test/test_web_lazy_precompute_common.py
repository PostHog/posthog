from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin
from unittest import mock

from django.test import override_settings

from parameterized import parameterized
from structlog.contextvars import get_contextvars

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    PropertyOperator,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql import ast

from posthog import redis
from posthog.clickhouse.query_tagging import Feature, get_query_tag_value, reset_query_tags, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    TtlSchedule,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    OOM_PIN_TTL_SECONDS,
    REVALIDATION_TRIGGER,
    SESSION_SETTLING_SECONDS,
    STALE_WHILE_REVALIDATE_SECONDS,
    PerQueryOptedOut,
    PerQueryOptInNotSet,
    TooManyFilters,
    UnsupportedFilterKey,
    _oom_pin_key,
    check_common_eligibility,
    compute_filters_eligibility_hash,
    handle_stale_served,
    host_filter_expr,
    is_precompute_enabled_for_team,
    is_precompute_unrestricted_for_team,
    is_team_oom_pinned,
    pin_team_oom,
    web_ensure_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

_COMMON = "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common"


def _date_range() -> tuple[datetime, datetime]:
    return (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 8, tzinfo=UTC))


class TestIsPrecomputeEnabledForTeam(BaseTest):
    @mock.patch(f"{_COMMON}.is_org_feature_flag_enabled", return_value=False)
    def test_team_in_setting_bypasses_org_flag(self, flag) -> None:
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[self.team.pk]):
            assert is_precompute_enabled_for_team(self.team) is True
        flag.assert_not_called()  # short-circuits before the flag is ever evaluated

    @override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[])
    @mock.patch(f"{_COMMON}.is_org_feature_flag_enabled", return_value=True)
    def test_team_not_in_setting_falls_back_to_enabled_flag(self, _flag) -> None:
        assert is_precompute_enabled_for_team(self.team) is True

    @override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[])
    @mock.patch(f"{_COMMON}.is_org_feature_flag_enabled", return_value=False)
    def test_team_not_in_setting_with_flag_off_is_ineligible(self, _flag) -> None:
        assert is_precompute_enabled_for_team(self.team) is False

    @override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[])
    @mock.patch(f"{_COMMON}.is_org_feature_flag_enabled", return_value=False)
    def test_unrestricted_team_is_enrolled_without_being_in_enrollment_list(self, flag) -> None:
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            assert is_precompute_enabled_for_team(self.team) is True
        flag.assert_not_called()

    @override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[])
    def test_team_not_in_unrestricted_list_is_restricted(self) -> None:
        assert is_precompute_unrestricted_for_team(self.team) is False

    def test_team_in_unrestricted_list_is_unrestricted(self) -> None:
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            assert is_precompute_unrestricted_for_team(self.team) is True


class TestCheckCommonEligibilityUnrestricted(BaseTest):
    def _check(self, *, use_precompute, properties=None) -> None:
        check_common_eligibility(
            team=self.team,
            use_web_analytics_precompute=use_precompute,
            conversion_goal=None,
            sampling=None,
            modifiers=None,
            properties=properties or [],
            resolve_date_range=_date_range,
        )

    def test_restricted_team_rejects_untouched_opt_in(self) -> None:
        with override_settings(
            WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[self.team.pk],
            WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[],
        ):
            with self.assertRaises(PerQueryOptInNotSet):
                self._check(use_precompute=None)

    def test_unrestricted_team_accepts_untouched_as_opt_out_default(self) -> None:
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            self._check(use_precompute=None)
            self._check(use_precompute=True)

    def test_unrestricted_team_rejects_explicit_opt_out(self) -> None:
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            with self.assertRaises(PerQueryOptedOut):
                self._check(use_precompute=False)

    def test_unrestricted_team_accepts_arbitrary_multi_filter(self) -> None:
        props = [
            EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT),
            EventPropertyFilter(key="$os", value="Mac OS X", operator=PropertyOperator.IS_NOT),
        ]
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            self._check(use_precompute=None, properties=props)

    def test_restricted_team_rejects_multi_filter(self) -> None:
        props = [
            EventPropertyFilter(key="$host", value="a.com", operator=PropertyOperator.EXACT),
            EventPropertyFilter(key="$host", value="b.com", operator=PropertyOperator.EXACT),
        ]
        with override_settings(
            WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[self.team.pk],
            WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[],
        ):
            with self.assertRaises(TooManyFilters):
                self._check(use_precompute=True, properties=props)

    def test_restricted_team_rejects_non_host_filter(self) -> None:
        props = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)]
        with override_settings(
            WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS=[self.team.pk],
            WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[],
        ):
            with self.assertRaises(UnsupportedFilterKey):
                self._check(use_precompute=True, properties=props)


class TestHostFilterExpr(BaseTest):
    def test_empty_properties_is_true_constant(self) -> None:
        expr = host_filter_expr([], team=self.team)
        assert isinstance(expr, ast.Constant)
        assert expr.value is True

    def test_restricted_team_builds_single_host_equals(self) -> None:
        props = [EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)]
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[]):
            expr = host_filter_expr(props, team=self.team)
        assert isinstance(expr, ast.Call)
        assert expr.name == "equals"

    def test_unrestricted_team_translates_arbitrary_filters(self) -> None:
        props = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)]
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            expr = host_filter_expr(props, team=self.team)
        # property_to_expr produces a comparison/AST node; it must not be the trivial True constant.
        assert not (isinstance(expr, ast.Constant) and expr.value is True)


def _overview(
    *,
    date_from: str = "-7d",
    date_to: str | None = None,
    properties: list | None = None,
    compare: bool = False,
) -> WebOverviewQuery:
    return WebOverviewQuery(
        dateRange=DateRange(date_from=date_from, date_to=date_to),
        properties=properties or [],
        compareFilter=CompareFilter(compare=compare) if compare else None,
    )


def _stats(
    *,
    date_from: str = "-7d",
    breakdown_by: WebStatsBreakdown = WebStatsBreakdown.BROWSER,
    properties: list | None = None,
) -> WebStatsTableQuery:
    return WebStatsTableQuery(
        dateRange=DateRange(date_from=date_from),
        breakdownBy=breakdown_by,
        properties=properties or [],
    )


class TestComputeFiltersEligibilityHash(BaseTest):
    def test_stable_across_calls_with_identical_query(self) -> None:
        q = _overview()
        assert compute_filters_eligibility_hash(q, "UTC") == compute_filters_eligibility_hash(q, "UTC")

    def test_stable_across_freshly_built_equal_queries(self) -> None:
        assert compute_filters_eligibility_hash(_overview(), "UTC") == compute_filters_eligibility_hash(
            _overview(), "UTC"
        )

    def test_date_range_fragments_key(self) -> None:
        a = compute_filters_eligibility_hash(_overview(date_from="-7d"), "UTC")
        b = compute_filters_eligibility_hash(_overview(date_from="-30d"), "UTC")
        assert a != b

    def test_breakdown_fragments_key(self) -> None:
        a = compute_filters_eligibility_hash(_stats(breakdown_by=WebStatsBreakdown.BROWSER), "UTC")
        b = compute_filters_eligibility_hash(_stats(breakdown_by=WebStatsBreakdown.OS), "UTC")
        assert a != b

    def test_filter_value_fragments_key(self) -> None:
        chrome = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)]
        firefox = [EventPropertyFilter(key="$browser", value="Firefox", operator=PropertyOperator.EXACT)]
        assert compute_filters_eligibility_hash(
            _overview(properties=chrome), "UTC"
        ) != compute_filters_eligibility_hash(_overview(properties=firefox), "UTC")

    def test_filter_operator_fragments_key(self) -> None:
        exact = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)]
        is_not = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.IS_NOT)]
        assert compute_filters_eligibility_hash(_overview(properties=exact), "UTC") != compute_filters_eligibility_hash(
            _overview(properties=is_not), "UTC"
        )

    def test_query_kind_fragments_key(self) -> None:
        assert compute_filters_eligibility_hash(_overview(), "UTC") != compute_filters_eligibility_hash(_stats(), "UTC")

    def test_timezone_fragments_key(self) -> None:
        q = _overview()
        assert compute_filters_eligibility_hash(q, "UTC") != compute_filters_eligibility_hash(q, "America/New_York")

    def test_compare_filter_fragments_key(self) -> None:
        assert compute_filters_eligibility_hash(_overview(compare=False), "UTC") != compute_filters_eligibility_hash(
            _overview(compare=True), "UTC"
        )

    def test_property_order_currently_fragments_key_documented_not_desired(self) -> None:
        a = [
            EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT),
            EventPropertyFilter(key="$os", value="Mac OS X", operator=PropertyOperator.EXACT),
        ]
        b = list(reversed(a))
        # NOTE: we don't currently canonicalize order. If two clients send the
        # same filter set in different orders they will hash to different keys.
        # Document the current behavior rather than the desired one — change
        # this assertion if we add canonical ordering upstream.
        assert compute_filters_eligibility_hash(_overview(properties=a), "UTC") != compute_filters_eligibility_hash(
            _overview(properties=b), "UTC"
        )

    def test_use_web_analytics_precompute_toggle_does_not_fragment_key(self) -> None:
        q_on = WebOverviewQuery(
            dateRange=DateRange(date_from="-7d"),
            properties=[],
            useWebAnalyticsPrecompute=True,
        )
        q_off = WebOverviewQuery(
            dateRange=DateRange(date_from="-7d"),
            properties=[],
            useWebAnalyticsPrecompute=False,
        )
        assert compute_filters_eligibility_hash(q_on, "UTC") == compute_filters_eligibility_hash(q_off, "UTC")

    def test_hash_is_64_char_hex(self) -> None:
        h = compute_filters_eligibility_hash(_overview(), "UTC")
        assert len(h) == 64
        int(h, 16)


class TestFiltersEligibilityHashContextvarBinding(ClickhouseTestMixin, APIBaseTest):
    """Verifies that `WebAnalyticsQueryRunner.calculate()` binds `filters_eligibility_hash`
    on `structlog.contextvars` so every log emitted inside the request —
    including from code called via `super().calculate()` and downstream paths
    like the lazy framework's `lazy_computation.executed` — picks it up via
    the project-wide `merge_contextvars` processor.

    The tests inspect `structlog.contextvars.get_contextvars()` directly rather
    than going through `structlog.testing.capture_logs()` because the latter
    replaces the configured processor chain and therefore doesn't run
    `merge_contextvars` — capture_logs would falsely report the field missing
    even when production code is correct."""

    def _runner(self) -> WebOverviewQueryRunner:
        return WebOverviewQueryRunner(
            team=self.team,
            query=WebOverviewQuery(
                dateRange=DateRange(date_from="-7d"),
                properties=[],
            ),
        )

    def test_filters_eligibility_hash_bound_during_super_calculate(self) -> None:
        """While `super().calculate()` is running, `get_contextvars()` should
        return `filters_eligibility_hash` — this is the property the `merge_contextvars`
        processor relies on to attach the field to every log inside the call
        tree (`lazy_computation.executed`, eligibility-rejected lines, etc.).

        Patches `AnalyticsQueryRunner.calculate` (the parent reached by
        `super().calculate()`), NOT a runner-level class — patching at the
        binding class would replace the very method that wraps the
        contextvar block."""
        runner = self._runner()
        expected = runner.filters_eligibility_hash
        assert expected is not None

        captured: dict = {}
        original = AnalyticsQueryRunner.calculate

        def spy(self_):
            captured.update(get_contextvars())
            return original(self_)

        with mock.patch.object(AnalyticsQueryRunner, "calculate", spy):
            runner.calculate()

        assert captured.get("filters_eligibility_hash") == expected

    def test_filters_eligibility_hash_unbound_after_calculate_returns(self) -> None:
        """The contextvar must not leak past `calculate()` — `get_contextvars()`
        outside the request should NOT include the prior request's hash."""
        runner = self._runner()
        runner.calculate()
        assert "filters_eligibility_hash" not in get_contextvars()

    def test_filters_eligibility_hash_unbound_after_calculate_raises(self) -> None:
        """Same cleanup invariant when `calculate()` raises — the contextvar
        must still be unbound (otherwise an exception in one request would
        leak its filters_eligibility_hash into the next request on the same worker)."""
        runner = self._runner()

        with mock.patch.object(AnalyticsQueryRunner, "calculate", side_effect=RuntimeError("boom")):
            try:
                runner.calculate()
            except RuntimeError:
                pass

        assert "filters_eligibility_hash" not in get_contextvars()

    def test_filters_eligibility_hash_not_in_query_tags(self) -> None:
        """The hash is deliberately kept out of `tag_queries` — `system.query_log`
        has sub-day retention on prod, so a hash for multi-day analysis only
        makes sense on a long-retention source (Loki). This test pins the
        decision: if someone reintroduces it to the tags, they must intend it
        and update this assertion."""
        runner = self._runner()
        original = AnalyticsQueryRunner.calculate

        captured: dict = {}

        def spy(self_):
            captured["query_tag"] = get_query_tag_value("filters_eligibility_hash")
            return original(self_)

        with mock.patch.object(AnalyticsQueryRunner, "calculate", spy):
            runner.calculate()

        assert captured["query_tag"] is None


class TestTeamOomPin(BaseTest):
    def tearDown(self):
        redis.get_client().delete(_oom_pin_key(self.team.pk))
        super().tearDown()

    def test_unpinned_team(self):
        assert is_team_oom_pinned(self.team.pk) is False

    def test_pin_then_read_with_ttl(self):
        pin_team_oom(self.team.pk)
        assert is_team_oom_pinned(self.team.pk) is True
        ttl = redis.get_client().ttl(_oom_pin_key(self.team.pk))
        assert 0 < ttl <= OOM_PIN_TTL_SECONDS

    @mock.patch(f"{_COMMON}.redis.get_client", side_effect=Exception("redis down"))
    def test_redis_failure_reads_as_unpinned(self, _client):
        assert is_team_oom_pinned(self.team.pk) is False


class TestWebEnsurePrecomputed(BaseTest):
    def tearDown(self):
        redis.get_client().delete(_oom_pin_key(self.team.pk))
        super().tearDown()

    @mock.patch(f"{_COMMON}.ensure_precomputed")
    def test_pins_team_on_oom_and_runs_uncapped_first(self, mock_ensure):
        mock_ensure.return_value = LazyComputationResult(ready=False, job_ids=[], memory_exceeded=True)
        web_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        # ran width-uncapped this time (not yet pinned), then pinned for next time; the
        # schedule is normalized to a TtlSchedule carrying the session-pad finality lag
        passed = mock_ensure.call_args.kwargs["ttl_seconds"]
        assert isinstance(passed, TtlSchedule)
        assert passed.default_ttl_seconds == 3600
        assert passed.max_window_days is None
        assert passed.settling_period_seconds == SESSION_SETTLING_SECONDS
        assert is_team_oom_pinned(self.team.pk) is True

    @mock.patch(f"{_COMMON}.ensure_precomputed")
    def test_pinned_team_gets_width_capped_schedule(self, mock_ensure):
        pin_team_oom(self.team.pk)
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[], memory_exceeded=False)
        web_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        passed = mock_ensure.call_args.kwargs["ttl_seconds"]
        assert isinstance(passed, TtlSchedule)
        assert passed.max_window_days == 1

    @mock.patch(f"{_COMMON}.ensure_precomputed")
    def test_already_pinned_oom_refreshes_ttl(self, mock_ensure):
        pin_team_oom(self.team.pk)
        # expire-soon, then a re-OOM should refresh the TTL back to full
        redis.get_client().expire(_oom_pin_key(self.team.pk), 5)
        mock_ensure.return_value = LazyComputationResult(ready=False, job_ids=[], memory_exceeded=True)
        web_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        ttl = redis.get_client().ttl(_oom_pin_key(self.team.pk))
        assert ttl > 5

    @mock.patch(f"{_COMMON}.ensure_precomputed")
    def test_no_pin_on_success(self, mock_ensure):
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[], memory_exceeded=False)
        web_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        assert is_team_oom_pinned(self.team.pk) is False

    @mock.patch(f"{_COMMON}.ensure_precomputed")
    def test_pinned_team_restamps_prebuilt_schedule(self, mock_ensure):
        # A caller may pass an already-built TtlSchedule (ensure_precomputed accepts one);
        # the pin must stamp the cap onto it, not crash by re-parsing it.
        pin_team_oom(self.team.pk)
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[], memory_exceeded=False)
        prebuilt = TtlSchedule(rules=[], default_ttl_seconds=3600, max_window_days=None)
        web_ensure_precomputed(team=self.team, ttl_seconds=prebuilt, table=None)
        passed = mock_ensure.call_args.kwargs["ttl_seconds"]
        assert isinstance(passed, TtlSchedule)
        assert passed.max_window_days == 1
        assert passed.default_ttl_seconds == 3600

    @parameterized.expand(
        [
            ("user_request", None),
            ("eager_warmer", {"trigger": "webAnalyticsEagerBaselineWarming"}),
            ("replay_warmer", {"trigger": "webAnalyticsQueryWarming"}),
            # The revalidation task itself must never get the grace — a re-run that can
            # be served stale would never refresh anything and freeze the cache.
            ("stale_revalidation", {"trigger": REVALIDATION_TRIGGER}),
            # The generic insight cache warmer isn't in the named trigger set — the
            # CACHE_WARMUP feature gate must classify it as background, or it would
            # persist stale rows into the insight cache under a fresh timestamp.
            ("insight_warmer", {"trigger": "warmingV2", "feature": Feature.CACHE_WARMUP}),
            ("unknown_future_warmer", {"feature": Feature.CACHE_WARMUP}),
        ]
    )
    @mock.patch(f"{_COMMON}.ensure_precomputed")
    def test_stale_while_revalidate_grace_by_trigger(self, _name, tags, mock_ensure):
        mock_ensure.return_value = LazyComputationResult(ready=True, job_ids=[])
        reset_query_tags()
        if tags is not None:
            with tags_context(**tags):
                web_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        else:
            web_ensure_precomputed(team=self.team, ttl_seconds={"default": 3600}, table=None)
        grace = mock_ensure.call_args.kwargs["stale_while_revalidate_seconds"]
        if tags is None:
            assert grace == STALE_WHILE_REVALIDATE_SECONDS
        else:
            assert grace is None, f"background context {tags} must not be served stale"


class TestStaleRevalidationEnqueue(BaseTest):
    def setUp(self):
        super().setUp()
        self.query = WebOverviewQuery(dateRange=DateRange(date_from="-7d"), properties=[])

    def tearDown(self):
        reset_query_tags()
        super().tearDown()

    def _delay_patch(self):
        return mock.patch(
            "products.web_analytics.backend.tasks.lazy_precompute_revalidation"
            ".revalidate_web_analytics_precompute.delay"
        )

    def test_handle_stale_served_tags_read_and_enqueues_once_per_request(self):
        # Two stale ensures in one request (current + compare period) must tag the read
        # and mint exactly one revalidation task — one re-run covers both periods.
        runner = WebOverviewQueryRunner(team=self.team, query=self.query)
        reset_query_tags()
        with self._delay_patch() as delay:
            handle_stale_served(runner=runner, family="web_overview")
            handle_stale_served(runner=runner, family="web_overview")
        assert get_query_tag_value("precompute_stale") is True
        assert delay.call_count == 1
        payload = delay.call_args.kwargs
        assert payload["team_id"] == self.team.pk
        assert payload["query"]["kind"] == "WebOverviewQuery"

    def test_broker_failure_does_not_break_the_stale_read_path(self):
        # handle_stale_served runs inside the families' read try/except before the stale
        # rows are read — a broker outage raising out of it would discard the stale
        # result and fall back to the expensive live query, inverting SWR's purpose.
        runner = WebOverviewQueryRunner(team=self.team, query=self.query)
        reset_query_tags()
        with self._delay_patch() as delay:
            delay.side_effect = Exception("broker down")
            handle_stale_served(runner=runner, family="web_overview")
        assert get_query_tag_value("precompute_stale") is True
