from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    DateRange,
    FunnelConversionWindowTimeUnit,
    PathCleaningFilter,
    PathsV2Anchor,
    PathsV2AnchorType,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    PathsV2Row,
    PathsV2StepSource,
)

from posthog.hogql.query import execute_hogql_query

from posthog.test.test_journeys import journeys_for

from products.product_analytics.backend.hogql_queries.paths_v2.path_item import resolve_step_sources
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


def _item(event: str, label: str | None = None) -> PathsV2Item:
    return PathsV2Item(event=event, label=label)


def _row(event: str, count: float, label: str | None = None) -> PathsV2Row:
    return PathsV2Row(item=_item(event, label), count=count)


def _edge(
    step_index: int, source: PathsV2Item | None, target: PathsV2Item | None, count: float
) -> tuple[int, PathsV2Item | None, PathsV2Item | None, float]:
    return (step_index, source, target, count)


class TestPathsV2FilterConstraints(SimpleTestCase):
    @parameterized.expand(
        [
            ("max_steps_below_min", {"maxSteps": 1}),
            ("max_steps_above_max", {"maxSteps": 21}),
            ("max_rows_below_min", {"maxRowsPerStep": 0}),
            ("max_rows_above_max", {"maxRowsPerStep": 11}),
            ("step_sources_empty", {"stepSources": []}),
            ("step_sources_above_max", {"stepSources": [PathsV2StepSource(event=f"e{i}") for i in range(21)]}),
            ("excluded_items_above_max", {"excludedItems": [PathsV2Item(event=f"e{i}") for i in range(101)]}),
        ]
    )
    def test_out_of_bounds_config_rejects(self, _name: str, kwargs: dict[str, Any]) -> None:
        with self.assertRaises(PydanticValidationError):
            PathsV2Filter(**kwargs)

    def test_defaults(self) -> None:
        paths_filter = PathsV2Filter()
        self.assertEqual(paths_filter.maxSteps, 5)
        self.assertEqual(paths_filter.maxRowsPerStep, 3)
        self.assertEqual(paths_filter.gapInterval, 30)
        self.assertEqual(paths_filter.gapIntervalUnit, FunnelConversionWindowTimeUnit.MINUTE)
        self.assertEqual(paths_filter.collapseRepeats, True)
        self.assertEqual(paths_filter.conversionWindowInterval, 30)
        self.assertEqual(paths_filter.conversionWindowIntervalUnit, FunnelConversionWindowTimeUnit.MINUTE)
        self.assertEqual(paths_filter.applyTeamPathCleaning, True)
        self.assertIsNone(paths_filter.stepSources)
        self.assertIsNone(paths_filter.anchor)
        self.assertIsNone(paths_filter.excludedItems)
        self.assertIsNone(paths_filter.localPathCleaningFilters)

    def test_absent_step_sources_resolve_to_pageviews_preset(self) -> None:
        # Saved queries may omit stepSources; the frontend preset picker mirrors this default,
        # so a backend change here would silently relabel them.
        self.assertEqual(
            resolve_step_sources(PathsV2Query()),
            [PathsV2StepSource(event="$pageview", namingProperty="$pathname")],
        )


