import time
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.metrics.backend.facade.enums import AttributeScope, PrecomputedMetricKind
from products.metrics.backend.facade.tasks import schedule_metrics_precompute_fills
from products.metrics.backend.metric_samples_query_runner import build_metric_query_runner
from products.metrics.backend.models import MetricPrecomputedChunk, MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import LabelRef, Leaf, get_or_create_precomputed_metric
from products.metrics.backend.precompute.fill import FINAL_AFTER, RETENTION, fill_precomputed_metrics, fill_step
from products.metrics.backend.precompute.store import Entry, UnstorableLabelError, read_entries, write_entries
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
        gate = patch("products.metrics.backend.precompute.fill.precompute_enabled", return_value=True)
        self.precompute_enabled = gate.start()
        self.addCleanup(gate.stop)

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
        before = list(
            MetricPrecomputedChunk.objects.for_team(self.team.pk).order_by("start").values("start", "series", "final")
        )

        precomputed.covered_from = precomputed.covered_to = None
        precomputed.save()
        self._fill()

        after = list(
            MetricPrecomputedChunk.objects.for_team(self.team.pk).order_by("start").values("start", "series", "final")
        )
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

    @parameterized.expand(
        [
            ("nothing_stored_yet", 0, 1, [0]),
            ("stored_hours_inside_the_reread_window", 2, 4, [2, 3]),
        ]
    )
    def test_a_split_fill_past_the_deadline_saves_the_hours_it_finished(
        self, _name: str, covered_hours: int, reached_hours: int, stored_hours: list[int]
    ):
        start = SETTLED - dt.timedelta(hours=6)
        self._seed_delta_counter("checkout", 1.0, start, 6)
        self._seed_delta_counter("search", 2.0, start, 6)
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        precomputed.covered_from = start
        precomputed.covered_to = start + dt.timedelta(hours=covered_hours)
        precomputed.save()

        with patch("products.metrics.backend.metric_query_runner._ROW_LIMIT", 5):
            fill_step(self.team, precomputed, NOW, deadline=time.monotonic())

        assert precomputed.covered_to == start + dt.timedelta(hours=reached_hours)
        hours = [start + dt.timedelta(hours=hour) for hour in stored_hours]
        assert self._stored(precomputed) == {
            ("checkout",): dict.fromkeys(hours, 6.0),
            ("search",): dict.fromkeys(hours, 12.0),
        }

    def test_a_long_forward_backlog_is_filled_a_day_at_a_time_in_hours(self):
        start = SETTLED - dt.timedelta(days=25)
        self._seed_delta_counter("checkout", 1.0, start, 24)
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        precomputed.covered_from = precomputed.covered_to = start
        precomputed.save()

        fill_step(self.team, precomputed, NOW)

        assert precomputed.covered_to == start + dt.timedelta(days=1)
        assert self._stored(precomputed) == {("checkout",): dict.fromkeys(_hours(start, 24), 6.0)}

    @parameterized.expand(
        [("under_the_cap", {10, 20}, {10, 20}, False), ("over_the_cap", {30, 10, 20}, {10, 20}, True)]
    )
    def test_stores_a_bounded_sample_of_fingerprints_per_entry(
        self, _name: str, fingerprints: set[int], kept: set[int], truncated: bool
    ):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        entry = Entry(labels=(), fingerprints=fingerprints, points={SETTLED: 1.0})

        with patch("products.metrics.backend.precompute.store.MAX_FINGERPRINTS_PER_ENTRY", 2):
            write_entries(precomputed, SETTLED, SETTLED + dt.timedelta(hours=1), {entry.key: entry})

        stored = read_entries(precomputed, SETTLED, SETTLED + dt.timedelta(hours=1))
        assert [
            (stored_entry.fingerprints, stored_entry.fingerprints_truncated) for stored_entry in stored.values()
        ] == [(kept, truncated)]

    def test_refuses_a_label_value_postgres_cannot_store(self):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        entry = Entry(labels=("check\x00out",), points={SETTLED: 1.0})

        with self.assertRaises(UnstorableLabelError):
            write_entries(precomputed, SETTLED, SETTLED + dt.timedelta(hours=1), {entry.key: entry})

    def test_the_fill_query_returns_at_most_the_capped_fingerprints_per_row(self):
        start = SETTLED - dt.timedelta(hours=2)
        self._seed_delta_counter("checkout", 1.0, start, 2)
        self._seed_delta_counter("search", 2.0, start, 2)

        uncapped, capped = (
            build_metric_query_runner(
                team=self.team,
                metric_name="requests_total",
                aggregation="increase",
                date_from=start,
                date_to=SETTLED,
                interval="hour",
                max_series_fingerprints=cap,
            ).run()
            for cap in (None, 1)
        )

        assert [len(row["series_fingerprints"]) for row in uncapped] == [2, 2]
        assert [row["series_fingerprints"] for row in capped] == [[min(row["series_fingerprints"])] for row in uncapped]

    def test_stores_non_finite_histogram_bounds(self):
        precomputed = self._create(PrecomputedMetricKind.HISTOGRAM, "latency")
        entry = Entry(
            labels=("checkout",), metric_type="histogram", bounds=(0.1, float("inf")), points={SETTLED: [1.0, 2.0, 3.0]}
        )

        write_entries(precomputed, SETTLED, SETTLED + dt.timedelta(hours=1), {entry.key: entry})

        stored = read_entries(precomputed, SETTLED, SETTLED + dt.timedelta(hours=1))
        assert [(stored_entry.bounds, stored_entry.points) for stored_entry in stored.values()] == [
            ((0.1, float("inf")), {SETTLED: [1.0, 2.0, 3.0]})
        ]

    @parameterized.expand(
        [
            ("one_hour", "products.metrics.backend.metric_query_runner._ROW_LIMIT", 2),
            ("one_bucket", "products.metrics.backend.precompute.store.MAX_ENTRIES_PER_CHUNK", 1),
        ]
    )
    def test_pauses_when_too_many_series(self, _name: str, limit_path: str, limit: int):
        self._seed_delta_counter("checkout", 1.0, SETTLED - dt.timedelta(hours=2), 2)
        self._seed_delta_counter("search", 2.0, SETTLED - dt.timedelta(hours=2), 2)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")

        with patch(limit_path, limit):
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
        old_hour = (NOW - RETENTION - dt.timedelta(days=2)).replace(minute=0)
        MetricPrecomputedChunk.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, precomputed_metric=precomputed, start=old_hour, series=[]
        )
        precomputed.covered_from = old_hour
        precomputed.covered_to = SETTLED
        precomputed.last_used_at = timezone.now()
        precomputed.save()

        precomputed = self._fill()

        assert not MetricPrecomputedChunk.objects.for_team(self.team.pk).filter(start=old_hour).exists()
        assert precomputed.covered_from is not None
        assert precomputed.covered_from >= NOW - RETENTION - dt.timedelta(days=1)

    def test_the_scheduled_task_fills_each_team_with_an_active_metric(self):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")

        schedule_metrics_precompute_fills()

        precomputed.refresh_from_db()
        assert precomputed.covered_to is not None

    def test_the_scheduled_task_sweeps_a_team_whose_metrics_are_all_paused(self):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        precomputed.state = MetricPrecomputedMetric.State.PAUSED
        precomputed.last_used_at = timezone.now() - dt.timedelta(days=15)
        precomputed.save()

        schedule_metrics_precompute_fills()

        assert not MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()

    def _chunks(self) -> dict[dt.datetime, tuple[object, bool]]:
        return {
            chunk.start: (chunk.series, chunk.final)
            for chunk in MetricPrecomputedChunk.objects.for_team(self.team.pk).order_by("start")
        }

    def test_writes_only_the_buckets_whose_values_changed(self):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        hours = _hours(SETTLED - dt.timedelta(hours=3), 3)
        entry = Entry(labels=("checkout",), points=dict.fromkeys(hours, 6.0))
        assert write_entries(precomputed, hours[0], SETTLED, {entry.key: entry}) == 3
        written_at = {chunk.start: chunk.computed_at for chunk in MetricPrecomputedChunk.objects.for_team(self.team.pk)}

        entry.points[hours[1]] = 7.0
        assert write_entries(precomputed, hours[0], SETTLED, {entry.key: entry}) == 1

        chunks = MetricPrecomputedChunk.objects.for_team(self.team.pk)
        assert sorted(chunk.start for chunk in chunks if chunk.computed_at != written_at[chunk.start]) == [hours[1]]
        assert self._stored(self._fill_coverage(precomputed, hours[0]))[("checkout",)] == {
            hours[0]: 6.0,
            hours[1]: 7.0,
            hours[2]: 6.0,
        }

    def _fill_coverage(self, precomputed: MetricPrecomputedMetric, start: dt.datetime) -> MetricPrecomputedMetric:
        precomputed.covered_from, precomputed.covered_to = start, SETTLED
        return precomputed

    @parameterized.expand([("next_day", 25), ("after_three_days_without_fills", 72)])
    def test_the_daily_refill_rewrites_late_data_past_the_reread_and_marks_old_buckets_final(
        self, _name: str, hours_later: int
    ):
        start = SETTLED - dt.timedelta(hours=30)
        self._seed_delta_counter("checkout", 1.0, start, 30)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        self._fill()
        late_hour = SETTLED - dt.timedelta(hours=10)
        seed_metric(
            team_id=self.team.pk,
            metric_name="requests_total",
            metric_type="sum",
            aggregation_temporality="delta",
            is_monotonic=True,
            service_name="checkout",
            points=[(late_hour + dt.timedelta(minutes=59), 4.0)],
        )

        # The forward re-read covers only the newest hours, so the late hour waits for the daily re-fill.
        precomputed = self._fill(now=NOW + dt.timedelta(hours=1))
        assert self._stored(precomputed)[("checkout",)][late_hour] == 6.0

        later = NOW + dt.timedelta(hours=hours_later)
        precomputed = self._fill(now=later)

        assert self._stored(precomputed)[("checkout",)][late_hour] == 10.0
        assert precomputed.refilled_at == later
        for bucket_start, (_, final) in self._chunks().items():
            assert final is (bucket_start + dt.timedelta(hours=1) <= later - FINAL_AFTER), bucket_start

    def test_the_refill_reads_late_data_in_an_hour_that_was_empty_after_a_pause_in_fills(self):
        self._seed_delta_counter("checkout", 1.0, SETTLED - dt.timedelta(hours=40), 10)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        self._fill()
        empty_hour = SETTLED - dt.timedelta(hours=10)
        seed_metric(
            team_id=self.team.pk,
            metric_name="requests_total",
            metric_type="sum",
            aggregation_temporality="delta",
            is_monotonic=True,
            service_name="checkout",
            points=[(empty_hour + dt.timedelta(minutes=30), 4.0)],
        )

        precomputed = self._fill(now=NOW + dt.timedelta(hours=72))

        assert self._stored(precomputed)[("checkout",)][empty_hour] == 4.0

    def test_a_final_bucket_is_never_rewritten(self):
        precomputed = self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        hour = SETTLED - dt.timedelta(days=3)
        entry = Entry(labels=("checkout",), points={hour: 6.0})
        write_entries(precomputed, hour, hour + dt.timedelta(hours=1), {entry.key: entry}, final_before=NOW)

        entry.points[hour] = 9.0
        assert write_entries(precomputed, hour, hour + dt.timedelta(hours=1), {entry.key: entry}) == 0

        assert self._chunks()[hour] == ([{"labels": ["checkout"], "fingerprints": [], "value": 6.0}], True)

    def test_backfilled_buckets_past_the_lateness_cap_and_ingestion_allowance_are_final(self):
        start = SETTLED - dt.timedelta(hours=30)
        self._seed_delta_counter("checkout", 1.0, start, 30)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")

        self._fill()

        chunks = self._chunks()
        assert len([series for series, _ in chunks.values() if series]) == 30
        for bucket_start, (_, final) in chunks.items():
            assert final is (bucket_start + dt.timedelta(hours=1) <= NOW - FINAL_AFTER), bucket_start

    def test_does_not_fill_a_team_without_precomputing(self):
        self._seed_delta_counter("checkout", 1.0, SETTLED - dt.timedelta(hours=2), 2)
        self._create(PrecomputedMetricKind.INCREASE, "requests_total")
        self.precompute_enabled.return_value = False

        precomputed = self._fill()

        assert precomputed.covered_to is None
        assert not MetricPrecomputedChunk.objects.for_team(self.team.pk).exists()
