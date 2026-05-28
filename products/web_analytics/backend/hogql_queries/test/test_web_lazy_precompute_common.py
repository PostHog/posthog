from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin
from unittest import mock

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

from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import compute_precompute_filters_hash
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner


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


class TestComputePrecomputeFiltersHash(BaseTest):
    def test_stable_across_calls_with_identical_query(self) -> None:
        q = _overview()
        assert compute_precompute_filters_hash(q, "UTC") == compute_precompute_filters_hash(q, "UTC")

    def test_stable_across_freshly_built_equal_queries(self) -> None:
        assert compute_precompute_filters_hash(_overview(), "UTC") == compute_precompute_filters_hash(
            _overview(), "UTC"
        )

    def test_date_range_fragments_key(self) -> None:
        a = compute_precompute_filters_hash(_overview(date_from="-7d"), "UTC")
        b = compute_precompute_filters_hash(_overview(date_from="-30d"), "UTC")
        assert a != b

    def test_breakdown_fragments_key(self) -> None:
        a = compute_precompute_filters_hash(_stats(breakdown_by=WebStatsBreakdown.BROWSER), "UTC")
        b = compute_precompute_filters_hash(_stats(breakdown_by=WebStatsBreakdown.OS), "UTC")
        assert a != b

    def test_filter_value_fragments_key(self) -> None:
        chrome = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)]
        firefox = [EventPropertyFilter(key="$browser", value="Firefox", operator=PropertyOperator.EXACT)]
        assert compute_precompute_filters_hash(_overview(properties=chrome), "UTC") != compute_precompute_filters_hash(
            _overview(properties=firefox), "UTC"
        )

    def test_filter_operator_fragments_key(self) -> None:
        exact = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)]
        is_not = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.IS_NOT)]
        assert compute_precompute_filters_hash(_overview(properties=exact), "UTC") != compute_precompute_filters_hash(
            _overview(properties=is_not), "UTC"
        )

    def test_query_kind_fragments_key(self) -> None:
        assert compute_precompute_filters_hash(_overview(), "UTC") != compute_precompute_filters_hash(_stats(), "UTC")

    def test_timezone_fragments_key(self) -> None:
        q = _overview()
        assert compute_precompute_filters_hash(q, "UTC") != compute_precompute_filters_hash(q, "America/New_York")

    def test_compare_filter_fragments_key(self) -> None:
        assert compute_precompute_filters_hash(_overview(compare=False), "UTC") != compute_precompute_filters_hash(
            _overview(compare=True), "UTC"
        )

    def test_property_order_does_not_fragment_key(self) -> None:
        a = [
            EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT),
            EventPropertyFilter(key="$os", value="Mac OS X", operator=PropertyOperator.EXACT),
        ]
        b = list(reversed(a))
        # NOTE: we don't currently canonicalize order. If two clients send the
        # same filter set in different orders they will hash to different keys.
        # Document the current behavior rather than the desired one — change
        # this assertion if we add canonical ordering upstream.
        assert compute_precompute_filters_hash(_overview(properties=a), "UTC") != compute_precompute_filters_hash(
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
        assert compute_precompute_filters_hash(q_on, "UTC") == compute_precompute_filters_hash(q_off, "UTC")

    def test_hash_is_64_char_hex(self) -> None:
        h = compute_precompute_filters_hash(_overview(), "UTC")
        assert len(h) == 64
        int(h, 16)


class TestPrecomputeFiltersHashContextvarBinding(ClickhouseTestMixin, APIBaseTest):
    """Verifies that `WebAnalyticsQueryRunner.calculate()` binds `precompute_filters_hash`
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

    def test_precompute_filters_hash_bound_during_super_calculate(self) -> None:
        """While `super().calculate()` is running, `get_contextvars()` should
        return `precompute_filters_hash` — this is the property the `merge_contextvars`
        processor relies on to attach the field to every log inside the call
        tree (`lazy_computation.executed`, eligibility-rejected lines, etc.).

        Patches `AnalyticsQueryRunner.calculate` (the parent reached by
        `super().calculate()`), NOT a runner-level class — patching at the
        binding class would replace the very method that wraps the
        contextvar block."""
        runner = self._runner()
        expected = runner.precompute_filters_hash
        assert expected is not None

        captured: dict = {}
        original = AnalyticsQueryRunner.calculate

        def spy(self_):
            captured.update(get_contextvars())
            return original(self_)

        with mock.patch.object(AnalyticsQueryRunner, "calculate", spy):
            runner.calculate()

        assert captured.get("precompute_filters_hash") == expected

    def test_precompute_filters_hash_unbound_after_calculate_returns(self) -> None:
        """The contextvar must not leak past `calculate()` — `get_contextvars()`
        outside the request should NOT include the prior request's hash."""
        runner = self._runner()
        runner.calculate()
        assert "precompute_filters_hash" not in get_contextvars()

    def test_precompute_filters_hash_unbound_after_calculate_raises(self) -> None:
        """Same cleanup invariant when `calculate()` raises — the contextvar
        must still be unbound (otherwise an exception in one request would
        leak its precompute_filters_hash into the next request on the same worker)."""
        runner = self._runner()

        with mock.patch.object(AnalyticsQueryRunner, "calculate", side_effect=RuntimeError("boom")):
            try:
                runner.calculate()
            except RuntimeError:
                pass

        assert "precompute_filters_hash" not in get_contextvars()

    def test_query_tags_and_contextvar_carry_same_precompute_filters_hash(self) -> None:
        """The same value must land in three places per request:
        `runner.precompute_filters_hash`, `structlog.contextvars`, and the ClickHouse
        query-log tags (`get_query_tag_value`). If they diverge a downstream
        join would silently produce wrong results."""
        runner = self._runner()
        expected = runner.precompute_filters_hash
        assert expected is not None

        captured_contextvar: dict = {}
        captured_query_tag: dict = {}
        original = AnalyticsQueryRunner.calculate

        def spy(self_):
            captured_contextvar["precompute_filters_hash"] = get_contextvars().get("precompute_filters_hash")
            captured_query_tag["precompute_filters_hash"] = get_query_tag_value("precompute_filters_hash")
            return original(self_)

        with mock.patch.object(AnalyticsQueryRunner, "calculate", spy):
            runner.calculate()

        assert captured_contextvar["precompute_filters_hash"] == expected
        assert captured_query_tag["precompute_filters_hash"] == expected
