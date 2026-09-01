import datetime as dt

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.clickhouse.client import sync_execute

from products.metrics.backend import diagnostics
from products.metrics.backend.diagnostics import decompose_bucket
from products.metrics.backend.fundamentals import SpatialReducer, TemporalReducer
from products.metrics.backend.tests._seeder import seed_metric

BUCKET = dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.UTC)


class TestBucketDecomposition(ClickhouseTestMixin, APIBaseTest):
    """The decomposition recomputes a chart point from raw samples in Python and
    reports it next to what the HogQL runner returned. The two disagreeing is the
    signal — it means one of the reductions is wrong, and the breakdown shows which."""

    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def _seed_gauge_pair(self) -> None:
        # Two pods reporting the same gauge, three scrapes each inside one bucket.
        seed_metric(
            team_id=self.team.pk,
            metric_name="cache_size",
            metric_type="gauge",
            aggregation_temporality="",
            labels={"pod": "a"},
            points=[
                (BUCKET, 5.0),
                (BUCKET + dt.timedelta(seconds=60), 8.0),
                (BUCKET + dt.timedelta(seconds=120), 11.0),
            ],
        )
        seed_metric(
            team_id=self.team.pk,
            metric_name="cache_size",
            metric_type="gauge",
            aggregation_temporality="",
            labels={"pod": "b"},
            points=[
                (BUCKET, 20.0),
                (BUCKET + dt.timedelta(seconds=60), 21.0),
                (BUCKET + dt.timedelta(seconds=120), 22.0),
            ],
        )

    def test_gauge_breakdown_reduces_each_series_to_its_latest_reading(self) -> None:
        self._seed_gauge_pair()

        decomposition = decompose_bucket(
            team=self.team,
            metric_name="cache_size",
            aggregation="sum",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        assert decomposition.temporal_reducer == TemporalReducer.LAST
        assert decomposition.spatial_reducer == SpatialReducer.SUM
        assert decomposition.series_count == 2
        assert decomposition.sample_count == 6
        # 11 and 22 are the latest readings; the four earlier samples are re-readings.
        contributions = [series.value for series in decomposition.series]
        assert sorted(value for value in contributions if value is not None) == [11.0, 22.0]
        assert None not in contributions
        assert decomposition.reference_value == 33.0

    def test_reports_disagreement_between_the_runner_and_the_reference(self) -> None:
        """Whether these agree depends on the runner, which is the point: the check
        holds a reduction the runner does not share, so a regression on either side
        shows up as a disagreement rather than as a plausible-looking number."""
        self._seed_gauge_pair()

        decomposition = decompose_bucket(
            team=self.team,
            metric_name="cache_size",
            aggregation="sum",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        assert decomposition.actual_value is not None
        assert decomposition.agrees == (decomposition.actual_value == decomposition.reference_value)

    def test_delta_counter_totals_every_increment_rather_than_the_last_one(self) -> None:
        # Each delta sample IS an increment, so keeping only the newest would drop
        # the rest of the bucket's traffic.
        seed_metric(
            team_id=self.team.pk,
            metric_name="requests_total",
            metric_type="sum",
            aggregation_temporality="delta",
            is_monotonic=True,
            labels={"pod": "a"},
            points=[(BUCKET, 3.0), (BUCKET + dt.timedelta(seconds=60), 4.0), (BUCKET + dt.timedelta(seconds=120), 5.0)],
        )

        decomposition = decompose_bucket(
            team=self.team,
            metric_name="requests_total",
            aggregation="sum",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        assert decomposition.temporality == "delta"
        assert decomposition.temporal_reducer == TemporalReducer.SUM_OVER_TIME
        assert decomposition.reference_value == 12.0

    def test_cumulative_counter_increase_diffs_within_the_series(self) -> None:
        seed_metric(
            team_id=self.team.pk,
            metric_name="bytes_total",
            metric_type="sum",
            aggregation_temporality="cumulative",
            is_monotonic=True,
            labels={"pod": "a"},
            points=[
                (BUCKET, 100.0),
                (BUCKET + dt.timedelta(seconds=60), 120.0),
                (BUCKET + dt.timedelta(seconds=120), 5.0),
            ],
        )

        decomposition = decompose_bucket(
            team=self.team,
            metric_name="bytes_total",
            aggregation="increase",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        assert decomposition.temporal_reducer == TemporalReducer.INCREASE
        # +20, then a restart whose post-reset reading is itself the increase.
        assert decomposition.reference_value == 25.0

    def test_lone_cumulative_sample_has_no_increase_on_either_side(self) -> None:
        seed_metric(
            team_id=self.team.pk,
            metric_name="bytes_total",
            metric_type="sum",
            aggregation_temporality="cumulative",
            is_monotonic=True,
            points=[(BUCKET, 100.0)],
        )

        decomposition = decompose_bucket(
            team=self.team,
            metric_name="bytes_total",
            aggregation="increase",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        # The sample's history is unknown, so both the reference and the chart
        # return no value — a 0 on either side would fabricate a flat counter.
        assert decomposition.reference_value is None
        assert decomposition.actual_value is None
        assert decomposition.agrees is True

    def test_empty_bucket_reports_no_series_rather_than_zero(self) -> None:
        decomposition = decompose_bucket(
            team=self.team,
            metric_name="nothing_here",
            aggregation="sum",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        assert decomposition.series_count == 0
        assert decomposition.reference_value is None

    def test_truncation_is_reported_rather_than_silently_dropping_series(self) -> None:
        for index in range(4):
            seed_metric(
                team_id=self.team.pk,
                metric_name="wide_metric",
                metric_type="gauge",
                aggregation_temporality="",
                labels={"pod": f"pod-{index}"},
                points=[(BUCKET, float(index))],
            )

        decomposition = decompose_bucket(
            team=self.team,
            metric_name="wide_metric",
            aggregation="sum",
            bucket_start=BUCKET,
            interval="minute_5",
            max_series=2,
        )

        # The totals stay whole; only the per-series listing is shortened.
        assert decomposition.series_count == 4
        assert len(decomposition.series) == 2
        assert decomposition.series_truncated is True
        assert decomposition.reference_value == 6.0


class TestExplainEndpoint(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def test_explain_returns_the_series_behind_a_point(self) -> None:
        seed_metric(
            team_id=self.team.pk,
            metric_name="cache_size",
            metric_type="gauge",
            aggregation_temporality="",
            labels={"pod": "a"},
            points=[(BUCKET, 5.0), (BUCKET + dt.timedelta(seconds=60), 11.0)],
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/explain/",
            {
                "query": {
                    "metricName": "cache_size",
                    "aggregation": "sum",
                    "bucketStart": BUCKET.isoformat(),
                    "interval": "minute_5",
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        decomposition = response.json()["decomposition"]
        assert decomposition["temporal_reducer"] == "last"
        assert decomposition["series_count"] == 1
        assert decomposition["reference_value"] == 11.0
        assert [sample["value"] for sample in decomposition["series"][0]["samples"]] == [5.0, 11.0]

    def test_rejects_an_interval_the_chart_could_not_have_used(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/metrics/explain/",
            {
                "query": {
                    "metricName": "cache_size",
                    "aggregation": "sum",
                    "bucketStart": BUCKET.isoformat(),
                    "interval": "fortnight",
                }
            },
            format="json",
        )

        assert response.status_code == 400


class TestCounterBoundary(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")
        # The predecessor sample sits in the previous bucket; the chart's window
        # function diffs across that edge, so the check has to as well.
        seed_metric(
            team_id=self.team.pk,
            metric_name="bytes_total",
            metric_type="sum",
            aggregation_temporality="cumulative",
            is_monotonic=True,
            labels={"pod": "a"},
            points=[
                (BUCKET - dt.timedelta(seconds=60), 100.0),
                (BUCKET + dt.timedelta(seconds=60), 120.0),
                (BUCKET + dt.timedelta(seconds=120), 140.0),
            ],
        )

    def test_increase_counts_the_rise_across_the_bucket_edge(self) -> None:
        decomposition = decompose_bucket(
            team=self.team,
            metric_name="bytes_total",
            aggregation="increase",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        # 100 -> 120 -> 140: the bucket rose by 40, of which 20 crosses the
        # edge. Read in isolation, both sides would drop that 20 and agree on
        # a value the chart never plotted.
        assert decomposition.reference_value == 40.0
        assert decomposition.actual_value == 40.0
        assert decomposition.agrees is True

    def test_agrees_when_the_predecessor_sits_further_back_than_one_bucket(self) -> None:
        # A minute chart of a series scraped every few minutes: the reference
        # reduction and the runner have to reach back over the same window, or
        # one of them finds a predecessor the other doesn't and the tab reports
        # a disagreement the chart never had.
        seed_metric(
            team_id=self.team.pk,
            metric_name="packets_total",
            metric_type="sum",
            aggregation_temporality="cumulative",
            is_monotonic=True,
            points=[
                (BUCKET - dt.timedelta(minutes=3), 100.0),
                (BUCKET + dt.timedelta(seconds=30), 120.0),
            ],
        )

        decomposition = decompose_bucket(
            team=self.team,
            metric_name="packets_total",
            aggregation="increase",
            bucket_start=BUCKET,
            interval="minute",
        )

        assert decomposition.reference_value == 20.0
        assert decomposition.actual_value == 20.0
        assert decomposition.agrees is True

    def test_rate_normalizes_the_boundary_increase_too(self) -> None:
        decomposition = decompose_bucket(
            team=self.team,
            metric_name="bytes_total",
            aggregation="rate",
            bucket_start=BUCKET,
            interval="minute_5",
        )

        assert decomposition.reference_value == pytest.approx(40.0 / 300.0)
        assert decomposition.agrees is True


class TestTruncatedBucket(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        sync_execute("TRUNCATE TABLE IF EXISTS metrics1")

    def test_truncated_read_reports_not_comparable_instead_of_a_verdict(self) -> None:
        seed_metric(
            team_id=self.team.pk,
            metric_name="cache_size",
            metric_type="gauge",
            aggregation_temporality="",
            labels={"pod": "a"},
            points=[(BUCKET + dt.timedelta(seconds=10 * i), float(i)) for i in range(6)],
        )

        with patch.object(diagnostics, "_MAX_ROWS_READ", 5):
            decomposition = decompose_bucket(
                team=self.team,
                metric_name="cache_size",
                aggregation="sum",
                bucket_start=BUCKET,
                interval="minute_5",
            )

        # The reference saw 5 of 6 rows while the runner saw all of them, so
        # any verdict would be an artifact of the unequal inputs.
        assert decomposition.rows_truncated is True
        assert decomposition.agrees is None