class TestPathsV2Validation(ClickhouseTestMixin, APIBaseTest):
    def _runner(self, paths_filter: PathsV2Filter) -> PathsV2QueryRunner:
        return PathsV2QueryRunner(query=PathsV2Query(pathsV2Filter=paths_filter), team=self.team)

    @parameterized.expand(
        [
            ("second_above_max", 3601, FunnelConversionWindowTimeUnit.SECOND),
            ("minute_above_max", 1441, FunnelConversionWindowTimeUnit.MINUTE),
            ("hour_above_max", 25, FunnelConversionWindowTimeUnit.HOUR),
            ("day_above_max", 366, FunnelConversionWindowTimeUnit.DAY),
            ("week_above_max", 54, FunnelConversionWindowTimeUnit.WEEK),
            ("month_above_max", 13, FunnelConversionWindowTimeUnit.MONTH),
            ("minute_below_min", 0, FunnelConversionWindowTimeUnit.MINUTE),
        ]
    )
    def test_out_of_bounds_gap_rejects(self, _name: str, interval: int, unit: FunnelConversionWindowTimeUnit) -> None:
        runner = self._runner(PathsV2Filter(gapInterval=interval, gapIntervalUnit=unit))
        with self.assertRaisesMessage(ValidationError, "gapInterval"):
            runner.validate()

    @parameterized.expand(
        [
            ("second_max", 3600, FunnelConversionWindowTimeUnit.SECOND),
            ("minute_max", 1440, FunnelConversionWindowTimeUnit.MINUTE),
            ("day_min", 1, FunnelConversionWindowTimeUnit.DAY),
        ]
    )
    def test_gap_bounds_are_inclusive(self, _name: str, interval: int, unit: FunnelConversionWindowTimeUnit) -> None:
        self._runner(PathsV2Filter(gapInterval=interval, gapIntervalUnit=unit)).validate()

    @parameterized.expand(
        [
            ("duplicate_events", _sources("a", "a")),
            ("empty_event", _sources("")),
        ]
    )
    def test_invalid_step_sources_reject(self, _name: str, sources: list[PathsV2StepSource]) -> None:
        runner = self._runner(PathsV2Filter(stepSources=sources))
        with self.assertRaisesMessage(ValidationError, "stepSources"):
            runner.validate()

    @parameterized.expand(
        [
            ("second_above_max", 3601, FunnelConversionWindowTimeUnit.SECOND),
            ("minute_above_max", 1441, FunnelConversionWindowTimeUnit.MINUTE),
            ("day_above_max", 366, FunnelConversionWindowTimeUnit.DAY),
            ("minute_below_min", 0, FunnelConversionWindowTimeUnit.MINUTE),
        ]
    )
    def test_out_of_bounds_window_rejects(
        self, _name: str, interval: int, unit: FunnelConversionWindowTimeUnit
    ) -> None:
        runner = self._runner(PathsV2Filter(conversionWindowInterval=interval, conversionWindowIntervalUnit=unit))
        with self.assertRaisesMessage(ValidationError, "conversionWindowInterval"):
            runner.validate()

    def test_window_bounds_are_inclusive(self) -> None:
        self._runner(
            PathsV2Filter(
                conversionWindowInterval=1440, conversionWindowIntervalUnit=FunnelConversionWindowTimeUnit.MINUTE
            )
        ).validate()

    def test_anchor_event_must_be_a_step_source(self) -> None:
        runner = self._runner(
            PathsV2Filter(
                stepSources=_sources("a", "b"),
                anchor=PathsV2Anchor(type=PathsV2AnchorType.START, item=PathsV2Item(event="missing")),
            )
        )
        with self.assertRaisesMessage(ValidationError, "must be one of the step sources"):
            runner.validate()

    @parameterized.expand(
        [
            ("event_only", PathsV2Item(event="a")),
            # A spurious label on a source without a naming property must not hide that the query
            # anchors on (event, ''), which is the excluded item.
            ("spurious_anchor_label", PathsV2Item(event="a", label="x")),
        ]
    )
    def test_excluding_the_anchor_rejects(self, _name: str, anchor_item: PathsV2Item) -> None:
        runner = self._runner(
            PathsV2Filter(
                stepSources=_sources("a", "b"),
                anchor=PathsV2Anchor(type=PathsV2AnchorType.START, item=anchor_item),
                excludedItems=[PathsV2Item(event="a")],
            )
        )
        with self.assertRaisesMessage(ValidationError, "anchor"):
            runner.validate()

    @parameterized.expand(
        [
            # Editing step sources must not invalidate a saved exclude list; this exclusion is inert.
            ("non_source_event", _sources("a"), [PathsV2Item(event="gone")]),
            # A label-less exclusion of a naming-property source pins the item whose property is missing.
            (
                "label_less_on_naming_source",
                [PathsV2StepSource(event="$pageview", namingProperty="$pathname")],
                [PathsV2Item(event="$pageview")],
            ),
        ]
    )
    def test_permissive_exclusions_are_allowed(
        self, _name: str, sources: list[PathsV2StepSource], excluded: list[PathsV2Item]
    ) -> None:
        self._runner(PathsV2Filter(stepSources=sources, excludedItems=excluded)).validate()

    def test_anchor_on_naming_property_source_needs_a_label(self) -> None:
        runner = self._runner(
            PathsV2Filter(
                stepSources=[PathsV2StepSource(event="$pageview", namingProperty="$pathname")],
                anchor=PathsV2Anchor(type=PathsV2AnchorType.START, item=PathsV2Item(event="$pageview")),
            )
        )
        with self.assertRaisesMessage(ValidationError, "needs a label"):
            runner.validate()


