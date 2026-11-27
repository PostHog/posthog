import time_machine
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    PropertyMathType,
    PropertyOperator,
    WebVitalsMetric,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownResult,
    WebVitalsPathBreakdownResultItem,
)

from products.cohorts.backend.models.cohort import Cohort
from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner


@snapshot_clickhouse_queries
class TestWebVitalsPathBreakdownQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def _create_events(self, data, metric: WebVitalsMetric = WebVitalsMetric.INP):
        for distinct_id, timestamps in data:
            for timestamp, path, value in timestamps:
                _create_event(
                    team=self.team,
                    event="$web_vitals",
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties={
                        f"$web_vitals_{metric.value}_value": value,
                        "$pathname": path,
                    },
                )

        flush_persons_and_events()

    def _run_web_vitals_path_breakdown_query(
        self,
        date_from,
        date_to,
        thresholds: tuple[float, float],
        metric: WebVitalsMetric = WebVitalsMetric.INP,
        percentile: PropertyMathType = PropertyMathType.P75,
        properties=None,
        filter_test_accounts: bool = False,
        min_samples: int | None = None,
    ):
        with time_machine.travel(self.QUERY_TIMESTAMP, tick=False):
            query = WebVitalsPathBreakdownQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                metric=metric,
                percentile=percentile,
                thresholds=thresholds,
                properties=properties or [],
                filterTestAccounts=filter_test_accounts,
                minSamples=min_samples,
            )

            runner = WebVitalsPathBreakdownQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual([WebVitalsPathBreakdownResult(good=[], needs_improvements=[], poor=[])], results)

    def test_no_data_for_different_metric(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-08", "/path1", 100),
                        ("2025-01-08", "/path2", 200),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.LCP,
            PropertyMathType.P75,
        ).results

        self.assertEqual([WebVitalsPathBreakdownResult(good=[], needs_improvements=[], poor=[])], results)

    def test_no_data_for_different_period(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2024-01-12", "/path1", 100),
                        ("2024-01-12", "/path2", 200),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual([WebVitalsPathBreakdownResult(good=[], needs_improvements=[], poor=[])], results)

    def test_data_correctly_split_between_bands(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-05", "/path_outside_before_period", 50),
                        ("2025-01-10", "/path1", 50),
                        ("2025-01-10", "/path2", 100),
                        ("2025-01-10", "/path3", 150),
                        ("2025-01-10", "/path4", 200),
                        ("2025-01-10", "/path5", 250),
                        ("2025-01-10", "/path6", 300),
                        ("2025-01-18", "/path_outside_after_period", 50),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[
                        WebVitalsPathBreakdownResultItem(path="/path2", value=100, count=1),
                        WebVitalsPathBreakdownResultItem(path="/path1", value=50, count=1),
                    ],
                    needs_improvements=[
                        WebVitalsPathBreakdownResultItem(path="/path4", value=200, count=1),
                        WebVitalsPathBreakdownResultItem(path="/path3", value=150, count=1),
                    ],
                    poor=[
                        WebVitalsPathBreakdownResultItem(path="/path6", value=300, count=1),
                        WebVitalsPathBreakdownResultItem(path="/path5", value=250, count=1),
                    ],
                )
            ],
            results,
        )

    def test_limit_of_20_paths_keeps_the_worst_of_each_band(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", f"/path/a/{idx}", 50 + idx)
                        for idx in range(30)  # Creating 30, but should be limited to 20
                    ],
                ),
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", f"/path/b/{idx}", 150 + idx)
                        for idx in range(25)  # Creating 25, but should be limited to 20
                    ],
                ),
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", f"/path/c/{idx}", 499)
                        for idx in range(5)  # Creating only 5, return these 5
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            WebVitalsMetric.INP,
            PropertyMathType.P75,
        ).results

        self.assertEqual(20, len(results[0].good))
        self.assertEqual(20, len(results[0].needs_improvements))
        self.assertEqual(5, len(results[0].poor))
        # Worst first: the cap drops the fastest pages, not the slowest ones.
        self.assertEqual([item.value for item in results[0].good], [float(v) for v in range(79, 59, -1)])
        self.assertEqual(
            [item.value for item in results[0].needs_improvements], [float(v) for v in range(174, 154, -1)]
        )

    def test_min_samples_drops_thinly_sampled_pages(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/one-slow-load", 900),
                        *[("2025-01-10", "/busy", 250 + idx) for idx in range(4)],
                        ("2025-01-10", "/busy", None),
                        *[("2025-01-10", "/fast", 40) for _ in range(3)],
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        unfloored = self._run_web_vitals_path_breakdown_query("2025-01-08", "2025-01-15", (100, 200)).results
        floored = self._run_web_vitals_path_breakdown_query(
            "2025-01-08", "2025-01-15", (100, 200), min_samples=3
        ).results

        self.assertEqual(
            [
                WebVitalsPathBreakdownResultItem(path="/one-slow-load", value=900, count=1),
                WebVitalsPathBreakdownResultItem(path="/busy", value=252.25, count=4),
            ],
            unfloored[0].poor,
        )
        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[WebVitalsPathBreakdownResultItem(path="/fast", value=40, count=3)],
                    needs_improvements=[],
                    poor=[WebVitalsPathBreakdownResultItem(path="/busy", value=252.25, count=4)],
                )
            ],
            floored,
        )

    def test_percentile_is_applied(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                        ("2025-01-10", "/path1", 100),
                        ("2025-01-10", "/path1", 150),
                        ("2025-01-10", "/path1", 200),
                        ("2025-01-10", "/path1", 250),
                        ("2025-01-10", "/path1", 300),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        for percentile, value in [
            (PropertyMathType.P75, 237.5),
            (PropertyMathType.P90, 275.0),
            (PropertyMathType.P99, 297.5),
        ]:
            results = self._run_web_vitals_path_breakdown_query(
                "2025-01-08",
                "2025-01-15",
                (100, 200),
                WebVitalsMetric.INP,
                percentile,
            ).results

            self.assertEqual(
                [
                    WebVitalsPathBreakdownResult(
                        good=[],
                        needs_improvements=[],
                        poor=[WebVitalsPathBreakdownResultItem(path="/path1", value=value, count=6)],
                    )
                ],
                results,
            )

    def test_properties_are_applied(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/path1", 50),
                        ("2025-01-10", "/path2", 50),  # Won't be included because of the property filter below
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        results = self._run_web_vitals_path_breakdown_query(
            "2025-01-08",
            "2025-01-15",
            (100, 200),
            properties=[EventPropertyFilter(key="$pathname", operator=PropertyOperator.EXACT, value="/path1")],
        ).results

        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[WebVitalsPathBreakdownResultItem(path="/path1", value=50, count=1)],
                    needs_improvements=[],
                    poor=[],
                )
            ],
            results,
        )

    def test_test_account_cohort_filter_is_applied(self):
        _create_person(team_id=self.team.pk, distinct_ids=["visitor"])
        _create_person(team_id=self.team.pk, distinct_ids=["scanner"])
        self._create_events(
            [
                ("visitor", [("2025-01-10", "/path1", 50)]),
                ("scanner", [("2025-01-10", "/path1", 500), ("2025-01-10", "/path2", 500)]),
            ],
            WebVitalsMetric.INP,
        )
        cohort = Cohort.objects.create(team=self.team, name="scanners", groups=[], is_static=True)
        cohort.insert_users_by_list(["scanner"])
        self.team.test_account_filters = [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "not_in"}]
        self.team.save()

        unfiltered = self._run_web_vitals_path_breakdown_query("2025-01-08", "2025-01-15", (100, 200)).results
        filtered = self._run_web_vitals_path_breakdown_query(
            "2025-01-08", "2025-01-15", (100, 200), filter_test_accounts=True
        ).results

        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[],
                    needs_improvements=[],
                    poor=[
                        WebVitalsPathBreakdownResultItem(path="/path2", value=500, count=1),
                        WebVitalsPathBreakdownResultItem(path="/path1", value=387.5, count=2),
                    ],
                )
            ],
            unfiltered,
        )
        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[WebVitalsPathBreakdownResultItem(path="/path1", value=50, count=1)],
                    needs_improvements=[],
                    poor=[],
                )
            ],
            filtered,
        )

    def test_path_cleaning_filters(self):
        self._create_events(
            [
                (
                    "distinct_id_1",
                    [
                        ("2025-01-10", "/cleaned/123", 50),
                        ("2025-01-10", "/cleaned/456", 50),
                        ("2025-01-10", "/not-cleaned", 150),
                    ],
                ),
            ],
            WebVitalsMetric.INP,
        )

        self.team.path_cleaning_filters = [
            {"regex": "\\/cleaned\\/\\d+", "alias": "/cleaned/<id>"},
        ]
        self.team.save()

        with time_machine.travel(self.QUERY_TIMESTAMP, tick=False):
            query = WebVitalsPathBreakdownQuery(
                dateRange=DateRange(date_from="2025-01-08", date_to="2025-01-15"),
                metric=WebVitalsMetric.INP,
                percentile=PropertyMathType.P75,
                thresholds=(100, 200),
                properties=[],
                doPathCleaning=True,
            )

            runner = WebVitalsPathBreakdownQueryRunner(team=self.team, query=query)
            results = runner.calculate().results

        self.assertEqual(
            [
                WebVitalsPathBreakdownResult(
                    good=[WebVitalsPathBreakdownResultItem(path="/cleaned/<id>", value=50, count=2)],
                    needs_improvements=[WebVitalsPathBreakdownResultItem(path="/not-cleaned", value=150, count=1)],
                    poor=[],
                )
            ],
            results,
        )
