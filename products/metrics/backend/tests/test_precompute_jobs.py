import time
import datetime as dt

import time_machine
from posthog.test.base import BaseTest

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.metrics.backend.facade.enums import AttributeScope, PrecomputedMetricKind
from products.metrics.backend.models import MetricPrecomputedChunk, MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import LabelRef, Leaf, get_or_create_precomputed_metric
from products.metrics.backend.precompute.fill import FINAL_AFTER
from products.metrics.backend.precompute.jobs import index_filled_days, index_team_filled_days

NOW = dt.datetime(2026, 11, 12, 12, 7, tzinfo=dt.UTC)
DAY = dt.timedelta(days=1)
MIDNIGHT = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)


@time_machine.travel(NOW, tick=False)
class TestIndexFilledDays(BaseTest):
    def _metric(self, kind: PrecomputedMetricKind, covered_from: dt.datetime) -> MetricPrecomputedMetric:
        metric = get_or_create_precomputed_metric(
            self.team.pk,
            Leaf(
                metric_name="llm_generations",
                metric_type=None,
                kind=kind,
                labels=(LabelRef("model", AttributeScope.AUTO),),
            ),
        )
        assert metric is not None
        metric.covered_from, metric.covered_to = covered_from, MIDNIGHT + dt.timedelta(hours=11)
        metric.save()
        hour = covered_from
        while hour < metric.covered_to:
            MetricPrecomputedChunk.objects.for_team(self.team.pk).create(
                team=self.team, precomputed_metric=metric, start=hour, series=[]
            )
            hour += dt.timedelta(hours=1)
        return metric

    def _jobs(self) -> list[tuple[dt.datetime, dt.datetime, str]]:
        return list(
            PreaggregationJob.objects.filter(team=self.team)
            .order_by("time_range_start")
            .values_list("time_range_start", "time_range_end", "status")
        )

    def test_indexes_only_whole_stored_days_and_reuses_them_on_the_next_pass(self):
        # Stored from 06:00 four days ago to 11:00 today: the partial first and last days are not indexed, and
        # the two settled days share a TTL but still get one job each.
        metric = self._metric(PrecomputedMetricKind.SUM_OVER_TIME, MIDNIGHT - 4 * DAY + dt.timedelta(hours=6))

        first = index_filled_days(self.team, metric, FINAL_AFTER)
        second = index_filled_days(self.team, metric, FINAL_AFTER)

        assert first is not None and second is not None
        assert [job.id for job in second] == [job.id for job in first]
        assert self._jobs() == [
            (MIDNIGHT - 3 * DAY, MIDNIGHT - 2 * DAY, PreaggregationJob.Status.READY),
            (MIDNIGHT - 2 * DAY, MIDNIGHT - DAY, PreaggregationJob.Status.READY),
            (MIDNIGHT - DAY, MIDNIGHT, PreaggregationJob.Status.READY),
        ]

    def test_a_settled_day_is_kept_while_yesterday_is_rebuilt_a_day_later(self):
        metric = self._metric(PrecomputedMetricKind.BUCKET_INCREASE, MIDNIGHT - 2 * DAY)
        first = index_filled_days(self.team, metric, FINAL_AFTER)
        assert first is not None
        settled, yesterday = first

        with time_machine.travel(MIDNIGHT + FINAL_AFTER + dt.timedelta(minutes=5), tick=False):
            metric.covered_to = MIDNIGHT + DAY
            metric.save()
            later = index_filled_days(self.team, metric, FINAL_AFTER)

        assert later is not None
        by_start = {job.time_range_start: job.id for job in later}
        assert by_start[settled.time_range_start] == settled.id
        assert by_start[yesterday.time_range_start] != yesterday.id
        assert not PreaggregationJob.objects.filter(id=yesterday.id).exists()

    def test_kinds_that_stay_on_postgres_are_not_indexed(self):
        self._metric(PrecomputedMetricKind.INCREASE, MIDNIGHT - 3 * DAY)

        index_team_filled_days(self.team, FINAL_AFTER, time.monotonic() + 60)

        assert self._jobs() == []
