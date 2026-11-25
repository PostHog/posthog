import datetime as dt
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, MetricsQuery, MetricsQueryClause, MetricsQueryGroupBy

from posthog.caching.insight_result import InsightResult
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner

from products.dashboards.backend.facade.api import insight_frames
from products.dashboards.backend.facade.contracts import Frame, FrameField, FrameMeta
from products.metrics.backend.facade.testing import seed_metric

NOW = "2026-09-19T12:00:00Z"


def _ms(iso: str) -> int:
    return int(dt.datetime.fromisoformat(iso).timestamp() * 1000)


class TestMetricsDashboardFrames(ClickhouseTestMixin, APIBaseTest):
    """Dashboard frames built from real metrics results. It lives here because it runs metrics queries."""

    def _frames(self, query: Any) -> list[Frame] | None:
        response = get_query_runner(query, self.team).run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        return insight_frames(query.model_dump(), InsightResult.from_response_dict(response.model_dump()))

    @time_machine.travel(NOW, tick=False)
    def test_metrics_series_become_one_frame_each(self) -> None:
        base = dt.datetime(2026, 9, 19, 11, 30, tzinfo=dt.UTC)
        for container, value in (("capture", 5.0), ("ingestion", 7.0)):
            seed_metric(
                team_id=self.team.pk,
                metric_name="queue_depth",
                metric_type="gauge",
                unit="By",
                points=[(base + dt.timedelta(minutes=minute), value) for minute in (0, 1, 3)],
                labels={"container": container},
            )

        frames = self._frames(
            MetricsQuery(
                clauses=[
                    MetricsQueryClause(
                        name="a",
                        metricName="queue_depth",
                        aggregation="sum",
                        groupBy=[MetricsQueryGroupBy(key="container")],
                    )
                ],
                dateRange=DateRange(date_from="2026-09-19T11:00:00Z", date_to="2026-09-19T12:00:00Z"),
            )
        )

        assert frames is not None
        times = [_ms(f"2026-09-19T11:3{minute}:00+00:00") for minute in (0, 1, 3)]
        meta = FrameMeta(
            interval="minute",
            date_from=dt.datetime(2026, 9, 19, 11, tzinfo=dt.UTC),
            date_to=dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC),
        )
        assert sorted(frames, key=lambda frame: frame.name) == [
            Frame(
                name=f"container={container}",
                labels={"container": container},
                fields=[
                    FrameField(name="time", type="time", values=times),
                    FrameField(name="value", type="number", values=[value] * 3, unit="By"),
                ],
                meta=meta,
            )
            for container, value in (("capture", 5.0), ("ingestion", 7.0))
        ]
