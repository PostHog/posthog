import math
import datetime as dt
from typing import cast

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import MetricsQuery

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import SharingConfiguration, User
from posthog.shared_link_user import SharedLinkUser

from products.metrics.backend.facade.api import run_precomputed_promql_query
from products.metrics.backend.facade.contracts import MetricSeries
from products.metrics.backend.facade.enums import MetricQueryProvenanceMode, PrecomputedMetricKind
from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.models import MetricDailyQueryCount, MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import NOT_STARTED_BY_VIEWER
from products.metrics.backend.precompute.fill import fill_precomputed_metrics
from products.metrics.backend.precompute.promql_plan import (
    DELTA_HISTOGRAM_BUCKET,
    Matcher,
    _is_delta_histogram,
    histogram_quantile,
    parse_promql,
)
from products.metrics.backend.promql import run_promql_range
from products.metrics.backend.tests._fake_snuffle import FakeSnuffle, fake_snuffle
from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables

NOW = dt.datetime(2026, 11, 12, 12, 7, tzinfo=dt.UTC)
SEED_FROM = NOW - dt.timedelta(days=9)
LE = ("0.5", "1", "2.5", "+Inf")
EXACT = 1e-9


class TestParsePromQL(SimpleTestCase):
    @parameterized.expand(
        [
            ("sum_by", "sum by (span) (sum_over_time(llm_generations[$__interval]))", None, ("span",), None),
            ("sum_trailing_by", 'sum(sum_over_time(m{a="x"}[1d])) by (b)', dt.timedelta(days=1), ("b",), None),
            ("repeated_group_label", "sum by (a, a, a) (sum_over_time(m[1h]))", dt.timedelta(hours=1), ("a",), None),
            (
                "topk_in_sort_desc",
                "sort_desc(topk(15, sum by (p) (sum_over_time(m[604800s]))))",
                dt.timedelta(days=7),
                ("p",),
                "topk",
            ),
            ("bottomk", "bottomk(3, sum(sum_over_time(m[1h30m])))", dt.timedelta(minutes=90), (), "bottomk"),
            ("rangeless", "sort(sum(sum_over_time(m)))", None, (), None),
        ]
    )
    def test_sum_over_time_shapes(self, _name, text, window, group_by, rank):
        query = parse_promql(text)
        assert not isinstance(query, str), query
        assert query.kind == PrecomputedMetricKind.SUM_OVER_TIME
        assert (query.window, query.group_by, query.rank) == (window, group_by, rank)

    def test_histogram_quantile_keeps_le_and_the_matchers(self):
        query = parse_promql(
            'histogram_quantile(0.95, sum by (le) (increase(llm_latency_seconds_bucket{model=~"gpt.*", env!="dev"}[6h])))'
        )
        assert not isinstance(query, str), query
        assert query.kind == PrecomputedMetricKind.BUCKET_INCREASE
        assert query.quantile == 0.95
        assert query.matchers == (
            Matcher(label="model", op="=~", value="gpt.*"),
            Matcher(label="env", op="!=", value="dev"),
        )
        assert query.kept_labels == ("env", "le", "model")

    @parameterized.expand(
        [
            ("rate", "sum(rate(m[5m]))"),
            ("avg", "avg(sum_over_time(m[1h]))"),
            ("sum_without", "sum without (a) (sum_over_time(m[1h]))"),
            ("offset", "sum(sum_over_time(m[1h] offset 1d))"),
            ("arithmetic", "100 * sum(sum_over_time(m[1h]))"),
            ("or", "sum(sum_over_time(m[1h])) or vector(0)"),
            ("name_matcher", 'sum(sum_over_time({__name__="m"}[1h]))'),
            ("quantile_without_le", "histogram_quantile(0.9, sum by (model) (increase(m_bucket[1h])))"),
            ("quantile_of_a_non_bucket", "histogram_quantile(0.9, sum by (le) (increase(m[1h])))"),
            ("sum_over_time_in_quantile", "histogram_quantile(0.9, sum by (le) (sum_over_time(m_bucket[1h])))"),
            ("rate_in_quantile", "histogram_quantile(0.9, sum by (le) (rate(m_bucket[1h])))"),
            ("two_topks", "topk(2, topk(3, sum by (a) (sum_over_time(m[1h]))))"),
            ("bad_escape", 'sum(sum_over_time(m{a=~"x\\.y"}[1h]))'),
            ("bare_selector", "sum(m)"),
            ("too_many_labels", "sum by (a, b, c, d, e, f) (sum_over_time(m[1h]))"),
            ("window_past_any_stored_range", "sum(sum_over_time(m[1000000y]))"),
            ("overlong_duration_token", f"sum(sum_over_time(m[{'1' * 40}s]))"),
            ("digit_dense_duration", "sum(sum_over_time(m[99999999999999999999ms]))"),
            ("summed_durations_past_timedelta", "sum(sum_over_time(m[999999999d999999999d]))"),
        ]
    )
    def test_other_shapes_run_raw(self, _name, text):
        assert isinstance(parse_promql(text), str)

    @parameterized.expand(
        [
            ("equal", "=", "gpt", {"gpt": True, "gpt-4": False, "": False}),
            ("not_equal", "!=", "gpt", {"gpt": False, "gpt-4": True, "": True}),
            ("regex_is_anchored", "=~", "gpt", {"gpt": True, "gpt-4": False, "a-gpt": False}),
            ("negated_regex_is_anchored", "!~", "gpt.*", {"gpt-4": False, "a-gpt": True, "": True}),
        ]
    )
    def test_matchers_follow_prometheus(self, _name, op, value, cases):
        matcher = Matcher(label="model", op=op, value=value)
        assert {label: matcher.matches(label) for label in cases} == cases

    @parameterized.expand(
        [
            ("middle_bucket", 0.5, [(0.5, 10.0), (1.0, 30.0), (math.inf, 40.0)], 0.75),
            ("top_bucket_returns_the_last_finite_bound", 0.99, [(0.5, 10.0), (1.0, 10.0), (math.inf, 40.0)], 1.0),
            ("no_inf_bucket", 0.5, [(0.5, 10.0), (1.0, 30.0)], math.nan),
            ("no_observations", 0.5, [(0.5, 0.0), (math.inf, 0.0)], math.nan),
            ("non_monotonic_is_fixed", 0.5, [(0.5, 10.0), (1.0, 5.0), (math.inf, 20.0)], 0.5),
            ("zero_quantile_with_an_empty_first_bucket", 0.0, [(0.5, 0.0), (1.0, 10.0), (math.inf, 10.0)], math.nan),
        ]
    )
    def test_histogram_quantile_matches_prometheus(self, _name, quantile, buckets, expected):
        value = histogram_quantile(quantile, buckets)
        assert (math.isnan(value) and math.isnan(expected)) or value == pytest.approx(expected)