class TestPathsV2QueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _run(self, query: PathsV2Query) -> Any:
        return PathsV2QueryRunner(query=query, team=self.team).calculate().results

    def _steps(self, results: Any) -> list[tuple[int, list[PathsV2Row], float, float]]:
        return [(step.stepIndex, step.rows, step.otherCount, step.dropOffCount) for step in results.steps]

    def _edges(self, results: Any) -> list[tuple[int, PathsV2Item | None, PathsV2Item | None, float]]:
        return [(edge.stepIndex, edge.source, edge.target, edge.count) for edge in results.edges]

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
        results = self._run(query)

        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("a", 4)], 0, 1),
                (1, [_row("b", 2), _row("s", 1)], 0, 0),
                (2, [_row("c", 2), _row("b", 1)], 0, 1),
                (3, [_row("c", 1), _row("d", 1)], 0, 0),
                (4, [_row("d", 1), _row("e", 1)], 0, 1),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [
                _edge(0, _item("a"), _item("b"), 2),
                _edge(0, _item("a"), _item("s"), 1),
                _edge(1, _item("b"), _item("c"), 2),
                _edge(1, _item("s"), _item("b"), 1),
                _edge(2, _item("b"), _item("c"), 1),
                _edge(2, _item("c"), _item("d"), 1),
                _edge(3, _item("c"), _item("d"), 1),
                _edge(3, _item("d"), _item("e"), 1),
            ],
        )

    @parameterized.expand(
        [
            ("gap_of_exactly_g_stays_together", "2023-03-10 10:30:00", True),
            ("gap_above_g_splits", "2023-03-10 10:30:01", False),
        ]
    )
    def test_gap_boundary(self, _name: str, second_timestamp: str, same_journey: bool):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "a", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "b", "timestamp": second_timestamp},
                ]
            },
        )

        query = PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b")))
        results = self._run(query)

        if same_journey:
            self.assertEqual(
                self._steps(results),
                [(0, [_row("a", 1)], 0, 0), (1, [_row("b", 1)], 0, 1)],
            )
            self.assertEqual(self._edges(results), [_edge(0, _item("a"), _item("b"), 1)])
        else:
            # Two one-item journeys of the same actor: both start at the first step and both end
            # there, so the actor still counts once per element.
            self.assertEqual(
                self._steps(results),
                [(0, [_row("a", 1), _row("b", 1)], 0, 1)],
            )
            self.assertEqual(self._edges(results), [])

    @parameterized.expand(
        [
            ("collapse_on", True),
            ("collapse_off", False),
        ]
    )
    def test_collapse_repeats(self, _name: str, collapse: bool):
        journeys_for(team=self.team, events_by_person=_timeline("p1", "a", "a", "b"))

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b"), collapseRepeats=collapse),
        )
        results = self._run(query)

        if collapse:
            self.assertEqual(
                self._steps(results),
                [(0, [_row("a", 1)], 0, 0), (1, [_row("b", 1)], 0, 1)],
            )
            self.assertEqual(self._edges(results), [_edge(0, _item("a"), _item("b"), 1)])
        else:
            self.assertEqual(
                self._steps(results),
                [(0, [_row("a", 1)], 0, 0), (1, [_row("a", 1)], 0, 0), (2, [_row("b", 1)], 0, 1)],
            )
            self.assertEqual(
                self._edges(results),
                [_edge(0, _item("a"), _item("a"), 1), _edge(1, _item("a"), _item("b"), 1)],
            )

    def test_unique_actor_dedup_across_journeys(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    *_timeline("p1", "a", "b")["p1"],
                    *_timeline("p1", "a", "c", start="2023-03-10 14:00:00")["p1"],
                ],
                **_timeline("p2", "a", "b"),
            },
        )

        query = PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c")))
        results = self._run(query)

        # p1 touches (step 0, a) with both journeys but counts once; the edge a -> b counts p1 once
        # alongside p2. Both of p1's journeys end at the second step, deduped into one drop-off.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("a", 2)], 0, 0),
                (1, [_row("b", 2), _row("c", 1)], 0, 2),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [_edge(0, _item("a"), _item("b"), 2), _edge(0, _item("a"), _item("c"), 1)],
        )

    def test_other_bucketing_dedups_actors(self):
        journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "x", "m1"),
                "p2": [
                    *_timeline("p2", "x", "m2")["p2"],
                    *_timeline("p2", "x", "m3", start="2023-03-10 14:00:00")["p2"],
                ],
                **_timeline("p3", "x", "m1"),
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("x", "m1", "m2", "m3"), maxRowsPerStep=1),
        )
        results = self._run(query)

        # m2 and m3 fall beyond the top row at the second step. p2 touches both, so the other row
        # counts p2 once, and so does the edge from x into the other bucket.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("x", 3)], 0, 0),
                (1, [_row("m1", 2)], 1, 3),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [
                _edge(0, _item("x"), _item("m1"), 2),
                _edge(0, _item("x"), None, 1),
            ],
        )

    def test_date_range_clips_journeys(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "a", "timestamp": "2023-02-28 23:50:00"},
                    {"event": "b", "timestamp": "2023-03-01 00:05:00"},
                    {"event": "c", "timestamp": "2023-03-01 00:10:00"},
                ]
            },
        )

        query = PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c")))
        results = self._run(query)

        # The pre-range event is invisible, so the journey starts at its first in-range item.
        self.assertEqual(
            self._steps(results),
            [(0, [_row("b", 1)], 0, 0), (1, [_row("c", 1)], 0, 1)],
        )
        self.assertEqual(self._edges(results), [_edge(0, _item("b"), _item("c"), 1)])

    def test_naming_property_sources(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "signup", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "stage changed", "timestamp": "2023-03-10 10:05:00", "properties": {"stage": "lead"}},
                    {"event": "stage changed", "timestamp": "2023-03-10 10:10:00", "properties": {"stage": "won"}},
                ],
                "p2": [
                    {"event": "signup", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "stage changed", "timestamp": "2023-03-10 10:05:00"},
                ],
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(
                stepSources=[
                    PathsV2StepSource(event="signup"),
                    PathsV2StepSource(event="stage changed", namingProperty="stage"),
                ]
            ),
        )
        results = self._run(query)

        # Consecutive events of the same source with different labels are distinct items; a missing
        # naming property labels the item with an empty string; sources without a naming property
        # have no label at all.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("signup", 2)], 0, 0),
                (1, [_row("stage changed", 1, label=""), _row("stage changed", 1, label="lead")], 0, 1),
                (2, [_row("stage changed", 1, label="won")], 0, 1),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [
                _edge(0, _item("signup"), _item("stage changed", label=""), 1),
                _edge(0, _item("signup"), _item("stage changed", label="lead"), 1),
                _edge(1, _item("stage changed", label="lead"), _item("stage changed", label="won"), 1),
            ],
        )

    def test_path_cleaning_merges_items(self):
        self.team.path_cleaning_filters = [{"alias": "/item/<id>", "regex": r"/item/\d+"}]
        self.team.save()
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "$pageview", "timestamp": "2023-03-10 10:00:00", "properties": {"$pathname": "/item/1"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:05:00", "properties": {"$pathname": "/item/2"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:10:00", "properties": {"$pathname": "/about"}},
                ]
            },
        )

        query = PathsV2Query(dateRange=DATE_RANGE)
        results = self._run(query)

        # Cleaning applies before collapse, so the two /item/<id> pageviews merge into one item.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("$pageview", 1, label="/item/<id>")], 0, 0),
                (1, [_row("$pageview", 1, label="/about")], 0, 1),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [_edge(0, _item("$pageview", label="/item/<id>"), _item("$pageview", label="/about"), 1)],
        )

    def test_excluded_items_drop_from_universe(self) -> None:
        journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "x", "b"),
                **_timeline("p2", "x"),
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "x"), excludedItems=[_item("x")]),
        )
        results = self._run(query)

        # Excluded events vanish from the universe before journeys are built: p1's journey bridges
        # a -> b instead of splitting around x, and p2 has no journey at all. A display-level filter
        # would drop the a -> x and x -> b edges without producing the bridged a -> b edge.
        self.assertEqual(
            self._steps(results),
            [(0, [_row("a", 1)], 0, 0), (1, [_row("b", 1)], 0, 1)],
        )
        self.assertEqual(self._edges(results), [_edge(0, _item("a"), _item("b"), 1)])

    def test_excluded_item_matches_the_label_not_the_event(self) -> None:
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "$pageview", "timestamp": "2023-03-10 10:00:00", "properties": {"$pathname": "/home"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:05:00", "properties": {"$pathname": "/login"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:10:00", "properties": {"$pathname": "/app"}},
                ]
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(excludedItems=[_item("$pageview", label="/login")]),
        )
        results = self._run(query)

        # Only the (event, label) item is excluded; the source's other items stay.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("$pageview", 1, label="/home")], 0, 0),
                (1, [_row("$pageview", 1, label="/app")], 0, 1),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [_edge(0, _item("$pageview", label="/home"), _item("$pageview", label="/app"), 1)],
        )

    def test_local_path_cleaning_applies_after_team_rules(self) -> None:
        self.team.path_cleaning_filters = [{"alias": "/item/:id", "regex": r"/item/\d+"}]
        self.team.save()
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "$pageview", "timestamp": "2023-03-10 10:00:00", "properties": {"$pathname": "/item/1"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:05:00", "properties": {"$pathname": "/about"}},
                ]
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(localPathCleaningFilters=[PathCleaningFilter(alias="<id>", regex=":id")]),
        )
        results = self._run(query)

        # The local rule's regex only matches the team rule's output, so this label proves both that
        # local rules apply and that they run after the team's.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("$pageview", 1, label="/item/<id>")], 0, 0),
                (1, [_row("$pageview", 1, label="/about")], 0, 1),
            ],
        )

    def test_team_path_cleaning_can_be_disabled(self) -> None:
        self.team.path_cleaning_filters = [{"alias": "/item/<id>", "regex": r"/item/\d+"}]
        self.team.save()
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "$pageview", "timestamp": "2023-03-10 10:00:00", "properties": {"$pathname": "/item/1"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:05:00", "properties": {"$pathname": "/item/2"}},
                ]
            },
        )

        query = PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=PathsV2Filter(applyTeamPathCleaning=False))
        results = self._run(query)

        # With the team's rules off, the raw URLs stay distinct items instead of merging.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("$pageview", 1, label="/item/1")], 0, 0),
                (1, [_row("$pageview", 1, label="/item/2")], 0, 1),
            ],
        )

    def test_null_team_path_cleaning_filters(self) -> None:
        # The nullable JSONField's None must behave like "no rules", not crash rule resolution.
        self.team.path_cleaning_filters = None
        self.team.save()
        journeys_for(team=self.team, events_by_person=_timeline("p1", "a"))

        query = PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=PathsV2Filter(stepSources=_sources("a")))

        self.assertEqual(self._steps(self._run(query)), [(0, [_row("a", 1)], 0, 1)])

    def test_max_steps_trims_journeys(self):
        journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "b", "c", "d", "e"),
                **_timeline("p2", "a", "b", "c"),
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c", "d", "e"), maxSteps=3),
        )
        results = self._run(query)

        # p1's journey continues beyond the grid: its items past the third step are invisible and
        # it never counts as a drop-off. p2's journey genuinely ends at the third step.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("a", 2)], 0, 0),
                (1, [_row("b", 2)], 0, 0),
                (2, [_row("c", 2)], 0, 1),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [_edge(0, _item("a"), _item("b"), 2), _edge(1, _item("b"), _item("c"), 2)],
        )

    @snapshot_clickhouse_queries
    def test_default_pageview_preset_snapshot(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "$pageview", "timestamp": "2023-03-10 10:00:00", "properties": {"$pathname": "/"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:05:00", "properties": {"$pathname": "/pricing"}},
                    {"event": "other event", "timestamp": "2023-03-10 10:07:00"},
                ]
            },
        )

        results = self._run(PathsV2Query(dateRange=DATE_RANGE))

        # Events outside the step sources are invisible and do not break adjacency.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("$pageview", 1, label="/")], 0, 0),
                (1, [_row("$pageview", 1, label="/pricing")], 0, 1),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [_edge(0, _item("$pageview", label="/"), _item("$pageview", label="/pricing"), 1)],
        )

    def test_executable_via_query_api(self):
        journeys_for(team=self.team, events_by_person=_timeline("p1", "a", "b"))

        response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "PathsV2Query",
                    "dateRange": {"date_from": "2023-03-01", "date_to": "2023-03-31"},
                    "pathsV2Filter": {"stepSources": [{"event": "a"}, {"event": "b"}]},
                }
            },
        )

        self.assertEqual(response.status_code, 200, response.json())
        results = response.json()["results"]
        self.assertEqual(len(results["steps"]), 2)
        self.assertEqual(len(results["edges"]), 1)

    def test_query_api_rejects_out_of_bounds_config(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {"query": {"kind": "PathsV2Query", "pathsV2Filter": {"maxSteps": 21}}},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("maxSteps", str(response.json()))

    def test_elements_per_actor_stage(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    *_timeline("p1", "a", "a", "b")["p1"],
                    *_timeline("p1", "c", start="2023-03-10 14:00:00")["p1"],
                ]
            },
        )

        runner = PathsV2QueryRunner(
            query=PathsV2Query(dateRange=DATE_RANGE, pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c"))),
            team=self.team,
        )
        response = execute_hogql_query(
            query=runner._elements_per_actor_query(),
            team=self.team,
        )

        self.assertEqual(len(response.results), 1)
        assert response.columns is not None
        elements = response.results[0][response.columns.index("elements")]
        self.assertCountEqual(
            elements,
            [
                # first journey, collapsed to [a, b]
                ("node", 1, ("a", ""), ("", "")),
                ("node", 2, ("b", ""), ("", "")),
                ("edge", 1, ("a", ""), ("b", "")),
                ("dropoff", 2, ("", ""), ("", "")),
                # second journey, split off by the four-hour gap
                ("node", 1, ("c", ""), ("", "")),
                ("dropoff", 1, ("", ""), ("", "")),
            ],
        )


def _anchor(event: str, anchor_type: PathsV2AnchorType = PathsV2AnchorType.START) -> PathsV2Anchor:
    return PathsV2Anchor(type=anchor_type, item=PathsV2Item(event=event))


def _prefix(items: list[tuple[str, str | None]], count: float) -> tuple[tuple[tuple[str, str | None], ...], float]:
    return (tuple(items), count)


class TestPathsV2AnchoredMode(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _run(self, query: PathsV2Query) -> Any:
        return PathsV2QueryRunner(query=query, team=self.team).calculate().results

    def _steps(self, results: Any) -> list[tuple[int, list[PathsV2Row], float, float]]:
        return [(step.stepIndex, step.rows, step.otherCount, step.dropOffCount) for step in results.steps]

    def _edges(self, results: Any) -> list[tuple[int, PathsV2Item | None, PathsV2Item | None, float]]:
        return [(edge.stepIndex, edge.source, edge.target, edge.count) for edge in results.edges]

    def _prefixes(self, results: Any) -> set[tuple[tuple[tuple[str, str | None], ...], float]]:
        return {(tuple((item.event, item.label) for item in prefix.items), prefix.count) for prefix in results.prefixes}

    def test_anchored_start_journey_grid(self):
        journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "b", "c"),
                **_timeline("p2", "a", "b", "d"),
                **_timeline("p3", "a", "x"),
                # z precedes the anchor, so the prefilter drops it and the sequence starts at a.
                **_timeline("p4", "z", "a", "b"),
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(
                stepSources=_sources("a", "b", "c", "d", "x", "z"), anchor=_anchor("a"), maxRowsPerStep=10
            ),
        )
        results = self._run(query)

        # One sequence per actor from the anchor: p1 [a,b,c], p2 [a,b,d], p3 [a,x], p4 [a,b]. The anchor
        # is the single 100% node; drop-offs count actors whose sequence ends at that step.
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("a", 4)], 0, 0),
                (1, [_row("b", 3), _row("x", 1)], 0, 2),
                (2, [_row("c", 1), _row("d", 1)], 0, 2),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [
                _edge(0, _item("a"), _item("b"), 3),
                _edge(0, _item("a"), _item("x"), 1),
                _edge(1, _item("b"), _item("c"), 1),
                _edge(1, _item("b"), _item("d"), 1),
            ],
        )
        # Prefix counts nest into the chain tree the hover preview walks.
        self.assertEqual(
            self._prefixes(results),
            {
                _prefix([("a", None)], 4),
                _prefix([("a", None), ("b", None)], 3),
                _prefix([("a", None), ("x", None)], 1),
                _prefix([("a", None), ("b", None), ("c", None)], 1),
                _prefix([("a", None), ("b", None), ("d", None)], 1),
            },
        )

    def test_prefixes_carry_only_displayed_chains(self):
        journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "b"),
                **_timeline("p2", "a", "b"),
                **_timeline("p3", "a", "b"),
                **_timeline("p4", "a", "x"),
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "x"), anchor=_anchor("a"), maxRowsPerStep=1),
        )
        results = self._run(query)

        # x lands in step 1's other row, so its label must not ship in the prefixes either: a shared
        # insight exposes the raw response, and the hover preview skips other-bucket chains anyway.
        self.assertEqual(
            self._steps(results),
            [(0, [_row("a", 4)], 0, 0), (1, [_row("b", 3)], 1, 4)],
        )
        self.assertEqual(
            self._prefixes(results),
            {_prefix([("a", None)], 4), _prefix([("a", None), ("b", None)], 3)},
        )

    def test_anchored_prefilter_bounds_actors_to_the_window(self):
        journeys_for(
            team=self.team,
            events_by_person={
                # b sits 40 min past the anchor, beyond the 30 min window, so it never joins the sequence.
                "p1": [
                    {"event": "a", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "b", "timestamp": "2023-03-10 10:40:00"},
                ],
                # No anchor event at all, so this actor is excluded entirely.
                **_timeline("p2", "b", "c"),
                # Anchor plus an in-window step.
                "p3": [
                    {"event": "a", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "b", "timestamp": "2023-03-10 10:20:00"},
                ],
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=_sources("a", "b", "c"), anchor=_anchor("a"), maxRowsPerStep=10),
        )
        results = self._run(query)

        self.assertEqual(
            self._steps(results),
            [(0, [_row("a", 2)], 0, 1), (1, [_row("b", 1)], 0, 1)],
        )
        self.assertEqual(self._edges(results), [_edge(0, _item("a"), _item("b"), 1)])
        self.assertEqual(
            self._prefixes(results),
            {_prefix([("a", None)], 2), _prefix([("a", None), ("b", None)], 1)},
        )

    def test_anchored_keeps_single_sequence_across_a_gap(self):
        # A 45 min gap would split into two journeys in open mode (gap G defaults to 30 min); anchored
        # mode never splits, so with a 60 min window the two events stay one sequence and the edge exists.
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "a", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "b", "timestamp": "2023-03-10 10:45:00"},
                ]
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(
                stepSources=_sources("a", "b"),
                anchor=_anchor("a"),
                conversionWindowInterval=60,
                conversionWindowIntervalUnit=FunnelConversionWindowTimeUnit.MINUTE,
            ),
        )
        results = self._run(query)

        self.assertEqual(
            self._steps(results),
            [(0, [_row("a", 1)], 0, 0), (1, [_row("b", 1)], 0, 1)],
        )
        self.assertEqual(self._edges(results), [_edge(0, _item("a"), _item("b"), 1)])

    def test_anchored_end_anchor_reads_backward(self):
        journeys_for(
            team=self.team,
            events_by_person={
                **_timeline("p1", "a", "b", "x"),
                **_timeline("p2", "c", "b", "x"),
            },
        )

        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(
                stepSources=_sources("a", "b", "c", "x"),
                anchor=_anchor("x", PathsV2AnchorType.END),
                maxRowsPerStep=10,
            ),
        )
        results = self._run(query)

        # End anchor: x is the single 100% node at step 0 and the grid reads backward in time toward it,
        # so p1 becomes [x, b, a] and p2 becomes [x, b, c].
        self.assertEqual(
            self._steps(results),
            [
                (0, [_row("x", 2)], 0, 0),
                (1, [_row("b", 2)], 0, 0),
                (2, [_row("a", 1), _row("c", 1)], 0, 2),
            ],
        )
        self.assertEqual(
            self._edges(results),
            [
                _edge(0, _item("x"), _item("b"), 2),
                _edge(1, _item("b"), _item("a"), 1),
                _edge(1, _item("b"), _item("c"), 1),
            ],
        )
        self.assertEqual(
            self._prefixes(results),
            {
                _prefix([("x", None)], 2),
                _prefix([("x", None), ("b", None)], 2),
                _prefix([("x", None), ("b", None), ("a", None)], 1),
                _prefix([("x", None), ("b", None), ("c", None)], 1),
            },
        )
