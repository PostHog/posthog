from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import DateRange, PathsV2Filter, PathsV2Item, PathsV2Query, PathsV2Row, PathsV2StepSource

from posthog.test.test_journeys import journeys_for

from products.product_analytics.backend.hogql_queries.paths_v2.paths_v2_query_runner import PathsV2QueryRunner

DATE_RANGE = DateRange(date_from="2023-03-01", date_to="2023-03-31")


def _sources(*events: str) -> list[PathsV2StepSource]:
    return [PathsV2StepSource(event=event) for event in events]


def _timeline(
    distinct_id: str, *events: str, start: str = "2023-03-10 10:00:00", step_minutes: int = 5
) -> dict[str, list[dict[str, Any]]]:
    start_dt = datetime.fromisoformat(start)
    return {
        distinct_id: [
            {
                "event": event,
                "timestamp": (start_dt + timedelta(minutes=i * step_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for i, event in enumerate(events)
        ]
    }


class TestPathsV2QueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def test_open_mode_journey_grid(self):
        journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "b", "c", "d", "e"),
                **_timeline("p2", "a", "s", "b", "c", "d", "e"),
                **_timeline("p3", "a", "b", "c"),
                **_timeline("p4", "a"),
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c", "d", "e", "s"), maxRowsPerStep=10),
        )
        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results

        step_rows = [(step.stepIndex, step.rows, step.otherCount, step.dropOffCount) for step in results.steps]
        self.assertEqual(
            step_rows,
            [
                (0, [PathsV2Row(item=PathsV2Item(event="a", label=None), count=4)], 0, 1),
                (
                    1,
                    [
                        PathsV2Row(item=PathsV2Item(event="b", label=None), count=2),
                        PathsV2Row(item=PathsV2Item(event="s", label=None), count=1),
                    ],
                    0,
                    0,
                ),
                (
                    2,
                    [
                        PathsV2Row(item=PathsV2Item(event="c", label=None), count=2),
                        PathsV2Row(item=PathsV2Item(event="b", label=None), count=1),
                    ],
                    0,
                    1,
                ),
                (
                    3,
                    [
                        PathsV2Row(item=PathsV2Item(event="c", label=None), count=1),
                        PathsV2Row(item=PathsV2Item(event="d", label=None), count=1),
                    ],
                    0,
                    0,
                ),
                (
                    4,
                    [
                        PathsV2Row(item=PathsV2Item(event="d", label=None), count=1),
                        PathsV2Row(item=PathsV2Item(event="e", label=None), count=1),
                    ],
                    0,
                    1,
                ),
            ],
        )

        edge_rows = [(edge.stepIndex, edge.source, edge.target, edge.count) for edge in results.edges]
        self.assertEqual(
            edge_rows,
            [
                (0, PathsV2Item(event="a", label=None), PathsV2Item(event="b", label=None), 2),
                (0, PathsV2Item(event="a", label=None), PathsV2Item(event="s", label=None), 1),
                (1, PathsV2Item(event="b", label=None), PathsV2Item(event="c", label=None), 2),
                (1, PathsV2Item(event="s", label=None), PathsV2Item(event="b", label=None), 1),
                (2, PathsV2Item(event="b", label=None), PathsV2Item(event="c", label=None), 1),
                (2, PathsV2Item(event="c", label=None), PathsV2Item(event="d", label=None), 1),
                (3, PathsV2Item(event="c", label=None), PathsV2Item(event="d", label=None), 1),
                (3, PathsV2Item(event="d", label=None), PathsV2Item(event="e", label=None), 1),
            ],
        )
