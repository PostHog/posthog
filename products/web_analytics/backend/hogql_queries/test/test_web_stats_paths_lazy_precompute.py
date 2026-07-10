import uuid
import dataclasses

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

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries
from posthog.models.utils import uuid7

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner

# Aliased so pytest doesn't collect this `test_`-prefixed helper as a test case.
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    SESSION_FORWARD_PAD_MINUTES,
    host_filter_expr,
    test_account_filter_expr as _test_account_filter_expr,
)
from products.web_analytics.backend.hogql_queries.web_stats_paths_lazy_precompute import (
    INSERT_QUERY_TEMPLATE_CAPPED,
    _breakdown_value_expr,
    _entry_breakdown_value_expr,
    _events_session_id_expr,
    _top_k_ranking_expr,
)


@override_settings(IN_UNIT_TESTING=True)
class TestWebStatsPathsLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

    def _enable_lazy(self):
        return patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=True,
        )

    def _seed_two_sessions(self) -> None:
        # p1 enters on /a, visits /b → bounce=False (multi-pageview session).
        # p2 enters on /a and stays there → bounce=True (single-pageview session).
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
                "$pathname": "/a",
                "$current_url": "https://example.com/a",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:05:00Z",
            properties={
                "$session_id": s1,
                "$host": "example.com",
                "$pathname": "/b",
                "$current_url": "https://example.com/b",
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
                "$pathname": "/a",
                "$current_url": "https://example.com/a",
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
        breakdown_by: WebStatsBreakdown = WebStatsBreakdown.PAGE,
        include_bounce_rate: bool = True,
        include_avg_time_on_page: bool = False,
        include_scroll_depth: bool = False,
        include_host: bool = False,
        do_path_cleaning: bool = False,
        sampling: WebAnalyticsSampling | None = None,
        conversion_goal=None,
        order_by: list | None = None,
    ) -> WebStatsTableQuery:
        return WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
            breakdownBy=breakdown_by,
            includeBounceRate=include_bounce_rate,
            includeAvgTimeOnPage=include_avg_time_on_page,
            includeScrollDepth=include_scroll_depth,
            includeHost=include_host,
            doPathCleaning=do_path_cleaning,
            useWebAnalyticsPrecompute=opt_in_precompute,
            sampling=sampling,
            conversionGoal=conversion_goal,
            orderBy=order_by,
        )

    def _run(self, query: WebStatsTableQuery):
        return WebStatsTableQueryRunner(team=self.team, query=query).calculate()

    @parameterized.expand([("stale_tagged", True, True), ("fresh", False, None)])
    def test_lazy_response_stamps_precompute_stale(self, _name, tag_set, expected):
        runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query())
        reset_query_tags()
        try:
            if tag_set:
                tag_queries(precompute_stale=True)
            response = runner._build_response_from_lazy_rows([], limit=10, offset=0)
        finally:
            reset_query_tags()
        assert response.preComputeStale is expected

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unfiltered_round_trip_creates_precompute_job(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())

        jobs = list(PreaggregationJob.objects.filter(team_id=self.team.pk))
        assert len(jobs) > 0, "expected at least one precompute job to be created"

    @unittest.skip(
        "CI-only flake since #59075 (passes 10/10 locally on the CI ClickHouse image) — "
        "lazy path returns empty rows despite READY job. "
        "Same root cause as test_web_overview_lazy_precompute.py::test_lazy_result_matches_raw_result. "
        "Suspected read-after-write visibility on Distributed table, but global "
        "insert_distributed_sync=1 is already set in users-dev.xml. Root cause under investigation."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_result(self):
        """Compare visitors / views / bounce_rate per path between the raw and lazy paths."""
        self._seed_two_sessions()

        raw_response = self._run(self._build_query())
        raw_by_path = self._collect_metrics(raw_response.results)

        with self._enable_lazy():
            lazy_response = self._run(self._build_query())

        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, "expected at least one READY precompute job"
        assert lazy_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE

        lazy_by_path = self._collect_metrics(lazy_response.results)

        assert lazy_by_path == raw_by_path, f"lazy/raw mismatch: lazy={lazy_by_path}, raw={raw_by_path}"

    @staticmethod
    def _collect_metrics(results) -> dict[str, dict]:
        """Build a {path: {visitors, views, bounce_rate}} dict from a table response.

        Each row is ``[breakdown_value, (visitors, prev), (views, prev), (bounce, prev), ui_fill, cross_sell]``.
        """
        out: dict[str, dict] = {}
        for row in results:
            breakdown = row[0]
            out[breakdown] = {
                "visitors": row[1][0],
                "views": row[2][0],
                "bounce_rate": row[3][0],
            }
        return out

    @unittest.skip(
        "CI-only flake since #59075 (passes locally on the CI ClickHouse image) — "
        "lazy path returns empty rows despite READY job, so the bounce-rate metric "
        "assertion KeyErrors on /a. Same root cause as test_lazy_result_matches_raw_result. "
        "Re-enable when the read-after-write visibility issue is resolved."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_bounce_rate_attributed_to_entry_path_only(self):
        """Bounce rate for /a should reflect sessions that ENTERED on /a, not all sessions that touched it.

        Both p1's session and p2's session touch /a, but only p2 entered AND bounced on /a.
        p1 entered on /a but did NOT bounce. So bounce_rate(/a) = avg(0, 1) = 0.5.
        Path /b is touched only by p1 (entered on /a, not /b) — bounce_rate(/b) should be NaN/None
        (no sessions entered on /b in the window) and the path may be dropped by the HAVING.
        """
        self._seed_two_sessions()
        with self._enable_lazy():
            response = self._run(self._build_query())
        metrics = self._collect_metrics(response.results)

        assert "/a" in metrics, f"expected /a in results: {metrics}"
        # bounce rate is between 0 and 1 for the lazy result (a float, not a percentage).
        # /a's bounce: p1 entered on /a with multi-pageview session (bounce=0), p2 entered on /a
        # with single-pageview session (bounce=1). avg = 0.5.
        assert abs(metrics["/a"]["bounce_rate"] - 0.5) < 0.01, f"/a bounce should be 0.5, got {metrics['/a']}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_host_filter_gets_distinct_cache_entry(self):
        self._seed_two_sessions()
        host_filter = EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)
        with self._enable_lazy():
            self._run(self._build_query())
            unfiltered_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(properties=[host_filter]))
            filtered_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert unfiltered_jobs, "expected unfiltered run to create at least one job"
        assert filtered_jobs, "expected host-filtered run to create at least one job"
        assert unfiltered_jobs.isdisjoint(filtered_jobs), (
            f"unfiltered and host-filtered runs must produce distinct cache keys, "
            f"got overlap: {unfiltered_jobs & filtered_jobs}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_distinct_include_host_values_get_distinct_cache_entries(self):
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(include_host=False))
            no_host_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(include_host=True))
            with_host_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert no_host_hashes.isdisjoint(with_host_hashes), (
            f"includeHost on/off must produce distinct cache keys, got overlap: {no_host_hashes & with_host_hashes}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_session_property_filter_falls_through(self):
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[
                        SessionPropertyFilter(key="$channel_type", value="Direct", operator=PropertyOperator.EXACT),
                    ]
                )
            )
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_disqualifying_filter_falls_through(self):
        # $pathname filter is outside the MVP allowlist.
        with self._enable_lazy():
            self._run(
                self._build_query(
                    properties=[
                        EventPropertyFilter(key="$pathname", value="/a", operator=PropertyOperator.EXACT),
                    ]
                )
            )
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_sampling_falls_through(self):
        with self._enable_lazy():
            self._run(self._build_query(sampling=WebAnalyticsSampling(enabled=True)))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_query_optin_alone_falls_through_when_org_flag_disabled(self):
        # `query.useWebAnalyticsPrecompute=True` BUT the rollout flag is off — refuse.
        self._run(self._build_query(opt_in_precompute=True))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_org_flag_alone_falls_through_when_query_not_opted_in(self):
        with self._enable_lazy():
            self._run(self._build_query(opt_in_precompute=False))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_initial_page_breakdown_uses_lazy_path(self):
        # INITIAL_PAGE reuses the same precompute table: feeding
        # `_entry_breakdown_value_expr` into both placeholders collapses the
        # inner GROUP BY to per-session, so the outer aggregate is "sessions
        # that entered on this path" — matching v2's INITIAL_PAGE semantic.
        # The AST differs from PAGE, so the cache key (query_hash) differs and
        # the two breakdowns coexist as distinct jobs.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(breakdown_by=WebStatsBreakdown.INITIAL_PAGE))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_page_and_initial_page_get_distinct_cache_entries(self):
        # Defence-in-depth: a team toggling between Path / Entry path tabs must
        # produce different precompute jobs. If the AST collapses (e.g., a
        # future refactor uses the same placeholder by accident), both
        # breakdowns would share rows and the entry-path bounce numbers would
        # be wrong for the path tile (and vice versa).
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(breakdown_by=WebStatsBreakdown.PAGE))
            page_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(breakdown_by=WebStatsBreakdown.INITIAL_PAGE))
            initial_page_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert page_hashes and initial_page_hashes, "both breakdowns should create jobs"
        assert page_hashes.isdisjoint(initial_page_hashes), (
            f"PAGE and INITIAL_PAGE breakdowns must produce distinct cache keys, "
            f"got overlap: {page_hashes & initial_page_hashes}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_missing_include_bounce_rate_falls_through(self):
        with self._enable_lazy():
            self._run(self._build_query(include_bounce_rate=False))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_avg_time_on_page_falls_through(self):
        with self._enable_lazy():
            self._run(self._build_query(include_avg_time_on_page=True))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_scroll_depth_falls_through(self):
        with self._enable_lazy():
            self._run(self._build_query(include_scroll_depth=True))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    def _set_path_cleaning_rules(self) -> None:
        self.team.path_cleaning_filters = [
            {"alias": "/project/<id>", "regex": "\\/project\\/\\d+", "order": 0},
            {"alias": "/insights/<id>", "regex": "\\/insights\\/[0-9a-zA-Z]+", "order": 1},
        ]
        self.team.save()

    @freeze_time("2024-01-15T12:00:00Z")
    def test_path_cleaning_uses_lazy_path(self):
        # Path cleaning is baked into the precompute at INSERT time, so a
        # path-cleaning query is still lazy-eligible and creates a precompute job.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(do_path_cleaning=True))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0

    @parameterized.expand([("breakdown", _breakdown_value_expr), ("entry", _entry_breakdown_value_expr)])
    def test_path_cleaning_baked_into_insert_expr(self, _name: str, fn):
        # With team rules + doPathCleaning, the insert breakdown/entry exprs carry
        # the cleaning regex chain; without it (or without rules) they store raw.
        self._set_path_cleaning_rules()
        cleaned = fn(WebStatsTableQueryRunner(team=self.team, query=self._build_query(do_path_cleaning=True)))
        raw = fn(WebStatsTableQueryRunner(team=self.team, query=self._build_query(do_path_cleaning=False)))
        assert "replaceRegexpAll" in repr(cleaned), f"{fn.__name__} must bake cleaning into the insert"
        assert "replaceRegexpAll" not in repr(raw), f"{fn.__name__} must store raw paths when cleaning is off"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_path_cleaning_gets_distinct_cache_entry(self):
        # Cleaning is part of the insert AST now, so doPathCleaning on/off map to
        # distinct query_hashes / jobs (a rules change spawns a fresh job).
        self._seed_two_sessions()
        self._set_path_cleaning_rules()
        with self._enable_lazy():
            self._run(self._build_query(do_path_cleaning=False))
            raw_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(do_path_cleaning=True))
            cleaned_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert raw_hashes, "expected raw run to create at least one job"
        assert cleaned_hashes, "expected cleaned run to create at least one job"
        assert raw_hashes.isdisjoint(cleaned_hashes), (
            f"doPathCleaning on/off must produce distinct cache keys, got overlap: {raw_hashes & cleaned_hashes}"
        )

    @parameterized.expand(
        [
            # Descending sorts cap by the matching merge metric; default is visitors DESC.
            ("default_visitors", None, "uniqMerge"),
            ("views_desc", [WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.DESC], "sumMerge"),
            ("bounce_desc", [WebAnalyticsOrderByFields.BOUNCE_RATE, WebAnalyticsOrderByDirection.DESC], "avgMerge"),
            # Ascending sorts are not capped (the "top" is a tied long tail) → store full set.
            ("visitors_asc", [WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.ASC], None),
        ]
    )
    def test_top_k_ranking_expr_matches_sort(self, _name: str, order_by, expected_metric):
        runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query(order_by=order_by))
        expr = _top_k_ranking_expr(runner)
        if expected_metric is None:
            assert expr is None
        else:
            assert expected_metric in repr(expr)

    @freeze_time("2024-01-15T12:00:00Z")
    def test_sort_key_gets_distinct_cache_entry(self):
        # The cap metric is in the insert AST, so different sort keys map to distinct
        # capped jobs. This also exercises that the capped insert template parses/builds.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(
                self._build_query(order_by=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC])
            )
            visitors_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(order_by=[WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.DESC]))
            views_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert visitors_hashes, "expected visitors-sorted run to create at least one job"
        assert views_hashes, "expected views-sorted run to create at least one job"
        assert visitors_hashes.isdisjoint(views_hashes), (
            f"different sort keys must produce distinct capped jobs, got overlap: {visitors_hashes & views_hashes}"
        )

    def test_capped_insert_top_level_columns_are_aliased(self):
        # Regression: the framework's `_build_manual_insert_sql` builds the INSERT
        # column list from top-level aliases — bare columns raise, silently failing
        # the capped insert so the tile falls back to raw. Parse the capped template
        # (the path every descending sort takes) and assert all columns are aliased.
        runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query())
        placeholders: dict = {
            "events_session_id": _events_session_id_expr(runner),
            "breakdown_value_expr": _breakdown_value_expr(runner),
            "entry_breakdown_value_expr": _entry_breakdown_value_expr(runner),
            "event_type_filter": runner.event_type_expr,
            "user_filter": host_filter_expr(runner.query.properties or [], team=runner.team),
            "test_account_filter": _test_account_filter_expr(
                test_account_filters=runner._test_account_filters, team=runner.team
            ),
            "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
            "top_k_metric": _top_k_ranking_expr(runner),
            "time_window_min": ast.Constant(value="__MIN__"),
            "time_window_max": ast.Constant(value="__MAX__"),
        }
        parsed = parse_select(INSERT_QUERY_TEMPLATE_CAPPED, placeholders=placeholders)
        assert isinstance(parsed, ast.SelectQuery)
        assert parsed.select and all(isinstance(e, ast.Alias) for e in parsed.select), (
            "capped insert top-level columns must all be aliased for _build_manual_insert_sql"
        )

    def test_capped_insert_caps_per_day_not_per_window(self):
        # The cap must be computed PER DAY, not over the whole job window. The read path
        # decomposes a request into daily windows and can serve one of them from a wider
        # covering job (`filter_overlapping_jobs`), so a path in a single day's top-K must
        # be stored even if it falls outside the job window's overall top-K — a per-window
        # cap silently drops it. Guards against a revert to per-window capping.
        runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query())
        placeholders: dict = {
            "events_session_id": _events_session_id_expr(runner),
            "breakdown_value_expr": _breakdown_value_expr(runner),
            "entry_breakdown_value_expr": _entry_breakdown_value_expr(runner),
            "event_type_filter": runner.event_type_expr,
            "user_filter": host_filter_expr(runner.query.properties or [], team=runner.team),
            "test_account_filter": _test_account_filter_expr(
                test_account_filters=runner._test_account_filters, team=runner.team
            ),
            "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
            "top_k_metric": _top_k_ranking_expr(runner),
            "time_window_min": ast.Constant(value="__MIN__"),
            "time_window_max": ast.Constant(value="__MAX__"),
        }
        parsed = parse_select(INSERT_QUERY_TEMPLATE_CAPPED, placeholders=placeholders)

        rank_windows: list[ast.WindowExpr] = []

        def walk(node: object) -> None:
            if isinstance(node, ast.WindowFunction) and node.name == "dense_rank" and node.over_expr:
                rank_windows.append(node.over_expr)
            if dataclasses.is_dataclass(node) and not isinstance(node, type):
                for field in dataclasses.fields(node):
                    walk(getattr(node, field.name, None))
            elif isinstance(node, list | tuple):
                for item in node:
                    walk(item)

        walk(parsed)
        assert rank_windows, "capped insert must rank breakdowns with a windowed dense_rank()"
        assert all(w.partition_by and "day_bucket" in str(w.partition_by) for w in rank_windows), (
            f"the top-K rank must partition by the day bucket, got: {[w.partition_by for w in rank_windows]}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_uuid_session_mode_falls_through(self):
        query = self._build_query()
        query.modifiers = HogQLQueryModifiers(sessionsV2JoinMode=SessionsV2JoinMode.UUID)
        with self._enable_lazy():
            self._run(query)
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_window_over_max_days_falls_through(self):
        with self._enable_lazy():
            self._run(self._build_query(date_from="2023-01-01", date_to="2024-01-07"))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @parameterized.expand(
        [
            ("none_value", None),
            ("list_value", ["example.com", "other.com"]),
            ("empty_string", ""),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_non_string_host_value_falls_through(self, _name: str, host_value) -> None:
        prop = EventPropertyFilter(key="$host", value=host_value, operator=PropertyOperator.EXACT)
        with self._enable_lazy():
            self._run(self._build_query(properties=[prop]))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @parameterized.expand(
        [
            ("utc", "UTC"),
            ("pacific", "America/Los_Angeles"),
            ("tokyo", "Asia/Tokyo"),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_result_matches_raw_for_whole_hour_timezones(self, _name: str, team_tz: str) -> None:
        # Same flakiness as test_lazy_result_matches_raw_result — lazy returns
        # empty rows despite READY job on CI. Skipped until the read-after-write
        # visibility issue tracked alongside #59075 is resolved.
        self.skipTest(
            "CI-only flake since #59075 (passes locally on the CI ClickHouse image) — "
            "lazy path returns empty rows despite READY job."
        )
        # mypy reads `skipTest` as `NoReturn`, but the test body must remain so
        # the test runs once the underlying flake is fixed.
        self.team.timezone = team_tz  # type: ignore[unreachable]
        self.team.save()
        self._seed_two_sessions()

        raw_response = self._run(self._build_query())
        raw_by_path = self._collect_metrics(raw_response.results)

        with self._enable_lazy():
            lazy_response = self._run(self._build_query())

        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, f"expected READY precompute job for {team_tz}, got 0"
        lazy_by_path = self._collect_metrics(lazy_response.results)
        assert lazy_by_path == raw_by_path, f"lazy/raw mismatch for {team_tz}: raw={raw_by_path}, lazy={lazy_by_path}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_half_hour_offset_timezone_falls_through(self):
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query())
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_falls_back_when_current_period_not_ready(self):
        from products.web_analytics.backend.hogql_queries.web_stats_paths_lazy_precompute import (
            execute_lazy_precomputed_read,
        )

        with (
            self._enable_lazy(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_stats_paths_lazy_precompute.ensure_web_stats_paths_precomputed",
                return_value=LazyComputationResult(ready=False, job_ids=[uuid.uuid4()]),
            ),
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query())
            result = execute_lazy_precomputed_read(
                runner, sort_column="visitors", sort_direction="DESC", limit=11, offset=0
            )

        assert result is None, f"expected fall-back to raw when current precompute not ready, got {result!r}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_compare_period_falls_back_when_previous_not_ready(self):
        from products.web_analytics.backend.hogql_queries.web_stats_paths_lazy_precompute import (
            execute_lazy_precomputed_read,
        )

        first_call = {"done": False}

        def fake_ensure(runner, time_range_start, time_range_end):
            if not first_call["done"]:
                first_call["done"] = True
                return LazyComputationResult(ready=True, job_ids=[uuid.uuid4()])
            return LazyComputationResult(ready=False, job_ids=[uuid.uuid4()])

        with (
            self._enable_lazy(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_stats_paths_lazy_precompute.ensure_web_stats_paths_precomputed",
                side_effect=fake_ensure,
            ),
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query(compare=True))
            result = execute_lazy_precomputed_read(
                runner, sort_column="visitors", sort_direction="DESC", limit=11, offset=0
            )

        assert result is None, f"expected fall-back to raw when previous precompute not ready, got {result!r}"

    @parameterized.expand(
        [
            ("rage_clicks", WebAnalyticsOrderByFields.RAGE_CLICKS),
            ("avg_scroll", WebAnalyticsOrderByFields.AVERAGE_SCROLL_PERCENTAGE),
            ("conversion_rate", WebAnalyticsOrderByFields.CONVERSION_RATE),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_unsupported_orderby_falls_through(self, _name: str, field: WebAnalyticsOrderByFields) -> None:
        # Fields the lazy response can't sort on must not silently rewrite to
        # `visitors` — refuse and let the raw path serve the request.
        self._seed_two_sessions()
        with self._enable_lazy():
            self._run(self._build_query(order_by=[field, WebAnalyticsOrderByDirection.DESC]))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @parameterized.expand(
        [
            ("visitors_asc", WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.ASC),
            ("views_desc", WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.DESC),
            ("bounce_rate_asc", WebAnalyticsOrderByFields.BOUNCE_RATE, WebAnalyticsOrderByDirection.ASC),
        ]
    )
    @unittest.skip(
        "CI-only flake since #59075 (passes locally on the CI ClickHouse image) — "
        "lazy path returns None on `preComputeStrategy` despite jobs being created "
        "(`test_unfiltered_round_trip_creates_precompute_job` passes). Same root "
        "cause as `test_lazy_result_matches_raw_result`: suspected read-after-write "
        "visibility on the Distributed lazy read. `@unittest.skip` placed AFTER "
        "`@parameterized.expand` so the expanded variants inherit the skip — putting "
        "it above the expand decorator lets the variants slip through (see #59614)."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_supported_orderby_is_eligible(
        self,
        _name: str,
        field: WebAnalyticsOrderByFields,
        direction: WebAnalyticsOrderByDirection,
    ) -> None:
        self._seed_two_sessions()
        with self._enable_lazy():
            response = self._run(self._build_query(order_by=[field, direction]))
        assert response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE

    @unittest.skip(
        "CI-only flake since #59075 (passes locally on the CI ClickHouse image) — "
        "same lazy-read read-after-write issue as the parity tests."
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_compare_period_only_populated_returns_real_previous_bounce(self):
        """When current period has no events but previous does, the lazy path
        must produce real previous-period bounce rates (not NaN/None) and
        sort/serialize correctly."""
        # Previous period: a single bouncing session on /a.
        s = str(uuid7("2023-12-26"))
        _create_person(team_id=self.team.pk, distinct_ids=["pp"], properties={"name": "pp"})
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="pp",
            timestamp="2023-12-26T10:00:00Z",
            properties={"$session_id": s, "$host": "example.com", "$pathname": "/a"},
        )

        raw_response = self._run(self._build_query(compare=True))
        raw_by_path = self._collect_compare_metrics(raw_response.results)

        with self._enable_lazy():
            lazy_response = self._run(self._build_query(compare=True))

        lazy_by_path = self._collect_compare_metrics(lazy_response.results)

        # Previous-period bounce on /a should be a real number on both paths,
        # not NaN. The exact value is asserted via raw-vs-lazy parity.
        assert lazy_by_path == raw_by_path, f"compare-period parity mismatch: lazy={lazy_by_path}, raw={raw_by_path}"

    @staticmethod
    def _collect_compare_metrics(results) -> dict[str, dict]:
        """Build a {path: {visitors, prev_visitors, views, prev_views, bounce, prev_bounce}} dict."""
        out: dict[str, dict] = {}
        for row in results:
            breakdown = row[0]
            out[breakdown] = {
                "visitors": row[1][0],
                "prev_visitors": row[1][1],
                "views": row[2][0],
                "prev_views": row[2][1],
                "bounce_rate": row[3][0],
                "prev_bounce_rate": row[3][1],
            }
        return out

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unrestricted_team_creates_job_for_multi_non_host_filter(self):
        # Filters the restricted gate would reject (multiple, non-`$host`,
        # non-`exact`) precompute fine for an unrestricted team — no org flag
        # needed, since membership in the unrestricted list implies enrollment.
        self._seed_two_sessions()
        props = [
            EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT),
            EventPropertyFilter(key="$os", value="Mac OS X", operator=PropertyOperator.IS_NOT),
        ]
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            self._run(self._build_query(properties=props))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unrestricted_team_distinct_filters_get_distinct_cache_entries(self):
        self._seed_two_sessions()
        chrome = [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)]
        firefox = [EventPropertyFilter(key="$browser", value="Firefox", operator=PropertyOperator.EXACT)]
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            self._run(self._build_query(properties=chrome))
            chrome_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(properties=firefox))
            firefox_hashes = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert chrome_hashes and firefox_hashes, "both filtered runs should create jobs"
        assert chrome_hashes.isdisjoint(firefox_hashes), (
            f"distinct filter values must produce distinct cache keys, got overlap: {chrome_hashes & firefox_hashes}"
        )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unrestricted_team_untouched_toggle_creates_job(self):
        # Unrestricted teams default to opt-out: an untouched toggle (None) still
        # precomputes.
        self._seed_two_sessions()
        query = self._build_query()
        query.useWebAnalyticsPrecompute = None
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            self._run(query)
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unrestricted_team_explicit_opt_out_falls_through(self):
        self._seed_two_sessions()
        with override_settings(WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS=[self.team.pk]):
            self._run(self._build_query(opt_in_precompute=False))
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @parameterized.expand(
        [
            ("user_request", None),
            ("eager_warmer", "webAnalyticsEagerBaselineWarming"),
            ("replay_warmer", "webAnalyticsQueryWarming"),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_ensure_wait_budget_by_trigger(self, _name: str, trigger: str | None) -> None:
        from datetime import UTC, datetime

        from posthog.clickhouse.query_tagging import reset_query_tags, tags_context

        from products.web_analytics.backend.hogql_queries import web_stats_paths_lazy_precompute as mod

        runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query())
        reset_query_tags()
        with patch.object(
            mod, "web_ensure_precomputed", return_value=LazyComputationResult(ready=True, job_ids=[])
        ) as ensure_mock:
            if trigger is not None:
                with tags_context(trigger=trigger):
                    mod.ensure_web_stats_paths_precomputed(
                        runner, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 8, tzinfo=UTC)
                    )
            else:
                mod.ensure_web_stats_paths_precomputed(
                    runner, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 8, tzinfo=UTC)
                )

        budget = ensure_mock.call_args.kwargs["wait_timeout_seconds"]
        grace = ensure_mock.call_args.kwargs["serve_stale_grace_seconds"]
        if trigger is None:
            assert budget == mod.PATHS_USER_ENSURE_WAIT_SECONDS
            assert grace == mod.PATHS_USER_STALE_GRACE_SECONDS
        else:
            # Warmers keep the full budget AND must never serve stale to themselves —
            # they are the refresh mechanism the stale path relies on.
            assert budget is None, f"warmer trigger {trigger} must keep the framework default budget"
            assert grace is None, f"warmer trigger {trigger} must not serve stale"

    @parameterized.expand(
        [
            # First ensure burned 9.5s of the 10s budget: the compare ensure must be
            # skipped entirely (fallback to raw) instead of getting a fresh budget.
            ("budget_spent_skips_compare", 9.5, None),
            # First ensure took 2s: the compare ensure runs with the 8s remainder,
            # not a fresh PATHS_USER_ENSURE_WAIT_SECONDS.
            ("remainder_passed_to_compare", 2.0, 8.0),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_user_ensure_budget_is_shared_across_compare_periods(
        self, _name: str, first_ensure_seconds: float, expected_compare_budget: float | None
    ) -> None:

        from posthog.clickhouse.query_tagging import reset_query_tags

        from products.web_analytics.backend.hogql_queries import web_stats_paths_lazy_precompute as mod

        runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query(compare=True))
        reset_query_tags()

        # perf_counter sequence: overall_started, ensure_started, after first ensure;
        # everything after sticks to the last value so later timing reads are stable.
        ticks = [0.0, 0.0, first_ensure_seconds]

        def fake_perf_counter() -> float:
            return ticks.pop(0) if len(ticks) > 1 else ticks[0]

        with (
            patch.object(
                mod,
                "ensure_web_stats_paths_precomputed",
                return_value=LazyComputationResult(ready=True, job_ids=[uuid.uuid4()]),
            ) as ensure_mock,
            patch.object(mod, "execute_read_query", return_value=[]),
            patch.object(mod.time, "perf_counter", side_effect=fake_perf_counter),
        ):
            result = mod.execute_lazy_precomputed_read(
                runner, sort_column="visitors", sort_direction="DESC", limit=11, offset=0
            )

        if expected_compare_budget is None:
            assert result is None, "spent budget must skip the compare ensure and fall back to raw"
            assert ensure_mock.call_count == 1
        else:
            assert ensure_mock.call_count == 2
            assert ensure_mock.call_args_list[1].kwargs["wait_budget_seconds"] == expected_compare_budget

    @parameterized.expand([("no_compare", False), ("compare", True)])
    @freeze_time("2024-01-15T12:00:00Z")
    def test_read_scan_is_pruned_to_requested_windows(self, _name: str, compare: bool) -> None:
        from datetime import UTC, datetime

        from products.web_analytics.backend.hogql_queries import web_stats_paths_lazy_precompute as mod

        cur_start = datetime(2024, 1, 8, tzinfo=UTC)
        cur_end = datetime(2024, 1, 15, tzinfo=UTC)
        prev_start = datetime(2024, 1, 1, tzinfo=UTC) if compare else None
        prev_end = datetime(2024, 1, 8, tzinfo=UTC) if compare else None

        runner = WebStatsTableQueryRunner(team=self.team, query=self._build_query(compare=compare))
        captured: dict = {}

        def fake_execute(**kwargs):
            captured["query"] = kwargs["query"]
            return type("FakeResponse", (), {"results": []})()

        with patch.object(mod, "execute_hogql_query", side_effect=fake_execute):
            mod.execute_read_query(
                runner=runner,
                job_ids=[str(uuid.uuid4())],
                current_start_utc=cur_start,
                current_end_utc=cur_end,
                previous_start_utc=prev_start,
                previous_end_utc=prev_end,
                sort_column="visitors",
                sort_direction="DESC",
                limit=11,
                offset=0,
            )

        inner = captured["query"].select_from.table
        assert isinstance(inner, ast.SelectQuery)
        bounds: dict[str, object] = {}
        assert inner.where is not None
        for expr in inner.where.args if isinstance(inner.where, ast.Call) else [inner.where]:
            if (
                isinstance(expr, ast.CompareOperation)
                and isinstance(expr.left, ast.Field)
                and expr.left.chain == ["time_window_start"]
                and isinstance(expr.right, ast.Constant)
            ):
                key = "min" if expr.op == ast.CompareOperationOp.GtEq else "max"
                bounds[key] = expr.right.value

        # The scan lower bound must be the union of the requested windows — with a compare
        # period that is prev_start; without one it must stay cur_start (NOT the 1970
        # no-compare sentinel, which would defeat the pruning entirely).
        expected_min = prev_start if compare else cur_start
        assert bounds == {"min": expected_min, "max": cur_end}