def _snuffle() -> FakeSnuffle:
    snuffle = FakeSnuffle()
    minutes = int((NOW - SEED_FROM).total_seconds() // 60)
    series = [
        ("openai", "gpt", "chat", 10),
        ("openai", "gpt-mini", "search", 10),
        ("openai", "gpt", "search", 30),
        ("anthropic", "claude", "chat", 10),
        ("anthropic", "claude-haiku", "chat", 20),
        # Sparse, so many hourly windows hold no sample.
        ("anthropic", "slow", "search", 180),
    ]
    for index, (provider, model, product, every) in enumerate(series):
        # Some samples land exactly on a bucket boundary, which belongs to the bucket that ends there.
        samples = [
            (
                SEED_FROM + dt.timedelta(minutes=minute, seconds=0 if minute % 60 == 0 else 7 + index),
                0.01 * (1 + (minute * 13 + index * 7) % 17),
            )
            for minute in range(0, minutes, every)
        ]
        snuffle.add("llm_cost_usd", {"provider": provider, "model": model, "product": product}, samples)
    # The ttft histogram is a delta one: each point holds only its own observations.
    for metric, delta in (("llm_latency_seconds_bucket", False), ("llm_ttft_seconds_bucket", True)):
        for index, (model, every) in enumerate((("gpt", 5), ("claude", 7), ("slow", 45))):
            totals = [0.0] * len(LE)
            by_le: dict[str, list[tuple[dt.datetime, float]]] = {le: [] for le in LE}
            for minute in range(0, minutes, every):
                if minute == 3000 + index:
                    totals = [0.0] * len(LE)  # a counter reset
                observed = [(minute // every + index + bucket) % 3 for bucket in range(len(LE))]
                running = 0.0
                for bucket, le in enumerate(LE):
                    running += observed[bucket]
                    totals[bucket] += running
                    point = running if delta else totals[bucket]
                    by_le[le].append((SEED_FROM + dt.timedelta(minutes=minute, seconds=13), point))
            for le, points in by_le.items():
                snuffle.add(metric, {"model": model, "le": le}, points, delta=delta)
    return snuffle


def _max_relative_difference(precomputed: list[MetricSeries], raw: list[MetricSeries]) -> float:
    def points(result: list[MetricSeries]) -> dict[tuple, float | None]:
        return {(tuple(sorted(s.labels.items())), p.time): p.value for s in result for p in s.points}

    got, expected = points(precomputed), points(raw)
    assert got.keys() == expected.keys()
    differences = [0.0]
    for key, value in expected.items():
        assert (value is None) == (got[key] is None), key
        if value is not None and got[key] is not None:
            differences.append(abs(got[key] - value) / max(abs(value), 1e-12))  # type: ignore[operator]
    return max(differences)


# Fills and planned tiles run the gate and the temporality lookup; both are pinned here.
@override_settings(IN_UNIT_TESTING=True)
class TestPrecomputedPromQL(APIBaseTest):
    def setUp(self):
        super().setUp()
        for target, value in (
            ("products.metrics.backend.precompute.gate.posthog_feature_flag_enabled", True),
            ("products.metrics.backend.precompute.promql_plan._is_delta_histogram", None),
        ):
            patcher = (
                patch(target, return_value=value)
                if value is not None
                else patch(target, side_effect=lambda team, name: name.startswith("llm_ttft"))
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        # A sampled shadow check runs the tile raw, which would add its whole-window query at random.
        shadow = patch("products.metrics.backend.facade.api.PRECOMPUTE_SHADOW_CHECK_RATE", 0.0)
        shadow.start()
        self.addCleanup(shadow.stop)
        self.snuffle = _snuffle()

    def _run(self, promql: str, days: int, interval: str):
        with fake_snuffle(self.snuffle):
            return run_precomputed_promql_query(
                team=self.team, promql=promql, date_from=NOW - dt.timedelta(days=days), date_to=NOW, interval=interval
            )

    def _raw(self, promql: str, days: int, interval: str) -> list[MetricSeries]:
        with fake_snuffle(self.snuffle):
            return run_promql_range(self.team, promql, NOW - dt.timedelta(days=days), NOW, interval)

    def _precompute(self, promql: str, days: int, interval: str) -> None:
        first = self._run(promql, days, interval)
        assert first.provenance.reasons == ("precomputing started",), first.provenance
        with fake_snuffle(self.snuffle):
            fill_precomputed_metrics(self.team.pk, now=NOW)

    @parameterized.expand(
        [
            (
                "sum_by_provider_hourly",
                "sum by (provider) (sum_over_time(llm_cost_usd[$__interval]))",
                2,
                "hour",
                EXACT,
            ),
            ("total_one_day_window_6h_step", "sum(sum_over_time(llm_cost_usd[1d]))", 7, "hour_6", EXACT),
            (
                "topk_models_with_a_regex",
                'topk(2, sum by (model) (sum_over_time(llm_cost_usd{provider=~"open.*"}[$__interval])))',
                2,
                "hour",
                EXACT,
            ),
            (
                "sort_desc_topk_over_the_range",
                "sort_desc(topk(3, sum by (product) (sum_over_time(llm_cost_usd[$__range]))))",
                7,
                "hour_6",
                EXACT,
            ),
            (
                "bottomk_trailing_by",
                'bottomk(1, sum(sum_over_time(llm_cost_usd{product!~"sea.*"}[2h])) by (model))',
                2,
                "hour",
                EXACT,
            ),
            ("sort_daily", "sort(sum by (provider) (sum_over_time(llm_cost_usd[$__interval])))", 7, "day", EXACT),
            (
                "sum_by_le_keeps_each_bucket",
                "sum by (le) (sum_over_time(llm_latency_seconds_bucket[$__interval]))",
                2,
                "hour",
                EXACT,
            ),
            (
                "p95_cumulative_hourly",
                "histogram_quantile(0.95, sum by (le) (increase(llm_latency_seconds_bucket[$__interval])))",
                2,
                "hour",
                EXACT,
            ),
            (
                "p50_by_model_cumulative",
                'histogram_quantile(0.5, sum by (le, model) (increase(llm_latency_seconds_bucket{model!="slow"}[1h])))',
                2,
                "hour",
                EXACT,
            ),
            (
                "p95_delta_6h",
                "histogram_quantile(0.95, sum by (le) (increase(llm_ttft_seconds_bucket[$__interval])))",
                7,
                "hour_6",
                EXACT,
            ),
            # A delta histogram's increase is the sum of its points, so summed buckets are exact for any window.
            (
                "p95_delta_daily",
                "histogram_quantile(0.95, sum by (le) (increase(llm_ttft_seconds_bucket[$__interval])))",
                7,
                "day",
                EXACT,
            ),
            (
                "p50_delta_over_the_range",
                "histogram_quantile(0.5, sum by (le) (increase(llm_ttft_seconds_bucket[$__range])))",
                7,
                "hour_6",
                EXACT,
            ),
            # A cumulative histogram's increase extrapolates per window, so summed buckets can read slightly low.
            (
                "p95_cumulative_over_the_range",
                "histogram_quantile(0.95, sum by (le) (increase(llm_latency_seconds_bucket[$__range])))",
                7,
                "hour_6",
                0.05,
            ),
        ]
    )
    def test_matches_raw_over_a_range_spanning_stored_and_raw_steps(
        self, name: str, promql: str, days: int, interval: str, tolerance: float
    ):
        self._precompute(promql, days, interval)
        precomputed = MetricPrecomputedMetric.objects.for_team(self.team.pk).get()
        queried_before = len(self.snuffle.queries)

        result = self._run(promql, days, interval)

        # The raw tail reads only the buckets after the stored ones, never the tile's whole window.
        bucket_window = f"[{precomputed.bucket_seconds}s]"
        assert all(bucket_window in query for query in self.snuffle.queries[queried_before:]), self.snuffle.queries
        # A daily tile's last step is midnight, which is stored, so it has no raw tail.
        expected = MetricQueryProvenanceMode.PRECOMPUTED if interval == "day" else MetricQueryProvenanceMode.MIXED
        assert result.provenance.mode == expected, result.provenance
        assert result.provenance.precomputed_until is not None and result.provenance.precomputed_until < NOW
        difference = _max_relative_difference(result.series, self._raw(promql, days, interval))
        print(f"promql parity {name}: max relative difference {difference:.3g}")  # noqa: T201
        assert difference <= tolerance

    def test_delta_histograms_use_six_hour_buckets(self):
        promql = "histogram_quantile(0.95, sum by (le) (increase(llm_ttft_seconds_bucket[$__interval])))"
        self._precompute(promql, 7, "hour_6")

        precomputed = MetricPrecomputedMetric.objects.for_team(self.team.pk).get()
        assert precomputed.bucket_seconds == DELTA_HISTOGRAM_BUCKET.total_seconds()
        assert precomputed.kind == PrecomputedMetricKind.BUCKET_INCREASE
        assert [label["key"] for label in precomputed.labels] == ["le"]

    def test_a_fill_response_over_the_byte_budget_splits_the_range(self):
        promql = "sum by (provider) (sum_over_time(llm_cost_usd[$__interval]))"
        with patch("products.metrics.backend.precompute.fill.MAX_FILL_RESPONSE_BYTES", 600):
            self._precompute(promql, 2, "hour")

        result = self._run(promql, 2, "hour")

        assert result.provenance.mode == MetricQueryProvenanceMode.MIXED, result.provenance
        assert _max_relative_difference(result.series, self._raw(promql, 2, "hour")) <= EXACT

    def test_fills_read_whole_buckets_without_counting_as_user_queries(self):
        promql = "sum by (provider) (sum_over_time(llm_cost_usd[$__interval]))"

        self._precompute(promql, 2, "hour")

        assert "sum by (provider) (sum_over_time(llm_cost_usd[3600s]))" in self.snuffle.queries
        # Only the tile that created the metric counts, not the fill's queries.
        assert MetricDailyQueryCount.objects.for_team(self.team.pk).get(metric_name="llm_cost_usd").query_count == 1

    @parameterized.expand(
        [
            ("window_not_whole_buckets", "sum(sum_over_time(llm_cost_usd[5m]))", "hour", "whole 1-hour buckets"),
            ("step_not_whole_buckets", "sum(sum_over_time(llm_cost_usd[$__interval]))", "minute_30", "whole 1-hour"),
            (
                "delta_histogram_hourly",
                "histogram_quantile(0.5, sum by (le) (increase(llm_ttft_seconds_bucket[1h])))",
                "hour",
                "whole 6-hour",
            ),
        ]
    )
    def test_queries_off_the_bucket_grid_run_raw_unchanged(self, _name, promql, interval, reason):
        result = self._run(promql, 2, interval)

        assert result.provenance.mode == MetricQueryProvenanceMode.RAW
        assert reason in result.provenance.reasons[0]
        assert result.series == self._raw(promql, 2, interval)
        assert not MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()

    def test_a_short_range_does_not_create_a_metric(self):
        result = self._run("sum(sum_over_time(llm_cost_usd[$__interval]))", 0, "hour")

        assert result.provenance.reasons == ("the range is too short to precompute",)

    def test_a_project_without_precomputing_runs_raw(self):
        with patch("products.metrics.backend.precompute.gate.posthog_feature_flag_enabled", return_value=False):
            result = self._run("sum(sum_over_time(llm_cost_usd[$__interval]))", 2, "hour")

        assert result.provenance.reasons == ("precomputing is off for this project",)
        assert not MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()

    def test_a_tile_answered_fully_from_storage_counts_as_one_query(self):
        promql = "sort(sum by (provider) (sum_over_time(llm_cost_usd[$__interval])))"
        self._precompute(promql, 7, "day")
        MetricDailyQueryCount.objects.for_team(self.team.pk).delete()

        result = self._run(promql, 7, "day")

        assert result.provenance.mode == MetricQueryProvenanceMode.PRECOMPUTED
        assert list(MetricDailyQueryCount.objects.for_team(self.team.pk).values_list("metric_name", "query_count")) == [
            ("llm_cost_usd", 1)
        ]

    def test_a_tile_whose_window_expands_past_the_budget_runs_raw(self):
        promql = "sum(sum_over_time(llm_cost_usd[1d]))"
        self._precompute(promql, 7, "hour")

        with patch("products.metrics.backend.precompute.promql_plan.MAX_EXPANDED_POINTS", 10):
            result = self._run(promql, 7, "hour")

        assert result.provenance.reasons == ("too much stored data to load",)
        assert result.series == self._raw(promql, 7, "hour")

    def test_a_sampled_tile_reports_its_shadow_check(self):
        promql = "sum by (model) (sum_over_time(llm_cost_usd[$__interval]))"
        self._precompute(promql, 2, "hour")

        with patch("products.metrics.backend.facade.api.PRECOMPUTE_SHADOW_CHECK_RATE", 1.0):
            result = self._run(promql, 2, "hour")

        assert result.shadow is not None
        assert result.shadow.max_relative_difference == pytest.approx(0.0, abs=EXACT)
        assert result.shadow.mismatched_points == 0


class TestDeltaHistogramLookup(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        truncate_metrics_tables()

    def test_tells_delta_histograms_from_cumulative_ones(self):
        now = timezone.now()
        for name, temporality in (("ttft_seconds", "delta"), ("latency_seconds", "cumulative")):
            seed_metric(
                team_id=self.team.pk,
                metric_name=name,
                metric_type="histogram",
                aggregation_temporality=temporality,
                histogram_bounds=[0.5],
                histogram_counts=[1, 1],
                points=[(now - dt.timedelta(minutes=5), 0.0)],
            )

        assert _is_delta_histogram(self.team, "ttft_seconds_bucket") is True
        assert _is_delta_histogram(self.team, "latency_seconds_bucket") is False


@override_settings(IN_UNIT_TESTING=True)
class TestMetricsQueryRunnerPromQLPrecompute(APIBaseTest):
    def _run(self, snuffle: FakeSnuffle, user: User | SharedLinkUser | None = None, interval: str = "hour"):
        runner = MetricsQueryRunner(
            query=MetricsQuery(
                language="promql",
                clauses=[],
                promql="sum by (provider) (sum_over_time(llm_cost_usd[$__interval]))",
                interval=interval,
                dateRange={"date_from": "-2d"},
            ),
            team=self.team,
            user=cast(User, user or self.user),
        )
        with (
            fake_snuffle(snuffle),
            patch(
                "products.metrics.backend.hogql_queries.metrics_query_runner.posthog_feature_flag_enabled",
                return_value=True,
            ),
            patch("products.metrics.backend.precompute.gate.posthog_feature_flag_enabled", return_value=True),
            patch("products.metrics.backend.facade.api.PRECOMPUTE_SHADOW_CHECK_RATE", 1.0),
            patch("posthog.hogql_queries.query_runner.report_user_or_team_action") as report,
        ):
            response = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, dashboard_id=1)
        (properties,) = [call.args[1] for call in report.call_args_list if call.args[0] == "query executed"]
        return response, properties

    @parameterized.expand(
        [
            # The last hourly step is newer than the stored buckets, so it reads raw.
            ("hour", "mixed", "mixed"),
            # The last daily step is midnight, which is stored.
            ("day", "precomputed", "derived"),
        ]
    )
    def test_a_planned_tile_puts_its_provenance_and_shadow_check_on_query_executed(
        self, interval: str, response_mode: str, event_provenance: str
    ):
        snuffle = _snuffle()
        with time_machine.travel(NOW, tick=False):
            first, first_properties = self._run(snuffle, interval=interval)
            with (
                fake_snuffle(snuffle),
                patch("products.metrics.backend.precompute.gate.posthog_feature_flag_enabled", return_value=True),
            ):
                fill_precomputed_metrics(self.team.pk, now=NOW)
            response, properties = self._run(snuffle, interval=interval)

        assert first.provenance is not None and first.provenance.mode == "raw"
        assert first_properties["precompute_provenance"] == "raw"
        assert first_properties["precompute_shadow_checked"] is False
        assert response.provenance is not None and response.provenance.mode == response_mode
        assert properties["precompute_provenance"] == event_provenance
        assert properties["precompute_shadow_checked"] is True
        assert properties["precompute_shadow_max_rel_diff"] == pytest.approx(0.0, abs=EXACT)
        assert properties["precompute_shadow_mismatched_points"] == 0

    def test_a_shared_link_viewer_neither_creates_nor_keeps_a_metric_in_use(self):
        viewer = SharedLinkUser(SharingConfiguration(team=self.team, enabled=True))
        snuffle = _snuffle()
        with time_machine.travel(NOW, tick=False):
            first, _ = self._run(snuffle, viewer)
            assert first.provenance is not None and first.provenance.reasons == [NOT_STARTED_BY_VIEWER]
            assert not MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()

            self._run(snuffle)
            stale = NOW - dt.timedelta(days=3)
            MetricPrecomputedMetric.objects.for_team(self.team.pk).update(last_used_at=stale)
            self._run(snuffle, viewer)

        assert MetricPrecomputedMetric.objects.for_team(self.team.pk).get().last_used_at == stale
