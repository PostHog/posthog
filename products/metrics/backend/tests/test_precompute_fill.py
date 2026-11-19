import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.metrics.backend.facade.enums import AttributeScope, PrecomputedMetricKind
from products.metrics.backend.facade.tasks import schedule_metrics_precompute_fills
from products.metrics.backend.models import MetricPrecomputedChunk, MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import LabelRef, Leaf, get_or_create_precomputed_metric
from products.metrics.backend.precompute.fill import RETENTION, fill_precomputed_metrics
from products.metrics.backend.precompute.store import read_entries
from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables

NOW = dt.datetime(2026, 11, 12, 12, 7, tzinfo=dt.UTC)
SETTLED = dt.datetime(2026, 11, 12, 11, 0, tzinfo=dt.UTC)
BOUNDS = [0.1, 0.5, 1.0]


def _hours(start: dt.datetime, count: int) -> list[dt.datetime]:
    return [start + dt.timedelta(hours=index) for index in range(count)]


class TestFillPrecomputedMetrics(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    def setUp(self):
        super().setUp()
        truncate_metrics_tables()

    def _seed_delta_counter(self, service: str, per_sample: float, start: dt.datetime, hours: int) -> None:
        # Six samples an hour, so an hour's increase is six times the sample.
        seed_metric(
            team_id=self.team.pk,
            metric_name="requests_total",
            metric_type="sum",
            aggregation_temporality="delta",
            is_monotonic=True,
            service_name=service,
            points=[(start + dt.timedelta(minutes=10 * index + 1), per_sample) for index in range(6 * hours)],
        )

    def _seed_delta_histogram(self, service: str, counts: list[int], start: dt.datetime, hours: int) -> None:
        for index in range(6 * hours):
            seed_metric(
                team_id=self.team.pk,
                metric_name="latency",
                metric_type="histogram",
                aggregation_temporality="delta",
                service_name=service,
                histogram_bounds=BOUNDS,
                histogram_counts=counts,
                points=[(start + dt.timedelta(minutes=10 * index + 1), 0.0)],
            )

    def _create(self, kind: PrecomputedMetricKind, metric_name: str) -> MetricPrecomputedMetric:
        precomputed = get_or_create_precomputed_metric(
            self.team.pk,
            Leaf(
                metric_name=metric_name,
                metric_type=None,
                kind=kind,
                labels=(LabelRef("service_name", AttributeScope.AUTO),),
            ),
        )
        assert precomputed is not None
        return precomputed

    def _fill(self, now: dt.datetime = NOW) -> MetricPrecomputedMetric:
        fill_precomputed_metrics(self.team.pk, now=now)
        return MetricPrecomputedMetric.objects.for_team(self.team.pk).get()

    def _stored(self, precomputed: MetricPrecomputedMetric) -> dict[tuple[str, ...], dict[dt.datetime, object]]:
        assert precomputed.covered_from is not None and precomputed.covered_to is not None
        entries = read_entries(precomputed, precomputed.covered_from, precomputed.covered_to)
        return {entry.labels: dict(entry.points) for entry in entries.values()}

    def test_fills_forward_then_back_to_the_retention_window(self):
        start = SETTLED - dt.timedelta(hours=30)
        self._seed_delta_counter("checkout", 1.0, start, 30)
        self._seed_delta_counter("search", 2.0, start, 30)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")

        precomputed = self._fill()

        assert precomputed.covered_to == SETTLED
        assert precomputed.covered_from == (NOW - RETENTION).replace(minute=0)
        stored = self._stored(precomputed)
        assert stored == {
            ("checkout",): dict.fromkeys(_hours(start, 30), 6.0),
            ("search",): dict.fromkeys(_hours(start, 30), 12.0),
        }

    def test_stores_summed_histogram_bucket_counts(self):
        start = SETTLED - dt.timedelta(hours=3)
        self._seed_delta_histogram("checkout", [1, 2, 0, 0], start, 3)
        self._seed_delta_histogram("search", [0, 0, 1, 1], start, 3)
        self._create(PrecomputedMetricKind.HISTOGRAM, "latency")

        precomputed = self._fill()

        stored = self._stored(precomputed)
        assert stored == {
            ("checkout",): dict.fromkeys(_hours(start, 3), [6.0, 12.0, 0.0, 0.0]),
            ("search",): dict.fromkeys(_hours(start, 3), [0.0, 0.0, 6.0, 6.0]),
        }

    def test_a_second_pass_over_the_same_hours_changes_nothing(self):
        self._seed_delta_counter("checkout", 1.0, SETTLED - dt.timedelta(hours=5), 5)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        precomputed = self._fill()
        before = list(MetricPrecomputedChunk.objects.for_team(self.team.pk).order_by("day").values("day", "series"))

        precomputed.covered_from = precomputed.covered_to = None
        precomputed.save()
        self._fill()

        after = list(MetricPrecomputedChunk.objects.for_team(self.team.pk).order_by("day").values("day", "series"))
        assert after == before

    def test_late_data_in_the_reread_window_is_rewritten_and_widens_settle(self):
        last_hour = SETTLED - dt.timedelta(hours=1)
        self._seed_delta_counter("checkout", 1.0, last_hour - dt.timedelta(hours=2), 3)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        self._fill()

        seed_metric(
            team_id=self.team.pk,
            metric_name="requests_total",
            metric_type="sum",
            aggregation_temporality="delta",
            is_monotonic=True,
            service_name="checkout",
            points=[(last_hour + dt.timedelta(minutes=59), 4.0)],
        )
        precomputed = self._fill(now=NOW + dt.timedelta(hours=1))

        assert self._stored(precomputed)[("checkout",)][last_hour] == 10.0
        assert precomputed.settle_seconds > 900
        assert precomputed.covered_to is not None
        assert precomputed.covered_to > SETTLED

    def test_splits_a_fill_that_returns_too_many_rows(self):
        start = SETTLED - dt.timedelta(hours=6)
        self._seed_delta_counter("checkout", 1.0, start, 6)
        self._seed_delta_counter("search", 2.0, start, 6)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")

        with patch("products.metrics.backend.metric_query_runner._ROW_LIMIT", 5):
            precomputed = self._fill()

        assert precomputed.state == MetricPrecomputedMetric.State.ACTIVE
        assert self._stored(precomputed)[("search",)] == dict.fromkeys(_hours(start, 6), 12.0)

    def test_pauses_when_one_hour_has_too_many_series(self):
        self._seed_delta_counter("checkout", 1.0, SETTLED - dt.timedelta(hours=2), 2)
        self._seed_delta_counter("search", 2.0, SETTLED - dt.timedelta(hours=2), 2)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")

        with patch("products.metrics.backend.metric_query_runner._ROW_LIMIT", 2):
            precomputed = self._fill()

        assert precomputed.state == MetricPrecomputedMetric.State.PAUSED
        assert "fewer labels" in (precomputed.last_error or "")

    @parameterized.expand([("used_recently", 1, True), ("unused_for_two_weeks", 15, False)])
    def test_deletes_metrics_no_tile_used_for_two_weeks(self, _name: str, days_unused: int, kept: bool):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        precomputed.last_used_at = NOW - dt.timedelta(days=days_unused)
        precomputed.save()

        fill_precomputed_metrics(self.team.pk, now=NOW)

        assert MetricPrecomputedMetric.objects.for_team(self.team.pk).exists() is kept

    def test_drops_chunks_past_retention(self):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        old_day = (NOW - RETENTION - dt.timedelta(days=2)).date()
        MetricPrecomputedChunk.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, precomputed_metric=precomputed, day=old_day, series=[]
        )
        precomputed.covered_from = dt.datetime.combine(old_day, dt.time(), tzinfo=dt.UTC)
        precomputed.covered_to = SETTLED
        precomputed.last_used_at = timezone.now()
        precomputed.save()

        precomputed = self._fill()

        assert not MetricPrecomputedChunk.objects.for_team(self.team.pk).filter(day=old_day).exists()
        assert precomputed.covered_from is not None
        assert precomputed.covered_from >= NOW - RETENTION - dt.timedelta(days=1)

    def test_the_scheduled_task_fills_each_team_with_an_active_metric(self):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")

        schedule_metrics_precompute_fills()

        precomputed.refresh_from_db()
        assert precomputed.covered_to is not None
